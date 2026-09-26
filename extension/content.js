let floatingBtn = null;
let downloadDialog = null;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "show_video_button") {
        showFloatingButton(msg.url, msg.mediaType, msg.filename);
    } else if (msg.type === "show_download_dialog") {
        showDownloadDialog(msg.url, msg.filename, msg.downloadId);
        // Acknowledge receipt
        sendResponse({received: true});
    }
});

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
        // Send to background to download and skip the dialog box
        chrome.runtime.sendMessage({
            type: "trigger_download",
            url: url,
            filename: filename,
            auto_start: true 
        });
        
        // Hide button after click
        floatingBtn.style.display = "none";
        setTimeout(() => {
            if (floatingBtn && floatingBtn.parentNode) {
                floatingBtn.parentNode.removeChild(floatingBtn);
            }
            floatingBtn = null;
        }, 1000);
    });
}
