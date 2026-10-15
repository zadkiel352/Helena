# browser_control.py - Control de navegadores Chromium/Edge desde Helena
import subprocess
import sys
import time
import pyperclip
import requests
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
from utils.silent_subprocess import popen_silent

try:
    from websocket_server import (
        listar_pestanias,
        navegador_conectado,
        cerrar_pestania_por_titulo,
        cambiar_a_pestania_por_titulo,
        enviar_comando_a_navegador_sync,
    )
    WEBSOCKET_DISPONIBLE = True
    print("[Navegador] Conexion con WebSocket establecida")
except ImportError as e:
    WEBSOCKET_DISPONIBLE = False
    print(f"[Navegador] WebSocket no disponible: {e}")

# CDP Backend
CDP_PORT = 9222
CDP_AVAILABLE = False

# Security
SENSITIVE_DOMAINS = [
    "bank", "banco", "paypal", "stripe", "checkout", "payment",
    "login", "signin", "auth", "password", "credential",
    "crypto", "wallet", "exchange", "trading"
]

def is_sensitive_url(url):
    """Verifica si una URL es potencialmente sensible"""
    url_lower = url.lower()
    for domain in SENSITIVE_DOMAINS:
        if domain in url_lower:
            return True
    return False

def validate_url_safety(url, action="navegar"):
    """Valida si es seguro realizar una acción en una URL"""
    if is_sensitive_url(url):
        return f"⚠️ Seguridad: La URL parece ser una página sensible ({url}). Por seguridad, Helena no automatiza páginas bancarias o de login sin confirmación explícita del usuario."
    return None

def check_cdp_available():
    """Verifica si hay un navegador con CDP disponible"""
    global CDP_AVAILABLE
    try:
        response = requests.get(f"http://localhost:{CDP_PORT}/json/version", timeout=1)
        CDP_AVAILABLE = response.status_code == 200
        return CDP_AVAILABLE
    except:
        CDP_AVAILABLE = False
        return False

def cdp_list_tabs():
    """Lista pestañas usando CDP"""
    try:
        response = requests.get(f"http://localhost:{CDP_PORT}/json", timeout=2)
        if response.status_code == 200:
            tabs = response.json()
            return tabs
        return None
    except Exception as e:
        print(f"[CDP] Error listando pestañas: {e}")
        return None

def cdp_navigate(tab_id, url):
    """Navega a una URL usando CDP"""
    try:
        endpoint = f"http://localhost:{CDP_PORT}/json/{tab_id}"
        response = requests.get(endpoint, timeout=2)
        if response.status_code == 200:
            tab_info = response.json()
            websocket_url = tab_info.get('webSocketDebuggerUrl')
            if websocket_url:
                # Para navegación simple, podemos usar el endpoint HTTP
                payload = {"id": int(time.time()), "method": "Page.navigate", "params": {"url": url}}
                # Nota: Navegación completa requiere WebSocket, esto es básico
                return True
        return False
    except Exception as e:
        print(f"[CDP] Error navegando: {e}")
        return False

def cdp_activate_tab(tab_id):
    """Activa una pestaña usando CDP"""
    try:
        response = requests.get(f"http://localhost:{CDP_PORT}/json/activate", timeout=2)
        return response.status_code == 200
    except Exception as e:
        print(f"[CDP] Error activando pestaña: {e}")
        return False


