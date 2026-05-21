document.addEventListener('DOMContentLoaded', () => {
    // Load existing settings
    chrome.storage.local.get(['apiUrl', 'apiKey'], (result) => {
        if (result.apiUrl) document.getElementById('apiUrl').value = result.apiUrl;
        if (result.apiKey) document.getElementById('apiKey').value = result.apiKey;
    });

    // Save settings
    document.getElementById('saveBtn').addEventListener('click', () => {
        const apiUrl = document.getElementById('apiUrl').value.trim();
        const apiKey = document.getElementById('apiKey').value.trim();

        chrome.storage.local.set({ apiUrl, apiKey }, () => {
            const status = document.getElementById('status');
            status.textContent = 'Settings saved.';
            setTimeout(() => {
                status.textContent = '';
            }, 2000);
        });
    });
});