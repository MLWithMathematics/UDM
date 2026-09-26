/**
 * UDM Browser Extension - Background Service Worker
 * 
 * Adds a right-click context menu item "Download with UDM"
 * and sends the URL to the UDM desktop app via WebSocket.
 */

const UDM_WS_URL = "ws://localhost:19615";

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
chrome.contextMenus.onClicked.addListener((info, tab) => {
  let url = "";
  let referrer = "";

  if (info.menuItemId === "udm-download-link") {
    url = info.linkUrl;
    referrer = info.pageUrl || "";
  } else if (info.menuItemId === "udm-download-page") {
    url = info.pageUrl;
  }

  if (url) {
    sendToUDM({
      type: "download",
      url: url,
      referrer: referrer,
      filename: extractFilename(url),
      user_agent: navigator.userAgent,
    });
  }
});

/**
 * Send download request to UDM via WebSocket.
 * Returns a Promise that resolves to true if successful, false otherwise.
 */
function sendToUDM(data) {
  return new Promise((resolve) => {
    try {
      const ws = new WebSocket(UDM_WS_URL);
      let resolved = false;

      const timeout = setTimeout(() => {
        if (!resolved) {
          resolved = true;
          ws.close();
          resolve(false);
        }
      }, 1000); // 1-second timeout

      ws.onopen = () => {
        ws.send(JSON.stringify(data));
        console.log("Sent to UDM:", data.url);
      };

      ws.onmessage = (event) => {
        try {
          const response = JSON.parse(event.data);
          console.log("UDM response:", response);
          if (response.status === "ok" && !resolved) {
            resolved = true;
            clearTimeout(timeout);
            ws.close();
            resolve(true);
          }
        } catch (e) {}
      };

      ws.onerror = (error) => {
        console.error("UDM connection failed.", error);
        chrome.action.setBadgeText({ text: "!" });
        chrome.action.setBadgeBackgroundColor({ color: "#ef5350" });
        setTimeout(() => chrome.action.setBadgeText({ text: "" }), 3000);
        
        if (!resolved) {
          resolved = true;
          clearTimeout(timeout);
          resolve(false);
        }
      };
    } catch (error) {
      console.error("Failed to connect to UDM:", error);
      resolve(false);
    }
  });
}

/**
 * Extract filename from URL.
 */
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

// Keep track of download IDs we are already intercepting
const interceptedDownloads = new Set();

// Handle messages from content script
chrome.runtime.onMessage.addListener(async (msg, sender, sendResponse) => {
    if (msg.type === "trigger_download") {
        try {
            // Try to extract cookies for the domain
            let cookieString = "";
            try {
                const urlObj = new URL(msg.url);
                const cookies = await chrome.cookies.getAll({ domain: urlObj.hostname });
                cookieString = cookies.map(c => `${c.name}=${c.value}`).join('; ');
            } catch (e) {
                console.log("Could not get cookies:", e);
            }

            const payload = {
                type: "download",
                url: msg.url,
                filename: msg.filename,
                referrer: msg.referrer || (sender.tab ? sender.tab.url : ""),
                cookies: cookieString,
                user_agent: navigator.userAgent,
                auto_start: msg.auto_start
            };

            const success = await sendToUDM(payload);
            
            if (success && msg.downloadId) {
                interceptedDownloads.add(msg.downloadId);
                chrome.downloads.cancel(msg.downloadId);
                chrome.downloads.erase({id: msg.downloadId});
            } else if (msg.downloadId) {
                chrome.downloads.resume(msg.downloadId);
            }
        } catch (e) {
            console.error("Error triggering download:", e);
        }
    } else if (msg.type === "cancel_download") {
        if (msg.downloadId) {
            chrome.downloads.resume(msg.downloadId);
        }
    }
});

// Intercept right before the browser shows the Save As dialog
chrome.downloads.onDeterminingFilename.addListener((downloadItem, suggest) => {
    // If we're intercepting it, cancel it immediately so Chrome never shows its dialog!
    if (!downloadItem.url.startsWith("blob:") && !downloadItem.url.startsWith("data:")) {
        chrome.downloads.cancel(downloadItem.id);
        chrome.downloads.erase({id: downloadItem.id});
    }
    suggest(); // Must call suggest
});

// Automatically intercept file downloads
chrome.downloads.onCreated.addListener(async (downloadItem) => {
  // Ignore downloads we are already handling, or internal blobs/data uris
  if (interceptedDownloads.has(downloadItem.id) || 
      downloadItem.url.startsWith("blob:") || 
      downloadItem.url.startsWith("data:")) {
    return;
  }

  console.log("Caught download:", downloadItem.url);
  
  // Pause the browser's download immediately
  chrome.downloads.pause(downloadItem.id);

  // Send message to the active tab to show the custom floating popup
  chrome.tabs.query({active: true, currentWindow: true}, async function(tabs) {
      if (tabs.length > 0 && tabs[0].url && !tabs[0].url.startsWith("chrome://")) {
          chrome.tabs.sendMessage(tabs[0].id, {
              type: "show_download_dialog",
              url: downloadItem.finalUrl || downloadItem.url,
              filename: downloadItem.filename || extractFilename(downloadItem.finalUrl || downloadItem.url),
              downloadId: downloadItem.id
          }, async (response) => {
              if (chrome.runtime.lastError) {
                  // Content script not loaded
                  console.log("Content script not found, falling back to UDM native dialog.");
                  const success = await sendToUDM({
                      type: "download",
                      url: downloadItem.finalUrl || downloadItem.url,
                      filename: downloadItem.filename || extractFilename(downloadItem.finalUrl || downloadItem.url),
                      referrer: tabs[0].url,
                      cookies: "",
                      user_agent: navigator.userAgent,
                      auto_start: false // Use native dialog
                  });
              }
          });
      } else {
          // No valid active tab, fallback to native UDM dialog
          const success = await sendToUDM({
              type: "download",
              url: downloadItem.finalUrl || downloadItem.url,
              filename: downloadItem.filename || extractFilename(downloadItem.finalUrl || downloadItem.url),
              referrer: "",
              cookies: "",
              user_agent: navigator.userAgent,
              auto_start: false // Use native dialog
          });
      }
  });
});