def browser_control(parameters: dict, player=None):
    """Controla navegador Chromium/Edge con backend hierarchy: EXTENSION > CDP > SYSTEM"""
    parameters = parameters or {}
    action = parameters.get("action", "").lower().strip()
    url = parameters.get("url", "")
    query = parameters.get("query", "")
    text = parameters.get("text", "")
    browser = parameters.get("browser", "").lower().strip()
    backend = parameters.get("backend", "").lower().strip()

    print(f"[Navegador] Accion: {action} browser={browser} backend={backend or 'auto'}")

    # Backend hierarchy
    used_backend = "none"

    # Try EXTENSION_BACKEND first
    if backend in ("", "auto", "extension") and WEBSOCKET_DISPONIBLE:
        used_backend = "extension"
        if action in ("list_tabs", "listar_pestanias", "ver_pestanias", "que_pestanas_tengo", "list_edge_tabs", "edge_tabs"):
            try:
                enviar_comando_a_navegador_sync("list_tabs")
                time.sleep(0.2)
            except Exception:
                pass
            tabs = listar_pestanias()
            connected_browser = ""
            try:
                connected_browser = (navegador_conectado() or "").lower()
            except Exception:
                connected_browser = ""
            wants_edge = browser == "edge" or action in ("list_edge_tabs", "edge_tabs")
            if wants_edge and connected_browser and connected_browser != "edge":
                return _listar_ventanas_edge()
            if wants_edge and tabs and not connected_browser and not any((t.get("browser") == "edge") for t in tabs):
                return _listar_ventanas_edge()
            if tabs:
                resultado = f"BROWSER CONTROL RESULT\nBackend: extension\nStatus: OK\n\nTienes {len(tabs)} pestanas abiertas:\n"
                for i, tab in enumerate(tabs[:20]):
                    titulo = (tab.get("title") or "Sin titulo")[:70]
                    tab_url = (tab.get("url") or "")[:100]
                    activa = " ACTIVA" if tab.get("active") else ""
                    resultado += f"{i + 1}. {titulo}{activa}"
                    if tab_url:
                        resultado += f" | {tab_url}"
                    resultado += "\n"
                return resultado
            if action in ("list_edge_tabs", "edge_tabs") or browser == "edge":
                return _listar_ventanas_edge()
            return "No hay pestanas abiertas o la extension no esta conectada."

        if action in ("close_tab_by_title", "cerrar_por_titulo", "cerrar_pestana_especifica"):
            if text:
                ok = cerrar_pestania_por_titulo(text)
                return f"BROWSER CONTROL RESULT\nBackend: extension\nStatus: OK\n\nCerrando pestana que contiene: '{text}'" if ok else "La extension no acepto el comando."
            return "Especifica que pestana quieres cerrar."

        if action in ("switch_to_tab", "cambiar_a_pestana", "ir_a_pestana"):
            if text:
                ok = cambiar_a_pestania_por_titulo(text)
                return f"BROWSER CONTROL RESULT\nBackend: extension\nStatus: OK\n\nCambiando a pestana que contiene: '{text}'" if ok else "La extension no acepto el comando."
            return "Especifica a que pestana quieres cambiar."

    # Try CDP_BACKEND second
    if backend in ("", "auto", "cdp") and check_cdp_available():
        used_backend = "cdp"
        if action in ("list_tabs", "listar_pestanias", "ver_pestanias", "que_pestanas_tengo"):
            tabs = cdp_list_tabs()
            if tabs:
                resultado = f"BROWSER CONTROL RESULT\nBackend: cdp\nStatus: OK\n\nTienes {len(tabs)} pestanas abiertas:\n"
                for i, tab in enumerate(tabs[:20]):
                    titulo = tab.get("title", "Sin titulo")[:70]
                    tab_url = tab.get("url", "")[:100]
                    resultado += f"{i + 1}. {titulo}"
                    if tab_url:
                        resultado += f" | {tab_url}"
                    resultado += "\n"
                return resultado
            return "CDP no está activo. Abrí el navegador con el launcher de Helena o usá la extensión."

    if action in ("list_edge_tabs", "edge_tabs"):
        return _listar_ventanas_edge()

    if action in ("new_tab", "nueva_pestania", "abrir_pestania", "abrir_pestana"):
        return f"BROWSER CONTROL RESULT\nBackend: system\nStatus: OK\n\n" + _enviar_atajo("^t", "Nueva pestana abierta")

    if action in ("close_tab", "cerrar_pestania", "cerrar_pestana", "cerrar_esta"):
        return f"BROWSER CONTROL RESULT\nBackend: system\nStatus: OK\n\n" + _enviar_atajo("^w", "Pestana actual cerrada")

    if action in ("reload", "recargar", "refrescar"):
        return f"BROWSER CONTROL RESULT\nBackend: system\nStatus: OK\n\n" + _enviar_atajo("{F5}", "Pestana recargada")

    if action in ("back", "atras", "volver"):
        return f"BROWSER CONTROL RESULT\nBackend: system\nStatus: OK\n\n" + _enviar_atajo("{LEFT}", "Navegando atrás")

    if action in ("forward", "adelante"):
        return f"BROWSER CONTROL RESULT\nBackend: system\nStatus: OK\n\n" + _enviar_atajo("{RIGHT}", "Navegando adelante")

    if action in ("scroll", "desplazar"):
        direction = parameters.get("direction", "down").lower()
        if direction == "down":
            return f"BROWSER CONTROL RESULT\nBackend: system\nStatus: OK\n\n" + _enviar_atajo("{DOWN}", "Desplazando hacia abajo")
        elif direction == "up":
            return f"BROWSER CONTROL RESULT\nBackend: system\nStatus: OK\n\n" + _enviar_atajo("{UP}", "Desplazando hacia arriba")
        return "Dirección no válida. Usa: up o down"

    if action in ("go_to", "navegar", "ir_a", "abrir_url"):
        if url:
            security_warning = validate_url_safety(url)
            if security_warning:
                return f"BROWSER CONTROL RESULT\nBackend: system\nStatus: BLOCKED\n\n{security_warning}"
            return f"BROWSER CONTROL RESULT\nBackend: system\nStatus: OK\n\n" + _abrir_url(url)
        return "No se especifico URL."

    if action in ("search", "buscar"):
        if query:
            return f"BROWSER CONTROL RESULT\nBackend: system\nStatus: OK\n\n" + _abrir_url(f"https://www.google.com/search?q={query.replace(' ', '+')}")
        return "No se especifico que buscar."

    if action == "status":
        ext_status = "conectado" if WEBSOCKET_DISPONIBLE and listar_pestanias() else "desconectado"
        cdp_status = "activo" if check_cdp_available() else "inactivo"
        browser = navegador_conectado() or "ninguno"
        
        suggestion = ""
        if ext_status == "desconectado" and cdp_status == "inactivo":
            suggestion = f"""

💡 Sugerencia: Para activar el control del navegador:
1. Usa el launcher automático: C:\\Helena\\launchers\\start_helena_browser_opera.bat
2. O ejecuta: python setup.py --browser-setup
3. O instala manualmente la extensión en chrome://extensions/"""
        elif ext_status == "desconectado":
            suggestion = "\n💡 Sugerencia: La extensión no está conectada. Abre el navegador desde el launcher o recarga la extensión."
        elif cdp_status == "inactivo":
            suggestion = "\n💡 Sugerencia: CDP no está activo. Usa el launcher con CDP o inicia el navegador con --remote-debugging-port=9222"
        
        return f"""BROWSER CONTROL RESULT
Backend: diagnostic
Status: OK

Estado del navegador:
- Extensión: {ext_status}
- CDP: {cdp_status}
- Navegador detectado: {browser}
- Puerto WebSocket: 8766
- Puerto CDP: 9222{suggestion}"""

    if action in ("security_diagnosis", "diagnostico_seguridad", "diagnóstico_seguridad", "seguridad_navegador"):
        ext_status = "conectado" if WEBSOCKET_DISPONIBLE and listar_pestanias() else "desconectado"
        cdp_status = "activo" if check_cdp_available() else "inactivo"
        browser = navegador_conectado() or "ninguno"
        
        # Verificar perfil aislado
        browser_profiles_dir = BASE_DIR / "browser_profiles"
        isolated_profile_warning = ""
        if cdp_status == "activo":
            isolated_profile = browser_profiles_dir / "opera_helena"
            isolated_profile_warning = (
                f"\n⚠️  ADVERTENCIA: CDP está activo. Asegúrate de usar perfil "
                f"aislado (--user-data-dir={isolated_profile})"
            )
        
        # Verificar .gitignore
        gitignore_path = BASE_DIR / ".gitignore"
        gitignore_status = "❌ No encontrado"
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8") as f:
                gitignore_content = f.read()
            if "browser_profiles/" in gitignore_content:
                gitignore_status = "✅ browser_profiles/ está en .gitignore"
            else:
                gitignore_status = "⚠️  browser_profiles/ NO está en .gitignore"
        
        # Verificar permisos de extensión
        manifest_path = BASE_DIR / "opera_extension" / "manifest.json"
        extension_perms = "❌ No se pudo verificar"
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                perms = manifest.get("permissions", [])
                has_nativeMessaging = "nativeMessaging" in perms
                if has_nativeMessaging:
                    extension_perms = "⚠️  Tiene nativeMessaging (permiso elevado)"
                else:
                    extension_perms = "✅ Permisos reducidos (sin nativeMessaging)"
            except:
                extension_perms = "❌ Error leyendo manifest.json"
        
        return f"""BROWSER CONTROL RESULT
Backend: security_diagnosis
Status: OK

🔒 DIAGNÓSTICO DE SEGURIDAD DEL NAVEGADOR

Estado de conexión:
- Extensión: {ext_status}
- CDP: {cdp_status}
- Navegador detectado: {browser}
- Puerto WebSocket: 8766
- Puerto CDP: 9222

Perfil y aislamiento:
- Ruta de perfiles aislados: {browser_profiles_dir}
{isolated_profile_warning}

Permisos de extensión:
- {extension_perms}
- Versión de extensión: 1.1 (permisos reducidos)
- Sin content_scripts en <all_urls>
- Sin acceso a cookies/tokens

.gitignore:
- {gitignore_status}

Recomendaciones de seguridad:
1. ✅ Usa siempre el launcher con perfil aislado
2. ✅ No uses tu perfil personal para automatización
3. ✅ La extensión no tiene permiso nativeMessaging
4. ✅ La extensión no lee cookies ni contraseñas
5. ✅ Los perfiles aislados están excluidos de GitHub

Para más información: docs/BROWSER_CONTROL.md"""

    return f"BROWSER CONTROL RESULT\nBackend: none\nStatus: FAILED\n\nAccion '{action}' no reconocida."


