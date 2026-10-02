/**
 * UDM Browser Extension - Background Service Worker
 *
 * Adds a right-click context menu item "Download with UDM"
 * and sends the URL to the UDM desktop app via WebSocket.
 *
 * TIER 1 HARDENING (this revision):
 *  - Every message to UDM carries a pairing token (set in the popup),
 *    checked against the token UDM generated in ~/.udm/config.json.
 *    Without this, any local webpage could open a WebSocket to
 *    ws://localhost:19615 itself and silently trigger downloads.
 *  - We no longer cancel/erase the browser's own download until UDM
 *    has actually confirmed success. Previously `onDeterminingFilename`
 *    erased every download unconditionally, racing ahead of the more
 *    careful logic in `onCreated` — if UDM wasn't running, or the
 *    request failed, the file was just gone. Now there is exactly one
 *    place that decides to cancel/erase: after a confirmed "ok" from UDM.
 */

const UDM_WS_URL = "ws://localhost:19615";
const DEFAULT_TIMEOUT_MS = 4000;   // plain file downloads (HEAD probe + queue add)
const VIDEO_TIMEOUT_MS = 30000;    // video resolution via yt-dlp can be slow

// Create context menu on install
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "udm-download-link",
    title: "⬇️ Download with UDM",
    contexts: ["link"],
  });

  chrome.contextMenus.create({
    id: "udm-download-page",
    title: "⬇️ Send Page URL to UDM",
    contexts: ["page"],
  });

  console.log("UDM extension installed");
});

// Handle context menu clicks
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  let url = "";
  let referrer = "";

  if (info.menuItemId === "udm-download-link") {
    url = info.linkUrl;
    referrer = info.pageUrl || "";
  } else if (info.menuItemId === "udm-download-page") {
    url = info.pageUrl;
  }

  if (url) {
    await sendToUDM({
      type: "download",
      url: url,
      referrer: referrer,
      filename: extractFilename(url),
      user_agent: navigator.userAgent,
      auto_start: true,
    });
  }
});

/** Read the pairing token the user saved via the popup. */
function getToken() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["udmToken"], (result) => {
      resolve(result.udmToken || "");
    });
  });
}

/**
 * Send a request to UDM via WebSocket and wait for its real response
 * (not just "message sent"). Resolves { success, message }.
 */
function sendToUDM(data, timeoutMs = DEFAULT_TIMEOUT_MS) {
  return new Promise(async (resolve) => {
    const token = await getToken();
    const payload = { ...data, token };

    try {
      const ws = new WebSocket(UDM_WS_URL);
      let resolved = false;

      const finish = (result) => {
        if (resolved) return;
        resolved = true;
        clearTimeout(timeout);
        try { ws.close(); } catch (e) {}
        resolve(result);
      };

      const timeout = setTimeout(() => {
        finish({ success: false, message: "UDM did not respond in time" });
      }, timeoutMs);

      ws.onopen = () => {
        ws.send(JSON.stringify(payload));
        console.log("Sent to UDM:", payload.type, payload.url);
      };

      ws.onmessage = (event) => {
        try {
          const response = JSON.parse(event.data);
          console.log("UDM response:", response);
          finish({
            success: response.status === "ok",
            message: response.message || "",
            data: response,
          });
        } catch (e) {
          finish({ success: false, message: "Invalid response from UDM" });
        }
      };

      ws.onerror = () => {
        chrome.action.setBadgeText({ text: "!" });
        chrome.action.setBadgeBackgroundColor({ color: "#ef5350" });
        setTimeout(() => chrome.action.setBadgeText({ text: "" }), 3000);
        finish({ success: false, message: "Could not connect to UDM" });
      };
    } catch (error) {
      console.error("Failed to connect to UDM:", error);
      resolve({ success: false, message: String(error) });
    }
  });
}

/** Extract filename from URL. */
function extractFilename(url) {
  try {
    const pathname = new URL(url).pathname;
    const parts = pathname.split("/");
    const name = parts[parts.length - 1];
    return decodeURIComponent(name || "download");
  } catch {
    return "download";
  }
}

// Downloads we've already handed off to UDM (so we don't double-handle them).
const interceptedDownloads = new Set();

// --- Hiding Chrome's own download popup -----------------------------------
// Chrome shows its download bubble the instant a download is created —
// before any extension code gets a chance to run — so racing it is
// impossible. The supported fix is chrome.downloads.setUiOptions (needs the
// "downloads.ui" permission): keep Chrome's download UI hidden by default,
// and switch it back on ONLY while a download has been handed back to
// Chrome (UDM unreachable, you pressed Cancel, a blob: download...), so
// nothing Chrome is genuinely downloading ever becomes invisible.
// Can be turned off from the extension popup.
let hideNativeUiPref = true;
const nativeFallbackIds = new Set();

function applyNativeUi() {
  if (!chrome.downloads.setUiOptions) return; // Chrome < 105
  const enabled = !hideNativeUiPref || nativeFallbackIds.size > 0;
  try {
    const result = chrome.downloads.setUiOptions({ enabled });
    if (result && result.catch) {
      result.catch((e) => console.log("setUiOptions:", e && e.message));
    }
  } catch (e) {
    console.log("setUiOptions failed:", e);
  }
}

