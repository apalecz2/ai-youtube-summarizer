document.addEventListener('DOMContentLoaded', () => {
    loadChannels();

    document.getElementById('addBtn').addEventListener('click', async () => {
        const inputVal = document.getElementById('newChannelId').value.trim();
        if (inputVal) {
            document.getElementById('addBtn').disabled = true;
            showStatus('Resolving channel...', false);
            
            // Send to background to resolve and add
            chrome.runtime.sendMessage({ action: 'addChannelFromUrlOrId', urlOrId: inputVal }, (response) => {
                document.getElementById('addBtn').disabled = false;
                if (response && response.success) {
                    document.getElementById('newChannelId').value = '';
                    showStatus('Channel added successfully!');
                    loadChannels();
                } else {
                    showStatus('Failed to add channel: ' + (response ? response.error : 'Unknown'), true);
                }
            });
        }
    });
});

function showStatus(message, isError = false) {
    const statusDiv = document.getElementById('status');
    statusDiv.textContent = message;
    statusDiv.style.color = isError ? 'red' : 'green';
    
    // Only clear success messages automatically
    if (!isError) {
        setTimeout(() => { 
            if (statusDiv.textContent === message) statusDiv.textContent = ''; 
        }, 3000);
    }
}

function loadChannels() {
    chrome.runtime.sendMessage({ action: 'getChannels' }, async (response) => {
        if (response && response.success) {
            const list = document.getElementById('channelList');
            list.innerHTML = '';
            
            if (!response.data || !response.data.channels || response.data.channels.length === 0) {
                list.innerHTML = '<li class="channel-item">No channels added yet.</li>';
                return;
            }

            for (const channelId of response.data.channels) {
                const li = document.createElement('li');
                li.className = 'channel-item';
                
                const nameSpan = document.createElement('span');
                nameSpan.className = 'channel-name';
                nameSpan.textContent = "Loading...";
                
                const idSpan = document.createElement('span');
                idSpan.className = 'channel-id';
                idSpan.textContent = channelId;

                const infoDiv = document.createElement('div');
                infoDiv.className = 'channel-info';
                infoDiv.appendChild(nameSpan);
                infoDiv.appendChild(idSpan);

                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'delete-btn';
                deleteBtn.textContent = 'Remove';
                deleteBtn.onclick = () => removeChannel(channelId);

                li.appendChild(infoDiv);
                li.appendChild(deleteBtn);
                list.appendChild(li);

                // Fetch the name asynchronously
                fetchChannelName(channelId).then(name => {
                    nameSpan.textContent = name;
                }).catch(err => {
                    nameSpan.textContent = "Unknown Channel";
                });
            }
        } else {
            showStatus('Failed to load channels: ' + (response ? response.error : 'Unknown error'), true);
        }
    });
}

async function fetchChannelName(channelId) {
    try {
        const response = await fetch(`https://www.youtube.com/channel/${channelId}`);
        const text = await response.text();
        const match = text.match(/<title>(.*?) - YouTube<\/title>/);
        if (match && match[1]) {
            return match[1];
        }
        return "Unknown Channel";
    } catch (e) {
        return "Unknown Channel";
    }
}

function removeChannel(channelId) {
    if (confirm(`Are you sure you want to remove channel ${channelId}?`)) {
        chrome.runtime.sendMessage({ action: 'removeChannel', channelId: channelId }, (response) => {
            if (response && response.success) {
                showStatus('Channel removed successfully!');
                loadChannels();
            } else {
                showStatus('Failed to remove channel: ' + (response ? response.error : 'Unknown'), true);
            }
        });
    }
}