# launch_browser_debug.py - Launcher para navegadores con remote debugging
import subprocess
import sys
import os
import json

# Configuración
CDP_PORT = 9222
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER_PROFILES = os.path.join(BASE_DIR, "browser_profiles")

def ensure_profile_dir(browser_name):
    """Asegura que el directorio de perfil existe"""
    profile_path = os.path.join(BROWSER_PROFILES, f"{browser_name}_helena")
    os.makedirs(profile_path, exist_ok=True)
    return profile_path

def find_browser_executable(browser_name):
    """Busca el ejecutable del navegador"""
    browser_paths = {
        "opera": [
            r"C:\Program Files\Opera\launcher.exe",
            r"C:\Program Files (x86)\Opera\launcher.exe",
            r"C:\Users\{}\AppData\Local\Programs\Opera\launcher.exe".format(os.getenv("USERNAME")),
        ],
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Users\{}\AppData\Local\Google\Chrome\Application\chrome.exe".format(os.getenv("USERNAME")),
        ],
        "edge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Users\{}\AppData\Local\Microsoft\Edge\Application\msedge.exe".format(os.getenv("USERNAME")),
        ],
        "brave": [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Users\{}\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe".format(os.getenv("USERNAME")),
        ],
    }
    
    paths = browser_paths.get(browser_name.lower(), [])
    for path in paths:
        if os.path.exists(path):
            return path
    return None

def launch_opera():
    """Lanza Opera con remote debugging"""
    exe = find_browser_executable("opera")
    if not exe:
        print("❌ No se encontró Opera. Instálalo o verifica la ruta.")
        return False
    
    profile = ensure_profile_dir("opera")
    cmd = [
        exe,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile}",
        "--new-window"
    ]
    
    print(f"🚀 Lanzando Opera con debugging en puerto {CDP_PORT}")
    print(f"📁 Perfil: {profile}")
    subprocess.Popen(cmd, detached=True)
    return True

def launch_chrome():
    """Lanza Chrome con remote debugging"""
    exe = find_browser_executable("chrome")
    if not exe:
        print("❌ No se encontró Chrome. Instálalo o verifica la ruta.")
        return False
    
    profile = ensure_profile_dir("chrome")
    cmd = [
        exe,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile}",
        "--new-window"
    ]
    
    print(f"🚀 Lanzando Chrome con debugging en puerto {CDP_PORT}")
    print(f"📁 Perfil: {profile}")
    subprocess.Popen(cmd, detached=True)
    return True

def launch_edge():
    """Lanza Edge con remote debugging"""
    exe = find_browser_executable("edge")
    if not exe:
        print("❌ No se encontró Edge. Instálalo o verifica la ruta.")
        return False
    
    profile = ensure_profile_dir("edge")
    cmd = [
        exe,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile}",
        "--new-window"
    ]
    
    print(f"🚀 Lanzando Edge con debugging en puerto {CDP_PORT}")
    print(f"📁 Perfil: {profile}")
    subprocess.Popen(cmd, detached=True)
    return True

def launch_brave():
    """Lanza Brave con remote debugging"""
    exe = find_browser_executable("brave")
    if not exe:
        print("❌ No se encontró Brave. Instálalo o verifica la ruta.")
        return False
    
    profile = ensure_profile_dir("brave")
    cmd = [
        exe,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile}",
        "--new-window"
    ]
    
    print(f"🚀 Lanzando Brave con debugging en puerto {CDP_PORT}")
    print(f"📁 Perfil: {profile}")
    subprocess.Popen(cmd, detached=True)
    return True

def main():
    if len(sys.argv) < 2:
        print("Uso: python launch_browser_debug.py [opera|chrome|edge|brave]")
        print("\nNavegadores detectados:")
        for browser in ["opera", "chrome", "edge", "brave"]:
            exe = find_browser_executable(browser)
            if exe:
                print(f"  ✅ {browser}: {exe}")
            else:
                print(f"  ❌ {browser}: no encontrado")
        return
    
    browser = sys.argv[1].lower()
    
    if browser == "opera":
        launch_opera()
    elif browser == "chrome":
        launch_chrome()
    elif browser == "edge":
        launch_edge()
    elif browser == "brave":
        launch_brave()
    else:
        print(f"❌ Navegador no soportado: {browser}")
        print("Navegadores soportados: opera, chrome, edge, brave")

if __name__ == "__main__":
    main()
