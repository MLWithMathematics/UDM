"""
Segment assembler - merges completed segment temp files into the final output file.
Handles temp file management and cleanup.
"""

import logging
import os
from pathlib import Path
from typing import List

from udm.core.segment import Segment, SegmentStatus

logger = logging.getLogger("udm.core.assembler")

COPY_BUFFER_SIZE = 1024 * 1024  # 1 MB copy buffer


class Assembler:
    """
    Merges downloaded segment temp files into a single output file.
    Segments must be assembled in order (by segment index/start_byte).
    """

    def __init__(self, output_path: str, temp_dir: str):
        self.output_path = output_path
        self.temp_dir = temp_dir

    def get_temp_path(self, download_id: str, segment_id: int) -> str:
        """Get the temp file path for a segment."""
        return str(Path(self.temp_dir) / f"{download_id}.seg{segment_id}.part")

    def assemble(self, segments: List[Segment]) -> bool:
        """
        Merge all segment temp files into the final output file.
        
        Args:
            segments: List of segments (must all be DONE status).
        
        Returns:
            True if assembly was successful.
        """
        # Sort segments by start_byte to ensure correct order
        sorted_segments = sorted(segments, key=lambda s: s.start_byte)

        # Verify all segments are complete
        for seg in sorted_segments:
            if seg.status != SegmentStatus.DONE:
                logger.error(f"Segment {seg.id} is not complete: {seg.status}")
                return False
            if not seg.temp_file or not Path(seg.temp_file).exists():
                logger.error(f"Segment {seg.id} temp file missing: {seg.temp_file}")
                return False

        # Create output directory if needed
        output_dir = Path(self.output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        # Use .udmpart extension during assembly
        partial_path = self.output_path + ".udmpart"

        try:
            with open(partial_path, "wb") as outfile:
                for seg in sorted_segments:
                    logger.debug(f"Assembling segment {seg.id}: {seg.temp_file}")
                    with open(seg.temp_file, "rb") as infile:
                        while True:
                            chunk = infile.read(COPY_BUFFER_SIZE)
                            if not chunk:
                                break
                            outfile.write(chunk)

            # Atomic rename: .udmpart → final filename
            # Handle case where target already exists
            if Path(self.output_path).exists():
                # Add number suffix to avoid overwrite
                self.output_path = self._get_unique_path(self.output_path)

            os.rename(partial_path, self.output_path)
            logger.info(f"Assembly complete: {self.output_path}")
            return True

        except Exception as e:
            logger.error(f"Assembly failed: {e}")
            # Clean up partial file
            if Path(partial_path).exists():
                try:
                    os.remove(partial_path)
                except OSError:
                    pass
            return False

    def cleanup_temp_files(self, segments: List[Segment]):
        """Remove all segment temp files after successful assembly."""
        for seg in segments:
            if seg.temp_file and Path(seg.temp_file).exists():
                try:
                    os.remove(seg.temp_file)
                    logger.debug(f"Cleaned up temp file: {seg.temp_file}")
                except OSError as e:
                    logger.warning(f"Failed to remove temp file {seg.temp_file}: {e}")

    def cleanup_all(self, download_id: str):
        """Remove all temp files for a download (including partial assembly)."""
        temp_dir = Path(self.temp_dir)
        if temp_dir.exists():
            for f in temp_dir.glob(f"{download_id}.*"):
                try:
                    f.unlink()
                except OSError:
                    pass

    @staticmethod
    def _get_unique_path(filepath: str) -> str:
        """Generate a unique file path by adding a number suffix."""
        path = Path(filepath)
        stem = path.stem
        ext = path.suffix
        parent = path.parent
        counter = 1
        while path.exists():
            path = parent / f"{stem} ({counter}){ext}"
            counter += 1
        return str(path)

    @staticmethod
    def ensure_temp_dir(temp_dir: str) -> str:
        """Create the temp directory if it doesn't exist."""
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        return temp_dir
