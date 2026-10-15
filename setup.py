import subprocess
import sys
import os
import json
import shutil

for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
EXTENSION_DIR = os.path.join(BASE_DIR, "opera_extension")
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
LAUNCHERS_DIR = os.path.join(BASE_DIR, "launchers")
BROWSER_PROFILES_DIR = os.path.join(BASE_DIR, "browser_profiles")

def install_requirements():
    print("Installing requirements...")
    requirements_path = os.path.join(BASE_DIR, "requirements.txt")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", requirements_path], check=True)

def install_playwright():
    print("Installing Playwright browsers...")
    subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)

def detect_browsers():
    """Detecta navegadores instalados con rutas típicas de Windows"""
    browsers = {}
    username = os.getenv("USERNAME", "usuario")
    
    browser_paths = {
        "opera_gx": [
            rf"C:\Users\{username}\AppData\Local\Programs\Opera GX\opera.exe",
            r"C:\Program Files\Opera GX\opera.exe",
            r"C:\Program Files (x86)\Opera GX\opera.exe",
        ],
        "opera": [
            rf"C:\Users\{username}\AppData\Local\Programs\Opera\opera.exe",
            r"C:\Program Files\Opera\opera.exe",
            r"C:\Program Files (x86)\Opera\opera.exe",
            r"C:\Program Files\Opera\launcher.exe",
            r"C:\Program Files (x86)\Opera\launcher.exe",
        ],
        "chrome": [
            rf"C:\Users\{username}\AppData\Local\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
        "edge": [
            rf"C:\Users\{username}\AppData\Local\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "brave": [
            rf"C:\Users\{username}\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
    }
    
    for browser, paths in browser_paths.items():
        for path in paths:
            if os.path.exists(path):
                browsers[browser] = path
                break
    
    return browsers

def validate_extension():
    """Valida que la extensión exista y esté correctamente configurada"""
    manifest_path = os.path.join(EXTENSION_DIR, "manifest.json")
    
    if not os.path.exists(manifest_path):
        return False, "manifest.json no encontrado en opera_extension/"
    
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        return False, f"Error leyendo manifest.json: {e}"
    
    # Validar nombre
    if manifest.get("name") != "Helena Browser Controller":
        return False, f"Nombre incorrecto en manifest: {manifest.get('name')}"
    
    # Validar permisos
    required_permissions = ["tabs", "storage", "activeTab"]
    permissions = manifest.get("permissions", [])
    for perm in required_permissions:
        if perm not in permissions:
            return False, f"Falta permiso requerido: {perm}"
    
    # Validar host permissions para puertos correctos
    host_permissions = manifest.get("host_permissions", [])
    has_8766 = any("8766" in perm for perm in host_permissions)
    has_8765 = any("8765" in perm for perm in host_permissions)
    
    if not has_8766:
        return False, "Falta host permission para puerto 8766"
    
    # Validar archivos requeridos
    required_files = ["background.js", "popup.html", "popup.js"]
    for file in required_files:
        if not os.path.exists(os.path.join(EXTENSION_DIR, file)):
            return False, f"Falta archivo requerido: {file}"
    
    return True, "Extensión válida"

def create_browser_config():
    """Crea configuración de browser control con estructura mejorada"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    
    browsers = detect_browsers()
    extension_valid, extension_msg = validate_extension()
    
    config = {
        "preferred_browser": "opera" if "opera" in browsers or "opera_gx" in browsers else next(iter(browsers), "chrome"),
        "extension_path": EXTENSION_DIR,
        "extension_valid": extension_valid,
        "extension_message": extension_msg,
        "websocket_ports": [8766, 8765],
        "cdp_port": 9222,
        "use_isolated_profile": True,
        "profiles": {
            "opera_gx": os.path.join(BROWSER_PROFILES_DIR, "opera_gx_helena"),
            "opera": os.path.join(BROWSER_PROFILES_DIR, "opera_helena"),
            "chrome": os.path.join(BROWSER_PROFILES_DIR, "chrome_helena"),
            "edge": os.path.join(BROWSER_PROFILES_DIR, "edge_helena"),
            "brave": os.path.join(BROWSER_PROFILES_DIR, "brave_helena"),
        },
        "launchers": {},
        "detected_browsers": browsers
    }
    
    # Agregar paths de launchers
    for browser in browsers:
        config["launchers"][browser] = os.path.join(LAUNCHERS_DIR, f"start_helena_browser_{browser}.bat")
        config["launchers"][f"{browser}_extension_only"] = os.path.join(LAUNCHERS_DIR, f"start_helena_browser_{browser}_extension_only.bat")
    
    config_path = os.path.join(CONFIG_DIR, "browser_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Browser config created: {config_path}")
    return config

def create_browser_launchers():
    """Crea scripts .bat para lanzar navegadores con perfil aislado y extensión cargada"""
    os.makedirs(LAUNCHERS_DIR, exist_ok=True)
    os.makedirs(BROWSER_PROFILES_DIR, exist_ok=True)
    
    browsers = detect_browsers()
    
    for browser, exe_path in browsers.items():
        profile_path = os.path.join(BROWSER_PROFILES_DIR, f"{browser}_helena")
        
        # Launcher con CDP y extensión
        bat_content = f"""@echo off
set HELENA_ROOT={BASE_DIR}
echo Lanzando {{BROWSER_NAME}} con perfil aislado de Helena y extensión cargada...
start "" "{exe_path}" ^
  --user-data-dir="{profile_path}" ^
  --load-extension="{EXTENSION_DIR}" ^
  --remote-debugging-port=9222 ^
  --no-first-run
echo Navegador iniciado. Helena puede controlarlo via WebSocket (puerto 8766) y CDP (puerto 9222).
pause
"""
        browser_name = browser.replace("_", " ").title()
        bat_content = bat_content.replace("{BROWSER_NAME}", browser_name)
        
        bat_path = os.path.join(LAUNCHERS_DIR, f"start_helena_browser_{browser}.bat")
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)
        print(f"✅ Launcher created: {bat_path}")
        
        # Launcher sin CDP (solo extensión)
        bat_content_no_cdp = f"""@echo off
set HELENA_ROOT={BASE_DIR}
echo Lanzando {{BROWSER_NAME}} con perfil aislado de Helena y extensión cargada (sin CDP)...
start "" "{exe_path}" ^
  --user-data-dir="{profile_path}" ^
  --load-extension="{EXTENSION_DIR}" ^
  --no-first-run
echo Navegador iniciado. Helena puede controlarlo via WebSocket (puerto 8766).
pause
"""
        bat_content_no_cdp = bat_content_no_cdp.replace("{BROWSER_NAME}", browser_name)
        
        bat_path_no_cdp = os.path.join(LAUNCHERS_DIR, f"start_helena_browser_{browser}_extension_only.bat")
        with open(bat_path_no_cdp, "w", encoding="utf-8") as f:
            f.write(bat_content_no_cdp)
        print(f"✅ Launcher (extension only) created: {bat_path_no_cdp}")

def create_example_configs():
    """Crea archivos de configuración de ejemplo"""
    # api_keys.example.json
    api_keys_example = {
        "openai": "your-openai-api-key-here",
        "anthropic": "your-anthropic-api-key-here",
        "google": "your-google-api-key-here"
    }
    with open(os.path.join(CONFIG_DIR, "api_keys.example.json"), "w", encoding="utf-8") as f:
        json.dump(api_keys_example, f, indent=2)
    
    # browser_config.example.json
    browser_config_example = {
        "browser_ws_port": 8766,
        "cdp_port": 9222,
        "browser_preferred": "opera",
        "extension_path": "opera_extension",
        "browser_profiles": {
            "opera": "browser_profiles\\opera_helena",
            "chrome": "browser_profiles\\chrome_helena",
            "edge": "browser_profiles\\edge_helena"
        }
    }
    with open(os.path.join(CONFIG_DIR, "browser_config.example.json"), "w", encoding="utf-8") as f:
        json.dump(browser_config_example, f, indent=2)
    
    print("✅ Example configs created")

def show_manual_install_instructions():
    """Muestra instrucciones para instalación manual en perfil personal"""
    print("\n" + "="*60)
    print("INSTALACIÓN MANUAL EN PERFIL PERSONAL")
    print("="*60)
    print("\nSi prefieres usar tu navegador personal (sin perfil aislado):")
    print("\n1. Abre tu navegador (Opera, Chrome, Edge)")
    print("2. Ve a la página de extensiones:")
    print("   - Opera/Chrome: chrome://extensions/")
    print("   - Edge: edge://extensions/")
    print("3. Activa 'Modo desarrollador'")
    print("4. Haz clic en 'Cargar extensión sin empaquetar'")
    print(f"5. Selecciona: {EXTENSION_DIR}")
    print("\n⚠️  Nota: Esto instalará la extensión en tu perfil personal.")
    print("   Helena no instalará extensiones silenciosamente por seguridad.")
    print("="*60)

def diagnose_browser_setup():
    """Diagnostica el estado de browser control"""
    print("\n" + "="*60)
    print("DIAGNÓSTICO DE BROWSER CONTROL")
    print("="*60)
    
    # Detectar navegadores
    print("\n🔍 Navegadores encontrados:")
    browsers = detect_browsers()
    if browsers:
        for browser, path in browsers.items():
            print(f"  ✅ {browser}: {path}")
    else:
        print("  ❌ No se encontraron navegadores")
    
    # Validar extensión
    print("\n📦 Extensión:")
    extension_valid, extension_msg = validate_extension()
    print(f"  {'✅' if extension_valid else '❌'} {extension_msg}")
    print(f"  Ruta: {EXTENSION_DIR}")
    
    # Verificar carpetas
    print("\n📁 Carpetas:")
    print(f"  {'✅' if os.path.exists(CONFIG_DIR) else '❌'} {CONFIG_DIR}")
    print(f"  {'✅' if os.path.exists(LAUNCHERS_DIR) else '❌'} {LAUNCHERS_DIR}")
    print(f"  {'✅' if os.path.exists(BROWSER_PROFILES_DIR) else '❌'} {BROWSER_PROFILES_DIR}")
    
    # Verificar launchers
    print("\n🚀 Launchers:")
    if os.path.exists(LAUNCHERS_DIR):
        for file in os.listdir(LAUNCHERS_DIR):
            if file.endswith(".bat"):
                print(f"  ✅ {file}")
    else:
        print("  ❌ No hay launchers creados")
    
    # Verificar config
    print("\n⚙️  Configuración:")
    config_path = os.path.join(CONFIG_DIR, "browser_config.json")
    if os.path.exists(config_path):
        print(f"  ✅ {config_path}")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            print(f"  Navegador preferido: {config.get('preferred_browser', 'no configurado')}")
            print(f"  Extensión válida: {config.get('extension_valid', 'no verificado')}")
            print(f"  Perfil aislado: {config.get('use_isolated_profile', False)}")
        except Exception as e:
            print(f"  ❌ Error leyendo config: {e}")
    else:
        print(f"  ❌ {config_path} no existe")
    
    # Puertos
    print("\n🔌 Puertos:")
    print("  WebSocket: 8766 (principal), 8765 (fallback)")
    print("  CDP: 9222")
    
    print("\n" + "="*60)
    print("Para crear launchers y configuración:")
    print("  python setup.py --browser-setup")
    print("\nPara instalación manual en perfil personal:")
    print("  python setup.py --manual-install")
    print("="*60)

def setup_browser_control():
    """Configura browser control con perfil aislado y extensión automática"""
    print("\n" + "="*60)
    print("BROWSER CONTROL SETUP - MODO AUTOMÁTICO SEGURO")
    print("="*60)
    
    print("\n🔍 Detectando navegadores...")
    browsers = detect_browsers()
    if browsers:
        print(f"✅ Navegadores encontrados: {', '.join(browsers.keys())}")
        for browser, path in browsers.items():
            print(f"   - {browser}: {path}")
    else:
        print("⚠️  No se encontraron navegadores")
    
    print("\n📦 Validando extensión...")
    extension_valid, extension_msg = validate_extension()
    if extension_valid:
        print(f"✅ {extension_msg}")
    else:
        print(f"❌ {extension_msg}")
    
    print("\n� Creando carpetas necesarias...")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(LAUNCHERS_DIR, exist_ok=True)
    os.makedirs(BROWSER_PROFILES_DIR, exist_ok=True)
    print(f"✅ {CONFIG_DIR}")
    print(f"✅ {LAUNCHERS_DIR}")
    print(f"✅ {BROWSER_PROFILES_DIR}")
    
    print("\n📝 Creando configuración...")
    create_browser_config()
    
    print("\n🚀 Creando launchers con perfil aislado...")
    create_browser_launchers()
    
    print("\n📄 Creando configs de ejemplo...")
    create_example_configs()
    
    print("\n" + "="*60)
    print("BROWSER CONTROL SETUP COMPLETADO")
    print("="*60)
    print("\n🎉 Sistema listo para uso automático:")
    print(f"- Perfiles aislados en: {BROWSER_PROFILES_DIR}")
    print(f"- Launchers en: {LAUNCHERS_DIR}")
    print(f"- Config en: {CONFIG_DIR}")
    print("\n📖 Para iniciar navegador con extensión cargada:")
    for browser in browsers:
        print(f"  {os.path.join(LAUNCHERS_DIR, f'start_helena_browser_{browser}.bat')}")
    print("\n⚠️  Los launchers usan perfiles aislados para no tocar tu perfil personal.")
    print("="*60)

def main():
    browser_setup = "--browser-setup" in sys.argv
    dry_run = "--dry-run" in sys.argv
    install_extension = "--install-browser-extension" in sys.argv
    create_launchers = "--create-browser-launchers" in sys.argv
    secure_profile = "--browser-secure-profile" in sys.argv
    diagnose = "--diagnose" in sys.argv
    manual_install = "--manual-install" in sys.argv
    
    if diagnose:
        diagnose_browser_setup()
        return
    
    if manual_install:
        show_manual_install_instructions()
        return
    
    if dry_run:
        print("🔍 MODO DRY RUN - No se harán cambios")
        print("\nNavegadores que se detectarían:")
        browsers = detect_browsers()
        for browser, path in browsers.items():
            print(f"  - {browser}: {path}")
        
        print("\nExtensión:")
        extension_valid, extension_msg = validate_extension()
        print(f"  {'✅' if extension_valid else '❌'} {extension_msg}")
        
        print("\nConfiguración que se crearía:")
        print(f"  - {os.path.join(CONFIG_DIR, 'browser_config.json')}")
        print(f"  - {os.path.join(CONFIG_DIR, 'api_keys.example.json')}")
        print(f"  - {os.path.join(CONFIG_DIR, 'browser_config.example.json')}")
        
        print("\nLaunchers que se crearían:")
        for browser in browsers:
            print(f"  - start_helena_browser_{browser}.bat (con CDP)")
            print(f"  - start_helena_browser_{browser}_extension_only.bat (sin CDP)")
        
        print("\nCarpetas que se crearían:")
        print(f"  - {CONFIG_DIR}")
        print(f"  - {LAUNCHERS_DIR}")
        print(f"  - {BROWSER_PROFILES_DIR}")
        return
    
    install_requirements()
    install_playwright()
    
    if browser_setup or install_extension or create_launchers or secure_profile:
        setup_browser_control()
    
    print("\n✅ Setup completado! Ejecuta 'python main.py' para iniciar Helena.")
    if browser_setup:
        print("Ejecuta 'python setup.py --browser-setup' para configurar browser control.")
    print("Ejecuta 'python setup.py --diagnose' para diagnosticar browser control.")
    print("Ejecuta 'python setup.py --manual-install' para instrucciones de instalación manual.")

if __name__ == "__main__":
    main()