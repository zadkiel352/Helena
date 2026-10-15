let currentTabs = [];
let connectionInfo = {
    connected: false,
    port: null,
    error: null
};

function updateStatus(info) {
    const statusDiv = document.getElementById('status');
    const portDiv = document.getElementById('portInfo');
    const errorDiv = document.getElementById('errorInfo');
    
    if (info.connected) {
        statusDiv.textContent = '✅ Conectado a Helena';
        statusDiv.className = 'connected';
        portDiv.textContent = `Puerto: ${info.port}`;
        errorDiv.textContent = '';
    } else {
        statusDiv.textContent = '❌ Desconectado';
        statusDiv.className = 'disconnected';
        portDiv.textContent = `Puerto intentado: ${info.port}`;
        errorDiv.textContent = info.error ? `Error: ${info.error}` : '';
    }
}

function displayTabs(tabs) {
    const container = document.getElementById('tabList');
    if (!tabs.length) {
        container.innerHTML = '<p>No hay pestañas</p>';
        return;
    }
    
    container.innerHTML = `<strong>Total: ${tabs.length} pestañas</strong><br>`;
    tabs.forEach(tab => {
        const div = document.createElement('div');
        div.className = 'tab-item';
        div.innerHTML = `
            <strong>${tab.title.substring(0, 50)}</strong><br>
            <small>${tab.url ? tab.url.substring(0, 60) : 'sin URL'}</small>
        `;
        container.appendChild(div);
    });
}

chrome.runtime.onMessage.addListener(function(msg) {
    if (msg.type === 'tab_list') {
        currentTabs = msg.tabs;
        displayTabs(currentTabs);
        connectionInfo.connected = true;
        updateStatus(connectionInfo);
    } else if (msg.type === 'connection_status') {
        connectionInfo.connected = msg.connected;
        connectionInfo.port = msg.port;
        connectionInfo.error = msg.error;
        updateStatus(connectionInfo);
    }
});

document.getElementById('refreshBtn').onclick = () => {
    chrome.runtime.sendMessage({action: 'list_tabs'});
};