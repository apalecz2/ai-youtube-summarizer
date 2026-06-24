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
    chrome.contextMenus.create({
        id: "addChannelMenu",
        title: "Add Channel to Summarizer",
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
                } else {
                    console.error("Summarize request failed for", linkUrl, result.error);
                }
            });
        }
    } else if (info.menuItemId === "addChannelMenu") {
        const linkUrl = info.linkUrl;
        if (linkUrl && linkUrl.includes("youtube.com")) {
            resolveChannelId(linkUrl).then(channelId => {
                if (channelId) {
                    apiCall('/channels', 'POST', { channel_id: channelId }).then(result => {
                        if (result.success) console.log("Successfully added channel", channelId);
                        else console.error("Failed to add channel", channelId, result.error);
                    });
                } else {
                    console.error("Could not resolve tracking ID for channel link:", linkUrl);
                }
            });
        }
    }
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'summarize') {
        sendSummarizeRequest(request.url, request.detail, sendResponse);
        return true;
    } else if (request.action === 'getChannels') {
        apiCall('/channels', 'GET', null).then(sendResponse);
        return true;
    } else if (request.action === 'removeChannel') {
        apiCall(`/channels/${request.channelId}`, 'DELETE', null).then(sendResponse);
        return true;
    } else if (request.action === 'addChannelFromUrlOrId') {
        resolveChannelId(request.urlOrId).then(channelId => {
            if (channelId) {
                apiCall('/channels', 'POST', { channel_id: channelId }).then(sendResponse);
            } else {
                sendResponse({ success: false, error: "Could not resolve a valid YouTube Channel ID from the input."});
            }
        });
        return true;
    } else if (request.action === 'getFilters') {
        apiCall(`/channels/${request.channelId}/filters`, 'GET', null).then(sendResponse);
        return true;
    } else if (request.action === 'addFilter') {
        apiCall(`/channels/${request.channelId}/filters`, 'POST', {
            value: request.value,
            field: request.field || 'title',
            match_type: request.matchType || 'contains',
            action: request.filterAction || 'include',
        }).then(sendResponse);
        return true;
    } else if (request.action === 'removeFilter') {
        apiCall(`/channels/filters/${request.filterId}`, 'DELETE', null).then(sendResponse);
        return true;
    }
});

async function resolveChannelId(input) {
    if (input.startsWith('UC') && input.length >= 20) {
        return input; // It's already an ID
    }
    
    // Explicit channel ID match in URL
    const match = input.match(/\/channel\/(UC[\w-]+)/);
    if (match) return match[1];

    // Otherwise, we fetch the page to extract it (works for /@handles and custom urls)
    try {
        let fetchUrl = input;
        if (!input.includes('youtube.com')) {
            // They just typed a handle e.g. "@username"
            if (input.startsWith('@')) fetchUrl = `https://www.youtube.com/${input}`;
            else return null; 
        }

        const res = await fetch(fetchUrl);
        const text = await res.text();
        
        // Strategy 1: Look for og:url
        const ogUrlMatch = text.match(/<meta property="og:url" content="https:\/\/www\.youtube\.com\/channel\/(UC[\w-]+)">/);
        if (ogUrlMatch) return ogUrlMatch[1];
        
        // Strategy 2: Look for itemprop channelId or identifier
        const itemPropMatch = text.match(/<meta itemprop="channelId" content="(UC[\w-]+)">/);
        if (itemPropMatch) return itemPropMatch[2] || itemPropMatch[1];
        
        const identifierMatch = text.match(/<meta itemprop="identifier" content="(UC[\w-]+)">/);
        if (identifierMatch) return identifierMatch[2] || identifierMatch[1];
    } catch (e) {
        console.error("Error resolving channel ID", e);
    }
    return null;
}

// Generic API call wrapper to reuse logic
async function apiCall(path, method, formDataObj) {
    return new Promise((resolve) => {
        chrome.storage.local.get(['apiUrl', 'apiKey'], async (settings) => {
            if (!settings.apiUrl || !settings.apiKey) {
                resolve({ success: false, error: 'API URL or API Key not configured.' });
                return;
            }

            const endpoint = new URL(path, settings.apiUrl).href;
            const options = {
                method: method,
                headers: {
                    'x-api-key': settings.apiKey
                }
            };

            if (formDataObj) {
                const formData = new URLSearchParams();
                for (const key in formDataObj) formData.append(key, formDataObj[key]);
                options.headers['Content-Type'] = 'application/x-www-form-urlencoded';
                options.body = formData.toString();
            }

            try {
                const response = await fetch(endpoint, options);
                if (!response.ok) {
                    const text = await response.text();
                    resolve({ success: false, error: `Server error ${response.status}: ${text}` });
                    return;
                }
                const data = await response.json();
                resolve({ success: true, data: data });
            } catch (error) {
                resolve({ success: false, error: error.message });
            }
        });
    });
}

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