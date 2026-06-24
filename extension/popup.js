let currentUrl = '';
let channelPageUrl = '';

// Matches YouTube channel pages: /@handle, /channel/UC..., /c/name, /user/name.
// Excludes /watch and other non-channel paths.
function isYouTubeChannelPage(url) {
    return /youtube\.com\/(@[\w.-]+|channel\/UC[\w-]+|c\/[\w-]+|user\/[\w-]+)/.test(url);
}

document.addEventListener('DOMContentLoaded', () => {
    // Get the active tab's URL
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        const tabUrl = (tabs[0] && tabs[0].url) || '';

        if (tabUrl.includes('youtube.com/watch')) {
            currentUrl = tabUrl;
            document.getElementById('urlDisplay').textContent = currentUrl;
        } else {
            document.getElementById('urlDisplay').textContent = 'Not a YouTube video page.';
            document.getElementById('summarizeBtn').disabled = true;
        }

        // Show the "Add This Channel" button when on a YouTube channel page
        // (e.g. /@handle, /channel/UC..., /c/name, /user/name).
        if (isYouTubeChannelPage(tabUrl)) {
            channelPageUrl = tabUrl;
            document.getElementById('addChannelSection').style.display = 'block';
        }
    });

    document.getElementById('summarizeBtn').addEventListener('click', () => {
        const detailLevel = parseInt(document.getElementById('detailLevel').value, 10);
        const statusDiv = document.getElementById('status');
        
        statusDiv.textContent = 'Sending request...';
        statusDiv.style.color = '#333';
        document.getElementById('summarizeBtn').disabled = true;

        chrome.runtime.sendMessage({
            action: 'summarize',
            url: currentUrl,
            detail: detailLevel
        }, (response) => {
            document.getElementById('summarizeBtn').disabled = false;
            if (response && response.success) {
                statusDiv.textContent = 'Success: Processing started!';
                statusDiv.style.color = 'green';
            } else {
                statusDiv.textContent = 'Error: ' + (response ? response.error : 'Unknown error');
                statusDiv.style.color = 'red';
            }
        });
    });

    // Add This Channel button logic
    document.getElementById('addChannelBtn').addEventListener('click', () => {
        const btn = document.getElementById('addChannelBtn');
        const statusDiv = document.getElementById('addChannelStatus');

        statusDiv.textContent = 'Resolving channel...';
        statusDiv.style.color = '#333';
        btn.disabled = true;

        chrome.runtime.sendMessage({
            action: 'addChannelFromUrlOrId',
            urlOrId: channelPageUrl
        }, (response) => {
            if (response && response.success) {
                statusDiv.textContent = 'Channel added!';
                statusDiv.style.color = 'green';
            } else {
                btn.disabled = false;
                statusDiv.textContent = 'Error: ' + (response ? response.error : 'Unknown error');
                statusDiv.style.color = 'red';
            }
        });
    });

    // Add Manage Channels button logic
    document.getElementById('channelsBtn').addEventListener('click', () => {
        chrome.tabs.create({ url: chrome.runtime.getURL('channels.html') });
    });
});