function letChromeHandle(downloadId) {
  nativeFallbackIds.add(downloadId);
  applyNativeUi();
}

function resumeNatively(downloadId) {
  letChromeHandle(downloadId);
  chrome.downloads.resume(downloadId);
}

chrome.downloads.onChanged.addListener((delta) => {
  if (!nativeFallbackIds.has(delta.id) || !delta.state) return;
  if (delta.state.current === "complete" || delta.state.current === "interrupted") {
    nativeFallbackIds.delete(delta.id);
    applyNativeUi();
  }
});

chrome.storage.local.get(["udmHideNativeUi"], (result) => {
  hideNativeUiPref = result.udmHideNativeUi !== false;
  applyNativeUi();
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.udmHideNativeUi) {
    hideNativeUiPref = changes.udmHideNativeUi.newValue !== false;
    applyNativeUi();
  }
});


// Handle messages from content script
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg.type === "trigger_download") {
      try {
        let cookieString = "";
        try {
          // Use `url`, not `domain` — domain-scoped lookups miss cookies set
          // on a parent domain (common on CDN subdomains) that the browser
          // would still send for this exact request URL.
          const cookies = await chrome.cookies.getAll({ url: msg.url });
          cookieString = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
        } catch (e) {
          console.log("Could not get cookies:", e);
        }

        const { success } = await sendToUDM({
          type: "download",
          url: msg.url,
          filename: msg.filename,
          referrer: msg.referrer || (sender.tab ? sender.tab.url : ""),
          cookies: cookieString,
          user_agent: navigator.userAgent,
          auto_start: msg.auto_start,
        });

        if (success && msg.downloadId) {
          interceptedDownloads.add(msg.downloadId);
          chrome.downloads.cancel(msg.downloadId);
          chrome.downloads.erase({ id: msg.downloadId });
        } else if (msg.downloadId) {
          // UDM failed or is unreachable — let Chrome finish it natively
          // rather than losing the file.
          resumeNatively(msg.downloadId);
        }
      } catch (e) {
        console.error("Error triggering download:", e);
        if (msg.downloadId) resumeNatively(msg.downloadId);
      }
    } else if (msg.type === "cancel_download") {
      if (msg.downloadId) {
        resumeNatively(msg.downloadId);
      }
    } else if (msg.type === "trigger_video_download") {
      let cookieString = "";
      try {
        const cookies = await chrome.cookies.getAll({ url: msg.url });
        cookieString = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
      } catch (e) {
        console.log("Could not get cookies for video:", e);
      }

      await sendToUDM(
        {
          type: "video_download",
          url: msg.url,
          filename: msg.filename,
          referrer: sender.tab ? sender.tab.url : "",
          cookies: cookieString,
          user_agent: navigator.userAgent,
          quality: msg.quality || "best",
        },
        VIDEO_TIMEOUT_MS
      );
    } else if (msg.type === "get_video_formats") {
      let cookieString = "";
      try {
        const cookies = await chrome.cookies.getAll({ url: msg.url });
        cookieString = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
      } catch (e) {}

      const result = await sendToUDM(
        {
          type: "video_formats",
          url: msg.url,
          referrer: sender.tab ? sender.tab.url : "",
          cookies: cookieString,
          user_agent: navigator.userAgent,
        },
        VIDEO_TIMEOUT_MS * 2
      );
      sendResponse({
        success: result.success,
        message: result.message,
        options: (result.data && result.data.options) || [],
      });
    }
  })();
  return true; // keep the message channel open for the async work above
});

// Fires before Chrome would show its own Save-As dialog. We no longer
// cancel/erase here (that used to race with `onCreated` below and could
// discard downloads if UDM wasn't running) — we just let filename
// resolution proceed normally. The actual take-over decision happens
// exclusively in `onCreated`.
chrome.downloads.onDeterminingFilename.addListener((downloadItem, suggest) => {
  suggest();
});

const EXTENSION_START_TIME = new Date(Date.now() - 5000); // 5 second buffer

function getAutoConfirm() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["udmAutoConfirm"], (result) => {
      resolve(!!result.udmAutoConfirm);
    });
  });
}

