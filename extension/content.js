let floatingBtn = null;
let downloadDialog = null;
let linkHoverBtn = null;
let linkHoverTarget = null;
let linkHoverHideTimer = null;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "show_video_button") {
        showFloatingButton(msg.url, msg.mediaType, msg.filename);
    } else if (msg.type === "show_download_dialog") {
        showDownloadDialog(msg.url, msg.filename, msg.downloadId);
        // Acknowledge receipt
        sendResponse({received: true});
    }
});

// --- Known video PAGE detection (YouTube, Vimeo, etc.) ---
// The webRequest-based sniffer further below watches raw network traffic for
// video content-types — that works for generic self-hosted/HLS players, but
// NOT reliably for YouTube: its video CDN traffic goes over QUIC/HTTP3 by
// default, which extension webRequest listeners have a long-documented
// history of not seeing at all. And even if it were seen, yt-dlp's YouTube
// extractor needs the canonical watch-page URL, not a raw signed CDN segment
// URL — it would just reject the latter as an unsupported URL. So for known
// video sites we skip network sniffing entirely and watch the tab's own URL
// instead, which sidesteps both problems at once.
const KNOWN_VIDEO_PAGE_PATTERNS = [
    /^https?:\/\/(www\.)?youtube\.com\/watch\?/i,
    /^https?:\/\/(www\.)?youtube\.com\/shorts\//i,
    /^https?:\/\/youtu\.be\//i,
    /^https?:\/\/(www\.)?vimeo\.com\/\d+/i,
    /^https?:\/\/(www\.)?dailymotion\.com\/video\//i,
    /^https?:\/\/(www\.)?facebook\.com\/.*\/videos\//i,
    /^https?:\/\/(www\.)?instagram\.com\/(reel|p)\//i,
    /^https?:\/\/(www\.)?twitch\.tv\/videos\//i,
];

let pageVideoBtn = null;
let lastCheckedHref = "";

function isKnownVideoPage(href) {
    return KNOWN_VIDEO_PAGE_PATTERNS.some((re) => re.test(href));
}

function checkForVideoPage() {
    if (location.href === lastCheckedHref) return;
    lastCheckedHref = location.href;

    if (pageVideoBtn && pageVideoBtn.parentNode) {
        pageVideoBtn.parentNode.removeChild(pageVideoBtn);
    }
    pageVideoBtn = null;

    if (isKnownVideoPage(location.href)) {
        showPageVideoButton(location.href);
    }
}

function showPageVideoButton(pageUrl) {
    pageVideoBtn = document.createElement("div");
    pageVideoBtn.id = "udm-page-video-btn";
    pageVideoBtn.innerHTML = `<span>⬇ Download this video</span>`;
    document.body.appendChild(pageVideoBtn);

    pageVideoBtn.addEventListener("click", () => {
        showQualityPicker(pageUrl, "", () => {
            if (!pageVideoBtn) return;
            pageVideoBtn.innerHTML = `<span>✓ Sent to UDM</span>`;
            setTimeout(() => {
                if (pageVideoBtn && pageVideoBtn.parentNode) {
                    pageVideoBtn.parentNode.removeChild(pageVideoBtn);
                }
                pageVideoBtn = null;
            }, 2500);
        });
    });
}

// --- Quality picker -------------------------------------------------------
// Opens when a "Download this video" button is clicked. Asks UDM which
// qualities this video really has (so we never offer 4K on a 720p video),
// then sends the chosen one along with the download request. If the list
// can't be fetched, "Best available" still works.
let qualityPicker = null;

function closeQualityPicker() {
    if (qualityPicker && qualityPicker.parentNode) {
        qualityPicker.parentNode.removeChild(qualityPicker);
    }
    qualityPicker = null;
}

function formatQualitySize(bytes) {
    if (!bytes) return "";
    const mb = bytes / (1024 * 1024);
    return mb >= 1024 ? `~${(mb / 1024).toFixed(1)} GB` : `~${Math.round(mb)} MB`;
}

