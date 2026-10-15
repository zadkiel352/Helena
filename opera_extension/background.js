// background.js - Extensión para controlar navegadores Chromium desde Helena
let socket = null;
let isConnected = false;
let reconnectTimeout = null;
let currentPort = 8766;
let lastError = null;
let reconnectAttempts = 0;
let maxReconnectDelay = 10000;

const PORTS_TO_TRY = [8766, 8765];
const HOSTS_TO_TRY = ['localhost', '127.0.0.1'];

function getReconnectDelay() {
    const delay = Math.min(2000 * (reconnectAttempts + 1), maxReconnectDelay);
    return delay;
}

function notifyPopup(message) {
    chrome.runtime.sendMessage(message).catch(() => {});
}

function connectToHelena() {
    if (socket && (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN)) {
        return;
    }

    const portIndex = reconnectAttempts % PORTS_TO_TRY.length;
    const hostIndex = Math.floor(reconnectAttempts / PORTS_TO_TRY.length) % HOSTS_TO_TRY.length;
    currentPort = PORTS_TO_TRY[portIndex];
    const host = HOSTS_TO_TRY[hostIndex];
    const wsUrl = `ws://${host}:${currentPort}`;

    try {
        console.log(`[Helena] 🔌 Intentando conectar a ${wsUrl} (intento ${reconnectAttempts + 1})`);
        socket = new WebSocket(wsUrl);

        socket.onopen = function() {
            console.log(`[Helena] ✅ Conectada a Helena en ${wsUrl}`);
            isConnected = true;
            lastError = null;
            reconnectAttempts = 0;
            if (reconnectTimeout) {
                clearTimeout(reconnectTimeout);
                reconnectTimeout = null;
            }
            sendTabListToHelena();
            notifyPopup({type: 'connection_status', connected: true, port: currentPort, error: null});
        };

        socket.onmessage = function(event) {
            console.log('[Helena] 📩 Recibido:', event.data);
            handleHelenaCommand(event.data);
        };

        socket.onerror = function(error) {
            const errorMsg = `Error conectando a ${wsUrl}`;
            console.error('[Helena] ❌', errorMsg, error);
            lastError = errorMsg;
        };

        socket.onclose = function(event) {
            console.log(`[Helena] 🔌 Desconectada de ${wsUrl} (code: ${event.code})`);
            isConnected = false;
            notifyPopup({type: 'connection_status', connected: false, port: currentPort, error: lastError || 'Desconectado'});

            if (!reconnectTimeout) {
                const delay = getReconnectDelay();
                console.log(`[Helena] 🔄 Reintentando en ${delay}ms...`);
                reconnectTimeout = setTimeout(() => {
                    reconnectAttempts++;
                    connectToHelena();
                }, delay);
            }
        };
    } catch(e) {
        console.error('[Helena] Error conectando:', e);
        lastError = e.message;
        reconnectAttempts++;
    }
}

function sendTabListToHelena() {
    if (!isConnected) return;
    
    chrome.tabs.query({}, function(tabs) {
        const ua = navigator.userAgent || '';
        const browserName = ua.includes('Edg/') ? 'edge' : (ua.includes('OPR/') ? 'opera' : 'chromium');
        const tabList = tabs.map(tab => ({
            id: tab.id,
            title: tab.title,
            url: tab.url,
            active: tab.active,
            browser: browserName
        }));
        
        socket.send(JSON.stringify({
            type: 'tab_list',
            tabs: tabList,
            browser: browserName,
            count: tabs.length
        }));
    });
}

function handleHelenaCommand(commandStr) {
    console.log('[Helena] Comando recibido:', commandStr);
    try {
        const command = JSON.parse(commandStr);
        
        switch(command.action) {
            case 'list_tabs':
                sendTabListToHelena();
                break;
                
            case 'close_tab_by_title':
                console.log('[Helena] Cerrando pestaña con título que contenga:', command.title);
                closeTabByTitle(command.title);
                break;
                
            case 'switch_to_tab_by_title':
                console.log('[Helena] Cambiando a pestaña con título que contenga:', command.title);
                switchToTabByTitle(command.title);
                break;
                
            case 'new_tab':
                console.log('[Helena] Abriendo nueva pestaña');
                chrome.tabs.create({url: command.url || 'about:blank'});
                setTimeout(() => sendTabListToHelena(), 100);
                break;
                
            case 'ping':
                // Responder al ping para mantener la conexión
                if (socket && isConnected) {
                    socket.send(JSON.stringify({type: 'pong'}));
                }
                break;
                
            default:
                console.log('[Helena] Comando no reconocido:', command.action);
        }
    } catch(e) {
        console.error('[Helena] Error procesando comando:', e);
    }
}

function closeTabByTitle(titleText) {
    chrome.tabs.query({}, function(tabs) {
        const targetTab = tabs.find(tab => 
            tab.title && tab.title.toLowerCase().includes(titleText.toLowerCase())
        );
        
        if (targetTab) {
            chrome.tabs.remove(targetTab.id);
            console.log('[Helena] ✅ Cerrada pestaña:', targetTab.title);
            setTimeout(() => sendTabListToHelena(), 100);
        } else {
            console.log('[Helena] ❌ No se encontró pestaña con:', titleText);
        }
    });
}

function switchToTabByTitle(titleText) {
    chrome.tabs.query({}, function(tabs) {
        const targetTab = tabs.find(tab => 
            tab.title && tab.title.toLowerCase().includes(titleText.toLowerCase())
        );
        
        if (targetTab) {
            chrome.tabs.update(targetTab.id, {active: true});
            console.log('[Helena] ✅ Cambiado a pestaña:', targetTab.title);
            setTimeout(() => sendTabListToHelena(), 100);
        } else {
            console.log('[Helena] ❌ No se encontró pestaña con:', titleText);
        }
    });
}

// Mantener conexión activa con ping cada 25 segundos
function keepAlive() {
    if (socket && isConnected) {
        socket.send(JSON.stringify({type: 'ping'}));
        console.log('[Helena] 💓 Ping enviado');
    }
    setTimeout(keepAlive, 25000);
}

// Escuchar cambios en pestañas
chrome.tabs.onCreated.addListener(() => setTimeout(() => sendTabListToHelena(), 500));
chrome.tabs.onRemoved.addListener(() => setTimeout(() => sendTabListToHelena(), 500));
chrome.tabs.onUpdated.addListener(() => setTimeout(() => sendTabListToHelena(), 500));
chrome.tabs.onActivated.addListener(() => setTimeout(() => sendTabListToHelena(), 500));

// Iniciar conexión
connectToHelena();
keepAlive();