// Automatically intercept file downloads — this is the single authoritative
// interception path.
chrome.downloads.onCreated.addListener(async (downloadItem) => {
  const itemStartTime = new Date(downloadItem.startTime);
  if (itemStartTime < EXTENSION_START_TIME) {
    console.log("Ignoring old download from browser startup:", downloadItem.url);
    if (downloadItem.state === "in_progress") letChromeHandle(downloadItem.id);
    return;
  }

  if (
    downloadItem.state !== "in_progress" ||
    interceptedDownloads.has(downloadItem.id) ||
    downloadItem.url.startsWith("blob:") ||
    downloadItem.url.startsWith("data:")
  ) {
    if (downloadItem.state === "in_progress" && !interceptedDownloads.has(downloadItem.id)) {
      letChromeHandle(downloadItem.id);
    }
    return;
  }

  console.log("Caught download:", downloadItem.url);

  // Pause first thing, synchronously — already as fast as the API allows.
  // Nothing below can make Chrome's own "download started" indicator not
  // have appeared; only the OS Save-As dialog (a separate Chrome setting,
  // chrome://settings/downloads → "Ask where to save each file") can be
  // avoided entirely, and only by turning that setting off — no extension
  // API can suppress it, since it's shown before onCreated even fires.
  chrome.downloads.pause(downloadItem.id);

  const autoConfirm = await getAutoConfirm();
  if (autoConfirm) {
    // Skip the confirm-dialog round trip entirely — straight to UDM. This
    // removes two message hops (background → content script → background)
    // and the wait for a human click, so the window where Chrome's own UI
    // is visible is as short as it can be: bounded only by the WebSocket
    // round trip to UDM instead of also including dialog + reaction time.
    let cookieString = "";
    try {
      const cookies = await chrome.cookies.getAll({
        url: downloadItem.finalUrl || downloadItem.url,
      });
      cookieString = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    } catch (e) {}

    const { success } = await sendToUDM({
      type: "download",
      url: downloadItem.finalUrl || downloadItem.url,
      filename:
        downloadItem.filename ||
        extractFilename(downloadItem.finalUrl || downloadItem.url),
      referrer: downloadItem.referrer || "",
      cookies: cookieString,
      user_agent: navigator.userAgent,
      auto_start: true,
    });
    if (success) {
      interceptedDownloads.add(downloadItem.id);
      chrome.downloads.cancel(downloadItem.id);
      chrome.downloads.erase({ id: downloadItem.id });
    } else {
      resumeNatively(downloadItem.id);
    }
    return;
  }

  chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
    if (tabs.length > 0 && tabs[0].url && !tabs[0].url.startsWith("chrome://")) {
      chrome.tabs.sendMessage(
        tabs[0].id,
        {
          type: "show_download_dialog",
          url: downloadItem.finalUrl || downloadItem.url,
          filename:
            downloadItem.filename ||
            extractFilename(downloadItem.finalUrl || downloadItem.url),
          downloadId: downloadItem.id,
        },
        async (response) => {
          if (chrome.runtime.lastError) {
            // Content script not loaded on this page — fall back to
            // sending straight to UDM, and honor the real result.
            const { success } = await sendToUDM({
              type: "download",
              url: downloadItem.finalUrl || downloadItem.url,
              filename:
                downloadItem.filename ||
                extractFilename(downloadItem.finalUrl || downloadItem.url),
              referrer: tabs[0].url,
              cookies: "",
              user_agent: navigator.userAgent,
              auto_start: false,
            });
            if (success) {
              interceptedDownloads.add(downloadItem.id);
              chrome.downloads.cancel(downloadItem.id);
              chrome.downloads.erase({ id: downloadItem.id });
            } else {
              resumeNatively(downloadItem.id);
            }
          }
        }
      );
    } else {
      (async () => {
        const { success } = await sendToUDM({
          type: "download",
          url: downloadItem.finalUrl || downloadItem.url,
          filename:
            downloadItem.filename ||
            extractFilename(downloadItem.finalUrl || downloadItem.url),
          referrer: "",
          cookies: "",
          user_agent: navigator.userAgent,
          auto_start: false,
        });
        if (success) {
          interceptedDownloads.add(downloadItem.id);
          chrome.downloads.cancel(downloadItem.id);
          chrome.downloads.erase({ id: downloadItem.id });
        } else {
          resumeNatively(downloadItem.id);
        }
      })();
    }
  });
});

// Video Sniffer — flags likely video responses (non-YouTube included) so
// content.js can show the floating "Download this video" button.
chrome.webRequest.onResponseStarted.addListener(
  (details) => {
    if (details.tabId === -1) return;

    let isVideo = false;
    let mediaType = "video/mp4";

    const urlLower = details.url.toLowerCase();

    if (urlLower.includes(".m3u8") || urlLower.endsWith(".mp4") || urlLower.endsWith(".ts")) {
      isVideo = true;
      if (urlLower.includes(".m3u8")) mediaType = "application/x-mpegURL";
    }

    if (!isVideo && details.responseHeaders) {
      const ctHeader = details.responseHeaders.find(
        (h) => h.name.toLowerCase() === "content-type"
      );
      if (ctHeader && ctHeader.value && ctHeader.value.toLowerCase().startsWith("video/")) {
        isVideo = true;
        mediaType = ctHeader.value;
      }
    }

    if (isVideo) {
      console.log("Video detected:", details.url);
      if (urlLower.endsWith(".ts")) return;

      chrome.tabs
        .sendMessage(details.tabId, {
          type: "show_video_button",
          url: details.url,
          mediaType: mediaType,
          filename: urlLower.split("?")[0].split("/").pop() || "video.mp4",
        })
        .catch(() => {});
    }
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);
