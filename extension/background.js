/**
 * UDM Browser Extension - Background Service Worker
 *
 * Adds a right-click context menu item "Download with UDM"
 * and sends the URL to the UDM desktop app via WebSocket.
 *
 * - Every message to UDM carries a pairing token (set in the popup),
 *   checked against the token UDM generated in ~/.udm/config.json.
 * - We never cancel/erase the browser's own download until UDM has actually
 *   confirmed success. There is exactly one place that decides: the
 *   `handedToUdm` / `handedBackToChrome` helpers below.
 *
 * LATENCY / "browser flash" HARDENING (this revision):
 *  - Chrome's download UI is hidden SYNCHRONOUSLY the moment this service
 *    worker starts (and on browser startup), instead of after an async
 *    storage read. The old order meant the first download after a browser
 *    restart or a cold service-worker wake could flash Chrome's own bubble.
 *  - Chrome's filename determination (the step that can pop the OS
 *    "Save As" dialog) is held back for intercepted downloads until UDM has
 *    answered, with a hard cap so a download can never hang.
 *  - If the in-page UDM dialog can't be shown because the content script
 *    isn't loaded in that tab (page opened before the extension was
 *    installed/reloaded), it is injected on demand instead of silently
 *    falling back to UDM's desktop dialog.
 *  - Pairing token and preferences are cached in memory, removing storage
 *    round trips from the hot path.
 */

const UDM_WS_URL = "ws://localhost:19615";
const DEFAULT_TIMEOUT_MS = 4000;   // plain file downloads (HEAD probe + queue add)
const VIDEO_TIMEOUT_MS = 30000;    // video resolution via yt-dlp can be slow

// How long Chrome's filename determination (and with it any Save-As dialog)
// may be held while we wait for UDM. Must stay well below the 30 s idle limit
// of an MV3 service worker.
const FILENAME_HOLD_MS = 8000;

// ---------------------------------------------------------------------------
// Preferences / token cache (kept in memory so the hot path never waits on
// chrome.storage; refreshed at startup and whenever storage changes)
// ---------------------------------------------------------------------------
let hideNativeUiPref = true;   // default: hide Chrome's own download UI
let autoConfirmPref = null;    // null = not loaded yet
let tokenCache = null;         // null = not loaded yet

chrome.storage.local.get(["udmHideNativeUi", "udmAutoConfirm", "udmToken"], (result) => {
  hideNativeUiPref = result.udmHideNativeUi !== false;
  autoConfirmPref = !!result.udmAutoConfirm;
  tokenCache = result.udmToken || "";
  applyNativeUi();
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.udmHideNativeUi) {
    hideNativeUiPref = changes.udmHideNativeUi.newValue !== false;
    applyNativeUi();
  }
  if (changes.udmAutoConfirm) autoConfirmPref = !!changes.udmAutoConfirm.newValue;
  if (changes.udmToken) tokenCache = changes.udmToken.newValue || "";
});

/** Read the pairing token the user saved via the popup. */
function getToken() {
  if (tokenCache !== null) return Promise.resolve(tokenCache);
  return new Promise((resolve) => {
    chrome.storage.local.get(["udmToken"], (result) => {
      tokenCache = result.udmToken || "";
      resolve(tokenCache);
    });
  });
}

function getAutoConfirm() {
  if (autoConfirmPref !== null) return Promise.resolve(autoConfirmPref);
  return new Promise((resolve) => {
    chrome.storage.local.get(["udmAutoConfirm"], (result) => {
      autoConfirmPref = !!result.udmAutoConfirm;
      resolve(autoConfirmPref);
    });
  });
}

// ---------------------------------------------------------------------------
// Context menu
// ---------------------------------------------------------------------------
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

  applyNativeUi();
  console.log("UDM extension installed");
});

chrome.runtime.onStartup.addListener(() => {
  applyNativeUi();
});

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

// ---------------------------------------------------------------------------
// WebSocket request/response to UDM
// ---------------------------------------------------------------------------

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

