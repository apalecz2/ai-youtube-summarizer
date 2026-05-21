chrome.runtime.onInstalled.addListener(() => {
    chrome.contextMenus.create({
        id: "summarizeParent",
        title: "Summarize Video + Email",
        contexts: ["link"]
    });
    chrome.contextMenus.create({
        id: "summarize-depth-1",
        parentId: "summarizeParent",
        title: "1 - Concise",
        contexts: ["link"]
    });
    chrome.contextMenus.create({
        id: "summarize-depth-2",
        parentId: "summarizeParent",
        title: "2 - Standard",
        contexts: ["link"]
    });
    chrome.contextMenus.create({
        id: "summarize-depth-3",
        parentId: "summarizeParent",
        title: "3 - Deep Dive",
        contexts: ["link"]
    });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId.toString().startsWith("summarize-depth-")) {
        const detailStr = info.menuItemId.split("-").pop();
        const detail = parseInt(detailStr, 10) || 2;
        const linkUrl = info.linkUrl;
        if (linkUrl && linkUrl.includes("youtube.com")) {
            sendSummarizeRequest(linkUrl, detail, (result) => {
                if (result.success) {
                    console.log("Summarize request successful for", linkUrl);
                    // Could optionally inject a script to show a toast message here
                } else {
                    console.error("Summarize request failed for", linkUrl, result.error);
                }
            });
        }
    }
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'summarize') {
        sendSummarizeRequest(request.url, request.detail, sendResponse);
        return true; // Keep the message channel open for async response
    }
});

function sendSummarizeRequest(url, detail, callback) {
    chrome.storage.local.get(['apiUrl', 'apiKey'], async (settings) => {
        if (!settings.apiUrl || !settings.apiKey) {
            callback({ success: false, error: 'API URL or API Key not configured in extension options.' });
            return;
        }

        const endpoint = new URL('/summarize', settings.apiUrl).href;
        const formData = new URLSearchParams();
        formData.append('url', url);
        formData.append('detail', detail);

        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'x-api-key': settings.apiKey
                },
                body: formData.toString()
            });

            if (!response.ok) {
                const text = await response.text();
                callback({ success: false, error: `Server error ${response.status}: ${text}` });
                return;
            }

            const data = await response.json();
            callback({ success: true, data: data });
        } catch (error) {
            callback({ success: false, error: error.message });
        }
    });
}