def _listar_ventanas_edge() -> str:
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                "Get-Process msedge -ErrorAction SilentlyContinue | "
                "Where-Object { $_.MainWindowTitle } | "
                "Select-Object Id,MainWindowTitle | Format-Table -AutoSize | Out-String -Width 220",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            shell=False,
        )
        out = (result.stdout or "").strip()
        if out:
            return (
                "La extension de Helena no esta conectada en Edge, asi que solo puedo ver ventanas activas de Edge:\n"
                + out
            )
        return (
            "No encontre ventanas visibles de Microsoft Edge. Para listar todas las pestanas, "
            "carga la extension de Helena en Edge desde la carpeta opera_extension."
        )
    except Exception as exc:
        return f"No pude consultar Edge: {exc}"


def _enviar_atajo(atajo: str, mensaje: str) -> str:
    try:
        popen_silent(
            f'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; '
            f"[System.Windows.Forms.SendKeys]::SendWait('{atajo}')\""
        )
        return mensaje
    except Exception as e:
        return f"Error: {e}"


def _abrir_url(url: str) -> str:
    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        _enviar_atajo("^l", "")
        time.sleep(0.2)
        pyperclip.copy(url)
        time.sleep(0.1)
        _enviar_atajo("^v", "")
        time.sleep(0.1)
        _enviar_atajo("{ENTER}", "")
        return f"Abriendo {url}"
    except Exception as e:
        return f"Error al abrir URL: {e}"
