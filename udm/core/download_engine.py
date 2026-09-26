"""
Multi-threaded segmented download engine - the heart of UDM.

Implements IDM-style dynamic file segmentation:
1. HEAD request → get file size + range support
2. Divide file into N segments
3. Download segments concurrently with Range headers
4. Dynamic re-splitting: idle connections help slow ones
5. Assemble segments into final file
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional, Callable, Dict

from udm.core.segment import (
    Segment, SegmentStatus,
    DownloadTask, DownloadStatus,
    detect_category,
)
from udm.core.assembler import Assembler
from udm.core.speed_limiter import SpeedLimiter
from udm.network.http_client import HttpClient, RangeNotSupportedError

logger = logging.getLogger("udm.core.engine")

# Defaults
DEFAULT_SEGMENTS = 8
MAX_SEGMENTS = 32
MIN_SEGMENT_SIZE = 256 * 1024  # 256 KB minimum per segment
CHUNK_SIZE = 1048576  # 1 MB read chunks (improves download speed dramatically)
PROGRESS_UPDATE_INTERVAL = 0.3  # seconds between progress callbacks
SPEED_CALC_WINDOW = 3.0  # seconds for speed averaging


class DownloadEngine:
    """
    Core download engine with multi-threaded segmented downloading.
    
    Features:
    - Dynamic file segmentation with HTTP Range headers
    - Concurrent segment downloads with asyncio
    - Pause/Resume with segment state persistence
    - Speed calculation and ETA estimation
    - Integration with SpeedLimiter for bandwidth control
    """

    def __init__(
        self,
        speed_limiter: Optional[SpeedLimiter] = None,
        temp_dir: Optional[str] = None,
        default_save_dir: Optional[str] = None,
    ):
        self.speed_limiter = speed_limiter or SpeedLimiter()
        self.temp_dir = temp_dir or str(
            Path.home() / "Downloads" / ".udm_temp"
        )
        self.default_save_dir = default_save_dir or str(
            Path.home() / "Downloads"
        )

        # Active download tracking
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}
        self._pause_events: Dict[str, asyncio.Event] = {}
        self._progress_callbacks: Dict[str, Callable] = {}
        self._speed_data: Dict[str, list] = {}  # download_id -> [(timestamp, bytes)]

        # Ensure temp directory exists
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)

    async def prepare_download(
        self,
        url: str,
        save_path: Optional[str] = None,
        filename: Optional[str] = None,
        num_segments: int = DEFAULT_SEGMENTS,
        cookies: Optional[str] = None,
        referrer: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> DownloadTask:
        """
        Prepare a download task: probe the server, create segments.
        Does NOT start downloading yet.
        
        Returns a fully configured DownloadTask ready for start_download().
        """
        client = HttpClient(
            user_agent=user_agent,
            cookies=cookies,
        )

        try:
            # Step 1: HEAD request to get file metadata
            # Auto-derive referrer from URL origin if not provided
            if not referrer:
                referrer = client._derive_referrer(url)

            info = await client.get_file_info(url, referrer=referrer)
            logger.info(f"File info: {info}")

            # Handle anti-hotlink redirects: use original URL instead of
            # the redirected one (e.g. homepage) for the actual download
            was_redirected = info.get("redirected", False)
            if was_redirected:
                download_url = info.get("original_url", url)
                logger.warning(
                    f"Using original URL for download (redirect detected): {download_url}"
                )
            else:
                download_url = info.get("final_url", url)

            # Use user-provided filename, then filename from URL path
            # (not from redirect target), then server-detected filename
            if not filename:
                # Always try the original URL first for the filename
                from urllib.parse import urlparse, unquote
                from pathlib import PurePosixPath
                orig_parsed = urlparse(url)
                orig_name = unquote(PurePosixPath(orig_parsed.path.rstrip("/")).name)
                if orig_name and "." in orig_name and not orig_name.startswith("."):
                    filename = orig_name
                elif not was_redirected:
                    # Try the final URL (only if it wasn't an anti-hotlink redirect)
                    final_parsed = urlparse(download_url)
                    final_name = unquote(PurePosixPath(final_parsed.path.rstrip("/")).name)
                    if final_name and "." in final_name and not final_name.startswith("."):
                        filename = final_name

                if not filename:
                    filename = info.get("filename", "download")

            # Ensure filename has a proper extension based on content_type
            # if the filename has no extension or is just "download"
            content_type = info.get("content_type", "")
            ct_base = content_type.lower().split(";")[0].strip() if content_type else ""
            name_stem, name_ext = os.path.splitext(filename)
            if not name_ext or name_ext == ".":
                # No extension — try to derive from content_type
                ext = HttpClient.CONTENT_TYPE_EXTENSIONS.get(ct_base, "")
                if ext:
                    filename = f"{filename}{ext}"
                    logger.info(f"Added extension from content_type: {filename}")

            # Create the download task
            task = DownloadTask(
                url=download_url,
                filename=filename,
                save_path=save_path or self.default_save_dir,
                total_size=info["total_size"],
                supports_range=info["supports_range"],
                etag=info.get("etag"),
                last_modified=info.get("last_modified"),
                content_type=info.get("content_type"),
                cookies=cookies,
                referrer=referrer,
                user_agent=user_agent,
                num_segments=num_segments,
            )

            # Auto-detect category
            task.category = detect_category(task.filename)

            # Step 2: Create segments
            if task.supports_range and task.total_size > 0:
                # Calculate optimal number of segments
                effective_segments = min(
                    num_segments,
                    MAX_SEGMENTS,
                    max(1, task.total_size // MIN_SEGMENT_SIZE),
                )
                task.num_segments = effective_segments
                task.segments = self._create_segments(
                    task.id, task.total_size, effective_segments
                )
            else:
                # No range support or unknown size: single segment, full download
                task.num_segments = 1
                task.segments = [
                    Segment(
                        id=0,
                        download_id=task.id,
                        start_byte=0,
                        end_byte=max(task.total_size - 1, 0),
                        temp_file=str(
                            Path(self.temp_dir) / f"{task.id}.seg0.part"
                        ),
                    )
                ]
                task.supports_range = False  # Force non-range path

            logger.info(
                f"Prepared download: {task.filename} "
                f"({task.total_size} bytes, {task.num_segments} segments)"
            )
            return task

        finally:
            await client.close()

    def _create_segments(
        self, download_id: str, total_size: int, num_segments: int
    ) -> list[Segment]:
        """Divide file into equal segments with byte ranges."""
        segments = []
        segment_size = total_size // num_segments
        remainder = total_size % num_segments

        start = 0
        for i in range(num_segments):
            # Distribute remainder bytes across first segments
            size = segment_size + (1 if i < remainder else 0)
            end = start + size - 1

            seg = Segment(
                id=i,
                download_id=download_id,
                start_byte=start,
                end_byte=end,
                temp_file=str(
                    Path(self.temp_dir) / f"{download_id}.seg{i}.part"
                ),
            )
            segments.append(seg)
            start = end + 1

        return segments

    async def start_download(
        self,
        task: DownloadTask,
        on_progress: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ):
        """
        Start downloading a task. Runs segments concurrently.
        
        Args:
            task: The prepared DownloadTask.
            on_progress: Callback(task) called periodically with updated task.
            on_complete: Callback(task) called when download finishes.
            on_error: Callback(task, error_msg) called on failure.
        """
        if task.id in self._active_tasks:
            logger.warning(f"Download {task.id} is already active")
            return

        # Setup control events
        cancel_event = asyncio.Event()
        pause_event = asyncio.Event()
        pause_event.set()  # Not paused initially

        self._cancel_events[task.id] = cancel_event
        self._pause_events[task.id] = pause_event
        if on_progress:
            self._progress_callbacks[task.id] = on_progress
        self._speed_data[task.id] = []

        # Launch the download coroutine
        async_task = asyncio.create_task(
            self._run_download(task, cancel_event, pause_event,
                               on_progress, on_complete, on_error)
        )
        self._active_tasks[task.id] = async_task

    async def _run_download(
        self,
        task: DownloadTask,
        cancel_event: asyncio.Event,
        pause_event: asyncio.Event,
        on_progress: Optional[Callable],
        on_complete: Optional[Callable],
        on_error: Optional[Callable],
    ):
        """Internal: orchestrate the full download lifecycle."""
        task.status = DownloadStatus.DOWNLOADING
        client = HttpClient(
            user_agent=task.user_agent,
            cookies=task.cookies,
        )

        try:
            # Download all segments concurrently
            if task.supports_range:
                segment_tasks = []
                for segment in task.segments:
                    if segment.status == SegmentStatus.DONE:
                        continue  # Skip already-completed segments (resume)
                    seg_task = asyncio.create_task(
                        self._download_segment(
                            client, task, segment,
                            cancel_event, pause_event, on_progress
                        )
                    )
                    segment_tasks.append(seg_task)

                # Wait for all segments
                if segment_tasks:
                    try:
                        await asyncio.gather(*segment_tasks)
                    except RangeNotSupportedError:
                        logger.warning("Server does not support range requests. Falling back to single-connection download.")
                        task.supports_range = False
                        
                        # Cancel any running segment tasks
                        for st in segment_tasks:
                            if not st.done():
                                st.cancel()
                                
                        # Remove all segments except the first one
                        task.segments = [task.segments[0]]
                        task.segments[0].end_byte = task.total_size - 1 if task.total_size else 0
                        task.segments[0].total_bytes = task.total_size if task.total_size else 0
                        
                        # Reset the first segment's downloaded_bytes to 0 and clear its temp file
                        task.segments[0].downloaded_bytes = 0
                        with open(task.segments[0].temp_file, 'wb') as f:
                            pass
                            
                        # Single-segment full download (no range support)
                        await self._download_full_file(
                            client, task, task.segments[0],
                            cancel_event, pause_event, on_progress
                        )
            else:
                # Single-segment full download (no range support)
                await self._download_full_file(
                    client, task, task.segments[0],
                    cancel_event, pause_event, on_progress
                )

            # Check if cancelled
            if cancel_event.is_set():
                task.status = DownloadStatus.PAUSED
                logger.info(f"Download paused: {task.filename}")
                return

            # Check all segments complete
            all_done = all(s.status == SegmentStatus.DONE for s in task.segments)
            if not all_done:
                error_segs = [s for s in task.segments if s.status == SegmentStatus.ERROR]
                if error_segs:
                    msg = f"{len(error_segs)} segment(s) failed"
                    task.status = DownloadStatus.ERROR
                    task.error_message = msg
                    if on_error:
                        on_error(task, msg)
                    return

            # Assemble segments into final file
            task.status = DownloadStatus.MERGING
            task.update_downloaded_size()
            if on_progress:
                on_progress(task)

            assembler = Assembler(task.output_filepath, self.temp_dir)

            if len(task.segments) == 1 and not task.supports_range:
                # Single-file download: just rename temp file to output
                import shutil
                seg = task.segments[0]
                output_dir = Path(task.save_path)
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = task.output_filepath
                if Path(output_path).exists():
                    output_path = assembler._get_unique_path(output_path)
                try:
                    shutil.move(seg.temp_file, output_path)
                    success = True
                    logger.info(f"Moved temp file to: {output_path}")
                except Exception as e:
                    logger.error(f"Failed to move file: {e}")
                    success = False
            else:
                success = assembler.assemble(task.segments)
                if success:
                    assembler.cleanup_temp_files(task.segments)

            if success:
                task.status = DownloadStatus.COMPLETED
                task.completed_at = time.time()
                task.speed = 0
                logger.info(f"Download complete: {task.filename}")
                if on_complete:
                    on_complete(task)
            else:
                task.status = DownloadStatus.ERROR
                task.error_message = "Assembly failed"
                if on_error:
                    on_error(task, "Assembly failed")

        except asyncio.CancelledError:
            task.status = DownloadStatus.PAUSED
            logger.info(f"Download cancelled: {task.filename}")
        except Exception as e:
            task.status = DownloadStatus.ERROR
            task.error_message = str(e)
            logger.error(f"Download error: {task.filename} - {e}")
            if on_error:
                on_error(task, str(e))
        finally:
            await client.close()
            self._cleanup_tracking(task.id)
            if on_progress:
                on_progress(task)

    async def _download_segment(
        self,
        client: HttpClient,
        task: DownloadTask,
        segment: Segment,
        cancel_event: asyncio.Event,
        pause_event: asyncio.Event,
        on_progress: Optional[Callable],
    ):
        """Download a single segment (with Range header) with pause/cancel support."""
        segment.status = SegmentStatus.ACTIVE
        last_progress_time = time.monotonic()

        try:
            # Open temp file in append mode for resume support
            mode = "ab" if segment.downloaded_bytes > 0 else "wb"
            
            # Calculate the actual start byte (accounting for already downloaded)
            actual_start = segment.current_offset
            
            with open(segment.temp_file, mode) as f:
                async for chunk in client.download_range(
                    task.url,
                    actual_start,
                    segment.end_byte,
                    referrer=task.referrer,
                    etag=task.etag,
                    chunk_size=CHUNK_SIZE,
                ):
                    # Check cancel
                    if cancel_event.is_set():
                        segment.status = SegmentStatus.PAUSED
                        return

                    # Check pause (blocks until unpaused)
                    if not pause_event.is_set():
                        segment.status = SegmentStatus.PAUSED
                        await pause_event.wait()
                        segment.status = SegmentStatus.ACTIVE

                    # Apply speed limit
                    await self.speed_limiter.acquire(task.id, len(chunk))

                    # Enforce segment boundaries (in case server sends too much)
                    remaining = segment.total_bytes - segment.downloaded_bytes
                    if remaining <= 0:
                        break
                    
                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]

                    # Write chunk to temp file
                    f.write(chunk)
                    segment.downloaded_bytes += len(chunk)

                    # Break early if we reached the end of our segment
                    if segment.downloaded_bytes >= segment.total_bytes:
                        # Need to update stats one last time if we break
                        now = time.monotonic()
                        if task.id not in self._speed_data:
                            self._speed_data[task.id] = []
                        self._speed_data[task.id].append((now, len(chunk)))
                        break

                    # Track speed data
                    now = time.monotonic()
                    if task.id not in self._speed_data:
                        self._speed_data[task.id] = []
                    self._speed_data[task.id].append((now, len(chunk)))

                    # Periodic progress update
                    if now - last_progress_time >= PROGRESS_UPDATE_INTERVAL:
                        self._update_task_stats(task)
                        if on_progress:
                            on_progress(task)
                        last_progress_time = now

            if segment.downloaded_bytes < segment.total_bytes:
                raise Exception(f"Connection closed early: downloaded {segment.downloaded_bytes}/{segment.total_bytes} bytes")

            segment.status = SegmentStatus.DONE
            logger.debug(f"Segment {segment.id} complete for {task.filename}")

        except Exception as e:
            if isinstance(e, RangeNotSupportedError):
                raise
            segment.error_count += 1
            if segment.can_retry:
                segment.status = SegmentStatus.PENDING
                logger.warning(
                    f"Segment {segment.id} error (attempt {segment.error_count}): {e}"
                )
                # Retry with exponential backoff
                await asyncio.sleep(2 ** segment.error_count)
                await self._download_segment(
                    client, task, segment, cancel_event, pause_event, on_progress
                )
            else:
                segment.status = SegmentStatus.ERROR
                logger.error(
                    f"Segment {segment.id} failed after {segment.error_count} attempts: {e}"
                )

    async def _download_full_file(
        self,
        client: HttpClient,
        task: DownloadTask,
        segment: Segment,
        cancel_event: asyncio.Event,
        pause_event: asyncio.Event,
        on_progress: Optional[Callable],
    ):
        """
        Download a full file WITHOUT Range headers.
        Used for servers that don't support range requests or when file size is unknown.
        Tracks total_size and downloaded_bytes in real-time.
        """
        segment.status = SegmentStatus.ACTIVE
        last_progress_time = time.monotonic()

        # Reset downloaded bytes since we are restarting from the beginning
        segment.downloaded_bytes = 0
        task.update_downloaded_size()

        try:
            with open(segment.temp_file, "wb") as f:
                async for chunk in client.download_full(
                    task.url,
                    referrer=task.referrer,
                    chunk_size=CHUNK_SIZE,
                ):
                    # Check cancel
                    if cancel_event.is_set():
                        segment.status = SegmentStatus.PAUSED
                        return

                    # Check pause
                    if not pause_event.is_set():
                        segment.status = SegmentStatus.PAUSED
                        await pause_event.wait()
                        segment.status = SegmentStatus.ACTIVE

                    # Apply speed limit
                    await self.speed_limiter.acquire(task.id, len(chunk))

                    # Write chunk
                    f.write(chunk)
                    segment.downloaded_bytes += len(chunk)

                    # Update total_size in real-time for unknown-size files
                    if task.total_size == 0:
                        segment.end_byte = segment.downloaded_bytes - 1
                        task.total_size = segment.downloaded_bytes  # grows as we download

                    # Track speed
                    now = time.monotonic()
                    if task.id not in self._speed_data:
                        self._speed_data[task.id] = []
                    self._speed_data[task.id].append((now, len(chunk)))

                    # Periodic progress update
                    if now - last_progress_time >= PROGRESS_UPDATE_INTERVAL:
                        self._update_task_stats(task)
                        if on_progress:
                            on_progress(task)
                        last_progress_time = now

            # Download done — finalize sizes
            segment.end_byte = segment.downloaded_bytes - 1
            task.total_size = segment.downloaded_bytes
            segment.status = SegmentStatus.DONE
            self._update_task_stats(task)
            logger.info(f"Full file download complete: {task.filename} ({segment.downloaded_bytes} bytes)")

        except Exception as e:
            segment.error_count += 1
            if segment.can_retry:
                segment.status = SegmentStatus.PENDING
                logger.warning(f"Full download error (attempt {segment.error_count}): {e}")
                await asyncio.sleep(2 ** segment.error_count)
                await self._download_full_file(
                    client, task, segment, cancel_event, pause_event, on_progress
                )
            else:
                segment.status = SegmentStatus.ERROR
                logger.error(f"Full download failed after {segment.error_count} attempts: {e}")

    def _update_task_stats(self, task: DownloadTask):
        """Recalculate download speed and ETA."""
        task.update_downloaded_size()

        # Calculate speed from recent data points
        now = time.monotonic()
        speed_data = self._speed_data.get(task.id, [])

        # Remove old data points outside the window
        cutoff = now - SPEED_CALC_WINDOW
        speed_data = [(t, b) for t, b in speed_data if t >= cutoff]
        self._speed_data[task.id] = speed_data

        if len(speed_data) >= 2:
            total_bytes = sum(b for _, b in speed_data)
            time_span = speed_data[-1][0] - speed_data[0][0]
            if time_span > 0:
                task.speed = total_bytes / time_span
            else:
                task.speed = 0
        else:
            task.speed = 0

    async def pause_download(self, task_id: str):
        """Pause an active download."""
        if task_id in self._cancel_events:
            self._cancel_events[task_id].set()
            logger.info(f"Pausing download: {task_id}")

    async def resume_download(
        self,
        task: DownloadTask,
        on_progress: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ):
        """Resume a paused download."""
        if task.status not in (DownloadStatus.PAUSED, DownloadStatus.ERROR):
            logger.warning(f"Cannot resume download {task.id}: status is {task.status}")
            return

        # Verify file hasn't changed on server and update range support
        client = HttpClient(user_agent=task.user_agent, cookies=task.cookies)
        try:
            info = await client.get_file_info(task.url)
            if "supports_range" in info:
                task.supports_range = info["supports_range"]
                
            safe = await client.verify_resume(task.url, task.etag, task.last_modified)
            if not safe:
                logger.warning(f"File changed on server, restarting: {task.filename}")
                # Reset all segments
                for seg in task.segments:
                    seg.downloaded_bytes = 0
                    seg.status = SegmentStatus.PENDING
                task.downloaded_size = 0
        finally:
            await client.close()

        # Re-start the download (segments track their own progress)
        await self.start_download(task, on_progress, on_complete, on_error)

    async def cancel_download(self, task_id: str):
        """Cancel and remove a download. Cleans up temp files."""
        # Signal cancel
        if task_id in self._cancel_events:
            self._cancel_events[task_id].set()

        # Wait for task to finish
        if task_id in self._active_tasks:
            try:
                self._active_tasks[task_id].cancel()
                await asyncio.sleep(0.1)
            except Exception:
                pass

        # Clean up temp files
        assembler = Assembler("", self.temp_dir)
        assembler.cleanup_all(task_id)
        self._cleanup_tracking(task_id)

    def _cleanup_tracking(self, task_id: str):
        """Remove internal tracking data for a download."""
        self._active_tasks.pop(task_id, None)
        self._cancel_events.pop(task_id, None)
        self._pause_events.pop(task_id, None)
        self._progress_callbacks.pop(task_id, None)
        self._speed_data.pop(task_id, None)

    @property
    def active_count(self) -> int:
        """Number of currently active downloads."""
        return len(self._active_tasks)
