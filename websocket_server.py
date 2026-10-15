# websocket_server.py - Servidor WebSocket independiente para la extensión del navegador
import asyncio
import json
import threading
import websockets
import time

# Variables globales
connected_websockets = set()
current_tabs = []
current_browser = ""
_event_loop = None

async def websocket_handler(websocket):
    """Maneja mensajes de la extensión del navegador"""
    global current_tabs, current_browser
    connected_websockets.add(websocket)
    print("[BrowserBridge] extension connected")

    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get('type', '')

            if msg_type == 'tab_list':
                current_tabs = data.get('tabs', [])
                current_browser = data.get('browser', '') or (current_tabs[0].get('browser', '') if current_tabs else '')
                print(f"[BrowserBridge] tabs received: {len(current_tabs)}")
                for i, tab in enumerate(current_tabs[:3]):
                    titulo = tab.get('title', 'Sin título')[:50]
                    activa = " ✓" if tab.get('active') else ""
                    print(f"  {i+1}. {titulo}{activa}")
                if len(current_tabs) > 3:
                    print(f"  ... y {len(current_tabs) - 3} más")

            elif msg_type == 'hello':
                print("[BrowserBridge] hello received from extension")
                await websocket.send(json.dumps({'type': 'hello_ack'}))

            elif msg_type == 'ping':
                await websocket.send(json.dumps({'type': 'pong'}))

            elif msg_type == 'browser_status':
                print(f"[BrowserBridge] browser status: {data}")

            elif msg_type == 'tabs_update':
                current_tabs = data.get('tabs', [])
                print(f"[BrowserBridge] tabs updated: {len(current_tabs)}")

            elif msg_type == 'active_tab':
                print(f"[BrowserBridge] active tab: {data}")

            elif msg_type == 'pong':
                print("[BrowserBridge] pong received")

            else:
                print(f"[BrowserBridge] unknown message type: {msg_type}")

    except Exception as e:
        print(f"[BrowserBridge] error: {e}")
    finally:
        connected_websockets.discard(websocket)
        print("[BrowserBridge] extension disconnected")

async def start_websocket_server():
    """Inicia el servidor WebSocket en el puerto 8766"""
    async with websockets.serve(websocket_handler, "localhost", 8766):
        print("[WebSocket] 🚀 Servidor iniciado en ws://localhost:8766")
        await asyncio.Future()

def iniciar_servidor_websocket():
    """Inicia el servidor WebSocket en un hilo separado"""
    global _event_loop
    _event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_event_loop)
    _event_loop.run_until_complete(start_websocket_server())

def enviar_comando_a_navegador_sync(accion, **kwargs):
    """Envía un comando a la extensión (versión síncrona)"""
    global _event_loop, connected_websockets

    if not connected_websockets:
        print("[WebSocket] ⚠️ No hay extensión conectada")
        return False

    if not _event_loop:
        print("[WebSocket] ❌ No hay event loop")
        return False

    comando = {"action": accion, **kwargs}
    comando_json = json.dumps(comando)

    for ws in list(connected_websockets):
        try:
            asyncio.run_coroutine_threadsafe(ws.send(comando_json), _event_loop)
            print(f"[WebSocket] 📤 Enviado: {accion}")
        except Exception as e:
            print(f"[WebSocket] ❌ Error enviando: {e}")

    return True

def listar_pestanias():
    """Obtiene lista de pestañas del navegador"""
    global current_tabs
    return current_tabs

def navegador_conectado():
    """Devuelve el navegador que reporto la extension, si esta disponible."""
    global current_browser
    return current_browser

def cerrar_pestania_por_titulo(titulo):
    """Cierra pestaña que contiene el texto en el título"""
    print(f"[WebSocket] 🎯 Cerrando pestaña con: {titulo}")
    return enviar_comando_a_navegador_sync('close_tab_by_title', title=titulo)

def cambiar_a_pestania_por_titulo(titulo):
    """Cambia a la pestaña que contiene el texto en el título"""
    print(f"[WebSocket] 🎯 Cambiando a pestaña con: {titulo}")
    return enviar_comando_a_navegador_sync('switch_to_tab_by_title', title=titulo)
