let currentUrl = '';

document.addEventListener('DOMContentLoaded', () => {
    // Get the active tab's URL
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (tabs[0] && tabs[0].url && tabs[0].url.includes('youtube.com/watch')) {
            currentUrl = tabs[0].url;
            document.getElementById('urlDisplay').textContent = currentUrl;
        } else {
            document.getElementById('urlDisplay').textContent = 'Not a YouTube video page.';
            document.getElementById('summarizeBtn').disabled = true;
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
});