/** Cookie header string for a URL ("" if unavailable). */
async function collectCookies(url) {
  try {
    // Use `url`, not `domain` — domain-scoped lookups miss cookies set on a
    // parent domain (common on CDN subdomains) that the browser would still
    // send for this exact request URL.
    const cookies = await chrome.cookies.getAll({ url });
    return cookies.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch (e) {
    console.log("Could not get cookies:", e);
    return "";
  }
}

// ---------------------------------------------------------------------------
// Chrome's own download UI
// ---------------------------------------------------------------------------
// Chrome shows its download bubble the instant a download is created —
// before any extension code gets a chance to run — so racing it is
// impossible. The supported fix is chrome.downloads.setUiOptions (needs the
// "downloads.ui" permission): keep Chrome's download UI hidden by default,
// and switch it back on ONLY while a download has been handed back to
// Chrome (UDM unreachable, you pressed Cancel, a blob: download...), so
// nothing Chrome is genuinely downloading ever becomes invisible.
// Can be turned off from the extension popup.
const nativeFallbackIds = new Set();

async function applyNativeUi() {
  if (!chrome.downloads.setUiOptions) return; // Chrome < 105
  const enabled = !hideNativeUiPref || nativeFallbackIds.size > 0;
  try {
    await chrome.downloads.setUiOptions({ enabled });
  } catch (e) {
    console.log("setUiOptions failed:", e && e.message);
  }
}

async function letChromeHandle(downloadId) {
  nativeFallbackIds.add(downloadId);
  await applyNativeUi();
}

async function resumeNatively(downloadId) {
  await letChromeHandle(downloadId);
  chrome.downloads.resume(downloadId);
}

chrome.downloads.onChanged.addListener((delta) => {
  if (!nativeFallbackIds.has(delta.id) || !delta.state) return;
  if (delta.state.current === "complete" || delta.state.current === "interrupted") {
    nativeFallbackIds.delete(delta.id);
    applyNativeUi();
  }
});

// Hide the UI right now, synchronously at service-worker start-up, using the
// default. The stored preference (loaded above) corrects it a moment later if
// the user turned hiding off.
applyNativeUi();

// ---------------------------------------------------------------------------
// Holding Chrome's filename determination (prevents the "Save As" flash)
// ---------------------------------------------------------------------------
// downloadId -> { promise, release }
const filenameGates = new Map();

function holdFilenameDetermination(downloadId) {
  let release;
  const promise = new Promise((resolve) => (release = resolve));
  filenameGates.set(downloadId, { promise, release });
}

function releaseFilenameHold(downloadId) {
  const gate = filenameGates.get(downloadId);
  if (!gate) return;
  gate.release();
  setTimeout(() => filenameGates.delete(downloadId), 60000);
}

// Fires before Chrome would show its own Save-As dialog. For downloads we are
// about to intercept (onCreated opened a gate), wait for UDM's answer — but
// never longer than FILENAME_HOLD_MS. Everything else proceeds immediately.
chrome.downloads.onDeterminingFilename.addListener((downloadItem, suggest) => {
  const gate = filenameGates.get(downloadItem.id);
  if (!gate) {
    suggest();
    return;
  }

  let called = false;
  const proceed = () => {
    if (called) return;
    called = true;
    clearTimeout(timer);
    try { suggest(); } catch (e) {}
  };
  const timer = setTimeout(proceed, FILENAME_HOLD_MS);
  gate.promise.then(proceed);
  return true; // we will call suggest() asynchronously
});

// ---------------------------------------------------------------------------
// Settling an intercepted download — the ONLY two exits
// ---------------------------------------------------------------------------
// Downloads we've already handed off to UDM (so we don't double-handle them).
const interceptedDownloads = new Set();

/** UDM confirmed it has the download: remove Chrome's copy. */
function handedToUdm(downloadId) {
  interceptedDownloads.add(downloadId);
  chrome.downloads.cancel(downloadId);
  chrome.downloads.erase({ id: downloadId });
  releaseFilenameHold(downloadId);
}

/** UDM couldn't take it (or the user chose Cancel): let Chrome finish it. */
async function handedBackToChrome(downloadId) {
  await resumeNatively(downloadId); // UI is re-enabled first, then resume
  releaseFilenameHold(downloadId);
}

// ---------------------------------------------------------------------------
// Messages from the content script
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg.type === "trigger_download") {
      try {
        const cookieString = await collectCookies(msg.url);

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
          handedToUdm(msg.downloadId);
        } else if (msg.downloadId) {
          // UDM failed or is unreachable — let Chrome finish it natively
          // rather than losing the file.
          handedBackToChrome(msg.downloadId);
        }
      } catch (e) {
        console.error("Error triggering download:", e);
        if (msg.downloadId) handedBackToChrome(msg.downloadId);
      }
    } else if (msg.type === "cancel_download") {
      if (msg.downloadId) {
        handedBackToChrome(msg.downloadId);
      }
    } else if (msg.type === "trigger_video_download") {
      const cookieString = await collectCookies(msg.url);

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
      const cookieString = await collectCookies(msg.url);

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

// ---------------------------------------------------------------------------
// Automatic download interception
// ---------------------------------------------------------------------------
const EXTENSION_START_TIME = new Date(Date.now() - 5000); // 5 second buffer

/**
 * Show the in-page "UDM Download" dialog in a tab. If the content script
 * isn't there (tab opened before the extension was installed/reloaded),
 * inject it and try again. Resolves true if the dialog was shown.
 */
async function showDialogInTab(tabId, payload) {
  try {
    await chrome.tabs.sendMessage(tabId, payload);
    return true;
  } catch (e) {
    // No listener in that tab — fall through and inject.
  }

  try {
    await chrome.scripting.insertCSS({ target: { tabId }, files: ["content.css"] });
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    await chrome.tabs.sendMessage(tabId, payload);
    return true;
  } catch (e) {
    console.log("Could not show in-page dialog:", e && e.message);
    return false;
  }
}

// This is the single authoritative interception path.
chrome.downloads.onCreated.addListener(async (downloadItem) => {
  const id = downloadItem.id;

  const itemStartTime = new Date(downloadItem.startTime);
  if (itemStartTime < EXTENSION_START_TIME) {
    console.log("Ignoring old download from browser startup:", downloadItem.url);
    if (downloadItem.state === "in_progress") letChromeHandle(id);
    return;
  }

  if (
    downloadItem.state !== "in_progress" ||
    interceptedDownloads.has(id) ||
    downloadItem.url.startsWith("blob:") ||
    downloadItem.url.startsWith("data:")
  ) {
    if (downloadItem.state === "in_progress" && !interceptedDownloads.has(id)) {
      letChromeHandle(id);
    }
    return;
  }

  console.log("Caught download:", downloadItem.url);

  // Pause first thing, synchronously — as fast as the API allows — and open
  // the filename gate so Chrome doesn't pop a Save-As dialog while UDM is
  // deciding. Chrome's own bubble is already hidden (see applyNativeUi).
  chrome.downloads.pause(id);
  holdFilenameDetermination(id);

  const url = downloadItem.finalUrl || downloadItem.url;
  const filename = downloadItem.filename || extractFilename(url);

  try {
    if (await getAutoConfirm()) {
      // Skip the confirm dialog entirely — straight to UDM.
      const cookies = await collectCookies(url);
      const { success } = await sendToUDM({
        type: "download",
        url,
        filename,
        referrer: downloadItem.referrer || "",
        cookies,
        user_agent: navigator.userAgent,
        auto_start: true,
      });
      if (success) handedToUdm(id);
      else handedBackToChrome(id);
      return;
    }

    // Ask in the page. The dialog's buttons settle the download through
    // "trigger_download" / "cancel_download" above.
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const tabUrl = tab && tab.url ? tab.url : "";
    const pageOk = tab && tab.id != null && /^https?:/i.test(tabUrl);

    if (pageOk) {
      const shown = await showDialogInTab(tab.id, {
        type: "show_download_dialog",
        url,
        filename,
        downloadId: id,
      });
      if (shown) return;
    }

    // No page can host the dialog (chrome:// page, PDF viewer, new tab...):
    // let UDM's desktop app show its own Add Download dialog.
    const cookies = await collectCookies(url);
    const { success } = await sendToUDM({
      type: "download",
      url,
      filename,
      referrer: pageOk ? tabUrl : downloadItem.referrer || "",
      cookies,
      user_agent: navigator.userAgent,
      auto_start: false,
    });
    if (success) handedToUdm(id);
    else handedBackToChrome(id);
  } catch (e) {
    console.error("Interception failed:", e);
    handedBackToChrome(id);
  }
});

// ---------------------------------------------------------------------------
// Video Sniffer — flags likely video responses (non-YouTube included) so
// content.js can show the floating "Download this video" button.
// ---------------------------------------------------------------------------
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
