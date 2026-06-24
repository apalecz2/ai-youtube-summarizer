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

                const row = document.createElement('div');
                row.className = 'channel-row';

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

                const buttonsDiv = document.createElement('div');
                buttonsDiv.className = 'channel-buttons';

                const filtersPanel = document.createElement('div');
                filtersPanel.className = 'filters-panel hidden';

                const filtersBtn = document.createElement('button');
                filtersBtn.className = 'filters-btn';
                filtersBtn.textContent = 'Filters';
                filtersBtn.onclick = () => toggleFilters(channelId, filtersPanel, filtersBtn);

                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'delete-btn';
                deleteBtn.textContent = 'Remove';
                deleteBtn.onclick = () => removeChannel(channelId);

                buttonsDiv.appendChild(filtersBtn);
                buttonsDiv.appendChild(deleteBtn);

                row.appendChild(infoDiv);
                row.appendChild(buttonsDiv);

                li.appendChild(row);
                li.appendChild(filtersPanel);
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

function toggleFilters(channelId, panel, btn) {
    if (!panel.classList.contains('hidden')) {
        panel.classList.add('hidden');
        btn.textContent = 'Filters';
        return;
    }
    btn.textContent = 'Hide';
    panel.classList.remove('hidden');
    renderFilterPanel(channelId, panel);
}

function renderFilterPanel(channelId, panel) {
    panel.innerHTML = '<p class="filters-hint">Loading filters...</p>';

    chrome.runtime.sendMessage({ action: 'getFilters', channelId }, (response) => {
        panel.innerHTML = '';

        const hint = document.createElement('p');
        hint.className = 'filters-hint';
        hint.textContent = 'With no rules, every video is summarized. Add an "include" rule and only matching videos are sent; "exclude" rules drop matching videos.';
        panel.appendChild(hint);

        const rules = (response && response.success && response.data && response.data.filters) || [];

        const list = document.createElement('ul');
        list.className = 'filter-list';
        if (rules.length === 0) {
            const empty = document.createElement('li');
            empty.style.fontSize = '13px';
            empty.style.color = '#666';
            empty.textContent = 'No filters — all videos pass.';
            list.appendChild(empty);
        } else {
            for (const rule of rules) {
                const item = document.createElement('li');
                item.className = 'filter-rule';

                const label = document.createElement('span');
                const tag = document.createElement('span');
                tag.className = 'tag ' + rule.action;
                tag.textContent = rule.action;
                label.appendChild(tag);
                label.appendChild(document.createTextNode(`${rule.field} ${rule.match_type} "${rule.value}"`));

                const removeBtn = document.createElement('button');
                removeBtn.className = 'filter-remove';
                removeBtn.textContent = '×';
                removeBtn.title = 'Remove rule';
                removeBtn.onclick = () => removeFilter(rule.id, channelId, panel);

                item.appendChild(label);
                item.appendChild(removeBtn);
                list.appendChild(item);
            }
        }
        panel.appendChild(list);

        // Add-rule form
        const form = document.createElement('div');
        form.className = 'add-filter';

        const actionSelect = document.createElement('select');
        for (const opt of ['include', 'exclude']) {
            const o = document.createElement('option');
            o.value = opt;
            o.textContent = opt;
            actionSelect.appendChild(o);
        }

        const valueInput = document.createElement('input');
        valueInput.type = 'text';
        valueInput.placeholder = 'word or phrase in title';

        const addBtn = document.createElement('button');
        addBtn.textContent = 'Add';
        const submit = () => {
            const value = valueInput.value.trim();
            if (!value) return;
            addBtn.disabled = true;
            chrome.runtime.sendMessage({
                action: 'addFilter',
                channelId,
                value,
                field: 'title',
                matchType: 'contains',
                filterAction: actionSelect.value,
            }, (resp) => {
                addBtn.disabled = false;
                if (resp && resp.success) {
                    valueInput.value = '';
                    renderFilterPanel(channelId, panel);
                } else {
                    showStatus('Failed to add filter: ' + (resp ? resp.error : 'Unknown'), true);
                }
            });
        };
        addBtn.onclick = submit;
        valueInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });

        form.appendChild(actionSelect);
        form.appendChild(valueInput);
        form.appendChild(addBtn);
        panel.appendChild(form);
    });
}

function removeFilter(filterId, channelId, panel) {
    chrome.runtime.sendMessage({ action: 'removeFilter', filterId }, (response) => {
        if (response && response.success) {
            renderFilterPanel(channelId, panel);
        } else {
            showStatus('Failed to remove filter: ' + (response ? response.error : 'Unknown'), true);
        }
    });
}