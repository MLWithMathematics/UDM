/**
 * UDM Extension - Popup Logic
 * Handles manual URL submission, pairing token storage, and status checking.
 */

const UDM_WS_URL = "ws://localhost:19615";

document.addEventListener("DOMContentLoaded", () => {
  const statusDot = document.getElementById("statusDot");
  const statusText = document.getElementById("statusText");
  const urlInput = document.getElementById("urlInput");
  const downloadBtn = document.getElementById("downloadBtn");
  const tokenInput = document.getElementById("tokenInput");
  const saveTokenBtn = document.getElementById("saveTokenBtn");
  const autoConfirmCheck = document.getElementById("autoConfirmCheck");
  const hideNativeUiCheck = document.getElementById("hideNativeUiCheck");

  chrome.storage.local.get(["udmToken", "udmAutoConfirm", "udmHideNativeUi"], (result) => {
    if (result.udmToken) tokenInput.value = result.udmToken;
    autoConfirmCheck.checked = !!result.udmAutoConfirm;
    hideNativeUiCheck.checked = result.udmHideNativeUi !== false;
    checkConnection();
  });

  hideNativeUiCheck.addEventListener("change", () => {
    chrome.storage.local.set({ udmHideNativeUi: hideNativeUiCheck.checked });
  });

  autoConfirmCheck.addEventListener("change", () => {
    chrome.storage.local.set({ udmAutoConfirm: autoConfirmCheck.checked });
  });

  saveTokenBtn.addEventListener("click", () => {
    const token = tokenInput.value.trim();
    chrome.storage.local.set({ udmToken: token }, () => {
      saveTokenBtn.textContent = "Saved ✓";
      setTimeout(() => (saveTokenBtn.textContent = "Save"), 1200);
      checkConnection();
    });
  });

  downloadBtn.addEventListener("click", () => {
    const url = urlInput.value.trim();
    if (!url) {
      urlInput.focus();
      return;
    }
    sendToUDM(url);
  });

  urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      downloadBtn.click();
    }
  });

  function getToken() {
    return new Promise((resolve) => {
      chrome.storage.local.get(["udmToken"], (result) => resolve(result.udmToken || ""));
    });
  }

  async function checkConnection() {
    const token = await getToken();
    try {
      const ws = new WebSocket(UDM_WS_URL);
      const timeout = setTimeout(() => {
        try { ws.close(); } catch (e) {}
      }, 3000);

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "ping", token }));
      };

      ws.onmessage = (event) => {
        clearTimeout(timeout);
        try {
          const response = JSON.parse(event.data);
          if (response.status === "ok") {
            statusDot.classList.remove("offline");
            statusText.textContent = "UDM is running ✓";
          } else {
            statusDot.classList.add("offline");
            statusText.textContent = response.message || "Token rejected ✗";
          }
        } catch (e) {
          statusDot.classList.add("offline");
          statusText.textContent = "Unexpected response ✗";
        }
        setTimeout(() => ws.close(), 300);
      };

      ws.onerror = () => {
        clearTimeout(timeout);
        statusDot.classList.add("offline");
        statusText.textContent = "UDM is not running ✗";
      };
    } catch {
      statusDot.classList.add("offline");
      statusText.textContent = "UDM is not running ✗";
    }
  }

  async function sendToUDM(url) {
    const token = await getToken();
    try {
      const ws = new WebSocket(UDM_WS_URL);

      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            type: "download",
            url: url,
            referrer: "",
            user_agent: navigator.userAgent,
            auto_start: true,
            token,
          })
        );
      };

      ws.onmessage = (event) => {
        let ok = false;
        let message = "";
        try {
          const response = JSON.parse(event.data);
          ok = response.status === "ok";
          message = response.message || "";
        } catch (e) {}

        downloadBtn.textContent = ok ? "✅  Sent!" : `❌  ${message || "Failed"}`;
        downloadBtn.style.background = ok
          ? "linear-gradient(135deg, #4caf50, #388e3c)"
          : "linear-gradient(135deg, #ef5350, #e53935)";

        setTimeout(() => {
          downloadBtn.textContent = "⬇️  Send to UDM";
          downloadBtn.style.background = "";
          if (ok) urlInput.value = "";
          ws.close();
        }, 2000);
      };

      ws.onerror = () => {
        downloadBtn.textContent = "❌  UDM not running";
        downloadBtn.style.background =
          "linear-gradient(135deg, #ef5350, #e53935)";

        setTimeout(() => {
          downloadBtn.textContent = "⬇️  Send to UDM";
          downloadBtn.style.background = "";
        }, 2000);
      };
    } catch (error) {
      console.error("Failed to send to UDM:", error);
    }
  }
});
