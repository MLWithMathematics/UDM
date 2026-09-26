/**
 * UDM Extension - Popup Logic
 * Handles manual URL submission and status checking.
 */

const UDM_WS_URL = "ws://localhost:19615";

document.addEventListener("DOMContentLoaded", () => {
  const statusDot = document.getElementById("statusDot");
  const statusText = document.getElementById("statusText");
  const urlInput = document.getElementById("urlInput");
  const downloadBtn = document.getElementById("downloadBtn");

  // Check if UDM is running
  checkConnection();

  // Handle download button
  downloadBtn.addEventListener("click", () => {
    const url = urlInput.value.trim();
    if (!url) {
      urlInput.focus();
      return;
    }

    sendToUDM(url);
  });

  // Handle Enter key in input
  urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      downloadBtn.click();
    }
  });

  function checkConnection() {
    try {
      const ws = new WebSocket(UDM_WS_URL);

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "ping" }));

        statusDot.classList.remove("offline");
        statusText.textContent = "UDM is running ✓";

        setTimeout(() => ws.close(), 500);
      };

      ws.onerror = () => {
        statusDot.classList.add("offline");
        statusText.textContent = "UDM is not running ✗";
      };
    } catch {
      statusDot.classList.add("offline");
      statusText.textContent = "UDM is not running ✗";
    }
  }

  function sendToUDM(url) {
    try {
      const ws = new WebSocket(UDM_WS_URL);

      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            type: "download",
            url: url,
            referrer: "",
            user_agent: navigator.userAgent,
          })
        );

        downloadBtn.textContent = "✅  Sent!";
        downloadBtn.style.background =
          "linear-gradient(135deg, #4caf50, #388e3c)";

        setTimeout(() => {
          downloadBtn.textContent = "⬇️  Send to UDM";
          downloadBtn.style.background = "";
          urlInput.value = "";
          ws.close();
        }, 1500);
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