function showQualityPicker(url, filename, onChosen) {
    if (qualityPicker) return;

    qualityPicker = document.createElement("div");
    qualityPicker.id = "udm-quality-picker";

    const header = document.createElement("div");
    header.className = "udm-header";
    header.textContent = "⬇ Choose quality";

    const body = document.createElement("div");
    body.className = "udm-body";
    body.textContent = "Checking available qualities…";

    const footer = document.createElement("div");
    footer.className = "udm-footer";
    const cancelBtn = document.createElement("button");
    cancelBtn.id = "udm-quality-cancel";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", closeQualityPicker);
    footer.appendChild(cancelBtn);

    qualityPicker.append(header, body, footer);
    document.body.appendChild(qualityPicker);

    const choose = (quality) => {
        chrome.runtime.sendMessage({
            type: "trigger_video_download",
            url: url,
            filename: filename,
            quality: quality,
        });
        closeQualityPicker();
        if (onChosen) onChosen();
    };

    const addOption = (label, quality, sub) => {
        const btn = document.createElement("button");
        btn.className = "udm-quality-option";
        const main = document.createElement("span");
        main.textContent = label;
        btn.appendChild(main);
        if (sub) {
            const small = document.createElement("small");
            small.textContent = sub;
            btn.appendChild(small);
        }
        btn.addEventListener("click", () => choose(quality));
        body.appendChild(btn);
    };

    chrome.runtime.sendMessage({ type: "get_video_formats", url: url }, (response) => {
        if (!qualityPicker) return; // cancelled while loading
        body.textContent = "";

        const options = (!chrome.runtime.lastError && response && response.options) || [];

        addOption("Best available", "best", "Highest quality UDM can find");
        options.forEach((o) => addOption(o.label, o.quality, formatQualitySize(o.size)));
        addOption("Audio only", "audio", "No video");

        if (!options.length) {
            const note = document.createElement("div");
            note.className = "udm-quality-note";
            note.textContent = "Couldn't list individual qualities for this video.";
            body.appendChild(note);
        }
    });
}

// YouTube/Vimeo/etc. are single-page apps — navigating between videos does
// NOT reload the page, so there's no load event to hook. A cheap poll is the
// standard, reliable way content scripts detect SPA navigation.
checkForVideoPage();
setInterval(checkForVideoPage, 1500);

function showDownloadDialog(url, filename, downloadId) {
    if (downloadDialog) {
        return;
    }
    
    downloadDialog = document.createElement("div");
    downloadDialog.id = "udm-download-dialog";
    downloadDialog.innerHTML = `
        <div class="udm-dialog-content">
            <div class="udm-header">⬇ UDM Download</div>
            <div class="udm-body">
                <p>Do you want to download this file?</p>
                <div class="udm-filename" title="${filename}">${filename}</div>
            </div>
            <div class="udm-footer">
                <button id="udm-btn-cancel">Cancel</button>
                <button id="udm-btn-start">Start Download</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(downloadDialog);
    
    document.getElementById("udm-btn-start").addEventListener("click", () => {
        chrome.runtime.sendMessage({
            type: "trigger_download",
            url: url,
            filename: filename,
            downloadId: downloadId,
            auto_start: true 
        });
        closeDownloadDialog();
    });
    
    document.getElementById("udm-btn-cancel").addEventListener("click", () => {
        chrome.runtime.sendMessage({
            type: "cancel_download",
            downloadId: downloadId
        });
        closeDownloadDialog();
    });
}

function closeDownloadDialog() {
    if (downloadDialog && downloadDialog.parentNode) {
        downloadDialog.parentNode.removeChild(downloadDialog);
    }
    downloadDialog = null;
}

// Every extension UDM will proactively offer to grab — kept in one place so
// the click-interception below and the hover badge stay in sync. This is
// intentionally broader than before: it now also covers types Chrome
// normally renders INLINE instead of downloading (PDFs, some doc formats),
// which previously slipped through entirely since the browser never even
// started a "download" for them.
const DOWNLOAD_EXTENSIONS = [
    // Archives
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".tgz",
    // Executables / installers
    ".exe", ".msi", ".dmg", ".deb", ".rpm", ".apk", ".appx", ".bin",
    // Documents (Chrome often renders these inline rather than downloading)
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".csv",
    // Video
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp", ".mpg", ".mpeg",
    // Audio
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus",
    // Ebooks
    ".epub", ".mobi", ".azw3", ".djvu",
    // Misc
    ".torrent", ".srt", ".sub", ".psd", ".ai", ".eps",
];

function getPathname(href) {
    try {
        return new URL(href).pathname.toLowerCase();
    } catch {
        return "";
    }
}

function matchesDownloadExtension(pathname) {
    return DOWNLOAD_EXTENSIONS.some((ext) => pathname.endsWith(ext));
}

// Intercept clicks on links to prevent the browser from handling the download
document.addEventListener("click", function(e) {
    // Find the closest anchor tag
    const link = e.target.closest("a");
    if (!link || !link.href) return;

    const pathname = getPathname(link.href);
    const isDownloadFile = matchesDownloadExtension(pathname);
    const hasDownloadAttr = link.hasAttribute("download");

    if (isDownloadFile || hasDownloadAttr) {
        e.preventDefault();
        e.stopPropagation();

        let filename = "download";
        if (hasDownloadAttr && link.getAttribute("download")) {
            filename = link.getAttribute("download");
        } else {
            const parts = pathname.split("/");
            filename = decodeURIComponent(parts[parts.length - 1] || "download");
        }

        // Show our custom UDM web dialog immediately
        showDownloadDialog(link.href, filename, null);
    }
}, true); // Use capture phase to intercept before other scripts

// --- Hover badge: shows a small "⬇" next to a qualifying link BEFORE the
// user even clicks it, matching IDM's link-hover behavior. This is purely
// an accelerator (one click = send straight to UDM, skipping the confirm
// dialog); clicking the link itself still goes through the dialog above.
document.addEventListener("mouseover", function (e) {
    const link = e.target.closest("a");
    if (!link || !link.href) return;

    const pathname = getPathname(link.href);
    if (!matchesDownloadExtension(pathname) && !link.hasAttribute("download")) {
        return;
    }

    if (linkHoverHideTimer) {
        clearTimeout(linkHoverHideTimer);
        linkHoverHideTimer = null;
    }

    if (linkHoverTarget === link && linkHoverBtn) {
        return; // already showing for this link
    }

    linkHoverTarget = link;
    showLinkHoverBadge(link, pathname);
}, true);

document.addEventListener("mouseout", function (e) {
    if (!linkHoverBtn) return;
    const toElement = e.relatedTarget;
    // Don't hide if the mouse is moving onto the badge itself
    if (toElement && linkHoverBtn.contains(toElement)) return;

    linkHoverHideTimer = setTimeout(hideLinkHoverBadge, 400);
}, true);

function showLinkHoverBadge(link, pathname) {
    hideLinkHoverBadge();

    const rect = link.getBoundingClientRect();
    linkHoverBtn = document.createElement("div");
    linkHoverBtn.id = "udm-link-hover-btn";
    linkHoverBtn.innerHTML = "⬇";
    linkHoverBtn.style.top = `${window.scrollY + rect.top - 10}px`;
    linkHoverBtn.style.left = `${window.scrollX + rect.right - 6}px`;

    linkHoverBtn.addEventListener("mouseenter", () => {
        if (linkHoverHideTimer) {
            clearTimeout(linkHoverHideTimer);
            linkHoverHideTimer = null;
        }
    });
    linkHoverBtn.addEventListener("mouseleave", () => {
        linkHoverHideTimer = setTimeout(hideLinkHoverBadge, 200);
    });

    linkHoverBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();

        const parts = pathname.split("/");
        let filename = decodeURIComponent(parts[parts.length - 1] || "download");
        if (link.hasAttribute("download") && link.getAttribute("download")) {
            filename = link.getAttribute("download");
        }

        chrome.runtime.sendMessage({
            type: "trigger_download",
            url: link.href,
            filename: filename,
            downloadId: null,
            auto_start: true,
        });

        hideLinkHoverBadge();
    });

    document.body.appendChild(linkHoverBtn);
}

function hideLinkHoverBadge() {
    if (linkHoverBtn && linkHoverBtn.parentNode) {
        linkHoverBtn.parentNode.removeChild(linkHoverBtn);
    }
    linkHoverBtn = null;
    linkHoverTarget = null;
    if (linkHoverHideTimer) {
        clearTimeout(linkHoverHideTimer);
        linkHoverHideTimer = null;
    }
}

function showFloatingButton(url, mediaType, filename) {
    if (floatingBtn) {
        // Already showing
        return;
    }
    
    floatingBtn = document.createElement("div");
    floatingBtn.id = "udm-floating-btn";
    floatingBtn.innerHTML = `<span>⬇ Download this ${mediaType}</span>`;
    
    // Add it to DOM
    document.body.appendChild(floatingBtn);
    
    floatingBtn.addEventListener("click", () => {
        showQualityPicker(url, filename, () => {
            // Hide button once a quality has been chosen
            if (!floatingBtn) return;
            floatingBtn.style.display = "none";
            setTimeout(() => {
                if (floatingBtn && floatingBtn.parentNode) {
                    floatingBtn.parentNode.removeChild(floatingBtn);
                }
                floatingBtn = null;
            }, 1000);
        });
    });
}
