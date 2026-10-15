#computer_settings.py
import json
import re
import sys
import time
import subprocess
import platform
import ctypes
from pathlib import Path

# Importar utilidades silenciosas
sys.path.insert(0, r'C:\helena')
from utils.silent_subprocess import run_silent, popen_silent, powershell_silent

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_macos_wifi_interface() -> str:
    try:
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for j in range(i, min(i + 4, len(lines))):
                    if lines[j].startswith("Device:"):
                        return lines[j].split(":", 1)[1].strip()
    except Exception:
        pass
    return "en0"

def volume_up():
    if _OS == "Windows":
        for _ in range(5): pyautogui.press("volumeup")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            "set volume output volume (output volume of (get volume settings) + 10)"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"],
            capture_output=True)

def volume_down():
    if _OS == "Windows":
        for _ in range(5): pyautogui.press("volumedown")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            "set volume output volume (output volume of (get volume settings) - 10)"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"],
            capture_output=True)

def volume_mute():
    if _OS == "Windows":
        pyautogui.press("volumemute")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", "set volume with output muted"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
            capture_output=True)

def volume_set(value: int):
    value = max(0, min(100, int(value)))
    if _OS == "Windows":
        try:
            import math
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices   = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol       = cast(interface, POINTER(IAudioEndpointVolume))
            vol_db    = -65.25 if value == 0 else max(-65.25, 20 * math.log10(value / 100))
            vol.SetMasterVolumeLevel(vol_db, None)
            return f"Volume set requested: {value}%. Result: OK via pycaw."
        except Exception as e:
            print(f"[Settings] pycaw failed, using keypress fallback: {e}")
            return f"Volume set requested: {value}%. Result: FAILED ({e})."
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", f"set volume output volume {value}"],
            capture_output=True)
        return f"Volume set requested: {value}%. Result: OK."
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"],
            capture_output=True)
        return f"Volume set requested: {value}%. Result: OK."

def _get_current_brightness(default: int = 50) -> int:
    if _OS != "Windows":
        return default
    result = powershell_silent(
        "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 -ExpandProperty CurrentBrightness)"
    )
    try:
        out = (result.stdout or b"").decode(errors="ignore").strip() if result else ""
        return int(out) if out else default
    except Exception:
        return default

def _set_ddcci_brightness(value: int) -> tuple[bool, str]:
    """Set brightness on external DDC/CI monitors on Windows."""
    if _OS != "Windows":
        return False, "DDC/CI solo aplica en Windows."
    value = max(0, min(100, int(value)))
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        dxva2 = ctypes.windll.dxva2
        HMONITOR = getattr(wintypes, "HMONITOR", wintypes.HANDLE)
        HDC = getattr(wintypes, "HDC", wintypes.HANDLE)
        monitors = []
        enum_proc_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            HMONITOR,
            HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )

        def _enum_proc(hmonitor, hdc, rect, lparam):
            monitors.append(hmonitor)
            return True

        if not user32.EnumDisplayMonitors(0, 0, enum_proc_type(_enum_proc), 0):
            return False, "Windows no devolvio monitores."

        changed = 0
        for hmonitor in monitors:
            count = wintypes.DWORD()
            if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmonitor, ctypes.byref(count)):
                continue
            if count.value <= 0:
                continue

            class PHYSICAL_MONITOR(ctypes.Structure):
                _fields_ = [
                    ("hPhysicalMonitor", wintypes.HANDLE),
                    ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
                ]

            physical = (PHYSICAL_MONITOR * count.value)()
            if not dxva2.GetPhysicalMonitorsFromHMONITOR(hmonitor, count, physical):
                continue
            try:
                for monitor in physical:
                    if dxva2.SetVCPFeature(monitor.hPhysicalMonitor, 0x10, wintypes.DWORD(value)):
                        changed += 1
            finally:
                dxva2.DestroyPhysicalMonitors(count, physical)

        if changed:
            return True, f"Brillo DDC/CI aplicado a {changed} monitor(es): {value}%."
        return False, "No encontre monitores compatibles con DDC/CI."
    except Exception as exc:
        return False, f"DDC/CI fallo: {exc}"

def brightness_set(value: int) -> str:
    value = max(0, min(100, int(value)))
    if _OS == "Windows":
        ps = (
            "$b=[Math]::Max(0,[Math]::Min(100,{value})); "
            "$m=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue; "
            "if ($m) {{ $m | ForEach-Object {{ $_.WmiSetBrightness(1,$b) | Out-Null }}; 'WMI_OK' }} "
            "else {{ 'NO_WMI' }}"
        ).format(value=value)
        result = powershell_silent(ps)
        out = ""
        if result is not None:
            try:
                out = ((result.stdout or b"") + (result.stderr or b"")).decode(errors="ignore")
            except Exception:
                out = str(result)
        if result is not None and result.returncode == 0 and "WMI_OK" in out:
            return f"Brillo del monitor ajustado a {value}%."

        ok, msg = _set_ddcci_brightness(value)
        if ok:
            return msg
        return "El brillo no parece estar soportado por este dispositivo."

    if _OS == "Darwin":
        return "Ajuste exacto de brillo no implementado en macOS; puedo subir o bajar el brillo."

    if subprocess.run(["which", "brightnessctl"], capture_output=True).returncode == 0:
        subprocess.run(["brightnessctl", "set", f"{value}%"], capture_output=True)
        return f"Brillo ajustado a {value}%."
    return "No encontre brightnessctl para ajustar brillo exacto en Linux."

def brightness_up():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to key code 144'],
            capture_output=True)
    elif _OS == "Linux":
        if subprocess.run(["which", "brightnessctl"],
                capture_output=True).returncode == 0:
            subprocess.run(["brightnessctl", "set", "+10%"], capture_output=True)
        else:
            subprocess.run(
                'xrandr --output $(xrandr | grep " connected" | head -1 | cut -d " " -f1)'
                ' --brightness $(python3 -c "import subprocess; '
                'b=float(subprocess.check_output([\"xrandr\",\"--verbose\"]).decode()'
                '.split(\"Brightness:\")[1].split()[0]); print(min(1.0,b+0.1))")',
                shell=True, capture_output=True
            )
    else:
        return brightness_set(_get_current_brightness(default=50) + 10)

def brightness_down():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to key code 145'],
            capture_output=True)
    elif _OS == "Linux":
        if subprocess.run(["which", "brightnessctl"],
                capture_output=True).returncode == 0:
            subprocess.run(["brightnessctl", "set", "10%-"], capture_output=True)
        else:
            subprocess.run(
                'xrandr --output $(xrandr | grep " connected" | head -1 | cut -d " " -f1)'
                ' --brightness $(python3 -c "import subprocess; '
                'b=float(subprocess.check_output([\"xrandr\",\"--verbose\"]).decode()'
                '.split(\"Brightness:\")[1].split()[0]); print(max(0.1,b-0.1))")',
                shell=True, capture_output=True
            )
    else:
        return brightness_set(_get_current_brightness(default=50) - 10)

def close_app_alt_f4():
    """Cierra la ventana activa con Alt+F4"""
    if _OS == "Darwin":
        pyautogui.hotkey("command", "q")
    else:
        pyautogui.hotkey("alt", "f4")
    print("[Settings] ✅ Ventana cerrada (Alt+F4)")

def close_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "w")
    else:               pyautogui.hotkey("ctrl", "w")

def full_screen():
    if _OS == "Darwin": pyautogui.hotkey("ctrl", "command", "f")
    else:               pyautogui.press("f11")

def minimize_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "m")
    else:               pyautogui.hotkey("win", "down")

def maximize_window():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to keystroke "f" '
            'using {control down, command down}'],
            capture_output=True)
    elif _OS == "Windows":
        pyautogui.hotkey("win", "up")
    else:
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-b", "add,maximized_vert,maximized_horz"],
                capture_output=True)
        except Exception:
            pyautogui.hotkey("super", "up")

def snap_left():
    if _OS == "Windows":
        pyautogui.hotkey("win", "left")
    elif _OS == "Linux":
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", "0,0,0,960,1080"],
                capture_output=True)
        except Exception:
            pass

def snap_right():
    if _OS == "Windows":
        pyautogui.hotkey("win", "right")
    elif _OS == "Linux":
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", "0,960,0,960,1080"],
                capture_output=True)
        except Exception:
            pass

def switch_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "tab")
    else:               pyautogui.hotkey("alt", "tab")

def show_desktop():
    if _OS == "Darwin":   pyautogui.hotkey("fn", "f11")
    elif _OS == "Windows": pyautogui.hotkey("win", "d")
    else:                  pyautogui.hotkey("super", "d")

def open_task_manager():
    if _OS == "Windows":
        pyautogui.hotkey("ctrl", "shift", "esc")
    elif _OS == "Darwin":
        subprocess.Popen(["open", "-a", "Activity Monitor"])
    else:
        for cmd in [["gnome-system-monitor"], ["xfce4-taskmanager"], ["htop"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                break


def focus_search():
    if _OS == "Darwin": pyautogui.hotkey("command", "l")
    else:               pyautogui.hotkey("ctrl", "l")

def pause_video():      pyautogui.press("space")

def refresh_page():
    if _OS == "Darwin": pyautogui.hotkey("command", "r")
    else:               pyautogui.press("f5")

def close_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "w")
    else:               pyautogui.hotkey("ctrl", "w")

def new_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "t")
    else:               pyautogui.hotkey("ctrl", "t")

def next_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "bracketright")
    else:               pyautogui.hotkey("ctrl", "tab")

def prev_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "bracketleft")
    else:               pyautogui.hotkey("ctrl", "shift", "tab")

def go_back():
    if _OS == "Darwin": pyautogui.hotkey("command", "left")
    else:               pyautogui.hotkey("alt", "left")

def go_forward():
    if _OS == "Darwin": pyautogui.hotkey("command", "right")
    else:               pyautogui.hotkey("alt", "right")

def zoom_in():
    if _OS == "Darwin": pyautogui.hotkey("command", "equal")
    else:               pyautogui.hotkey("ctrl", "equal")

def zoom_out():
    if _OS == "Darwin": pyautogui.hotkey("command", "minus")
    else:               pyautogui.hotkey("ctrl", "minus")

def zoom_reset():
    if _OS == "Darwin": pyautogui.hotkey("command", "0")
    else:               pyautogui.hotkey("ctrl", "0")

def find_on_page():
    if _OS == "Darwin": pyautogui.hotkey("command", "f")
    else:               pyautogui.hotkey("ctrl", "f")

def reload_page_n(n: int):
    for _ in range(max(1, n)):
        refresh_page()
        time.sleep(0.8)


def scroll_up(amount: int = 500):    pyautogui.scroll(amount)
def scroll_down(amount: int = 500):  pyautogui.scroll(-amount)

def scroll_top():
    if _OS == "Darwin": pyautogui.hotkey("command", "up")
    else:               pyautogui.hotkey("ctrl", "home")

def scroll_bottom():
    if _OS == "Darwin": pyautogui.hotkey("command", "down")
    else:               pyautogui.hotkey("ctrl", "end")

def page_up():   pyautogui.press("pageup")
def page_down(): pyautogui.press("pagedown")


def copy():
    if _OS == "Darwin": pyautogui.hotkey("command", "c")
    else:               pyautogui.hotkey("ctrl", "c")

def paste():
    if _OS == "Darwin": pyautogui.hotkey("command", "v")
    else:               pyautogui.hotkey("ctrl", "v")

def cut():
    if _OS == "Darwin": pyautogui.hotkey("command", "x")
    else:               pyautogui.hotkey("ctrl", "x")

def undo():
    if _OS == "Darwin": pyautogui.hotkey("command", "z")
    else:               pyautogui.hotkey("ctrl", "z")

def redo():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "z")
    else:               pyautogui.hotkey("ctrl", "y")

def select_all():
    if _OS == "Darwin": pyautogui.hotkey("command", "a")
    else:               pyautogui.hotkey("ctrl", "a")

def save_file():
    if _OS == "Darwin": pyautogui.hotkey("command", "s")
    else:               pyautogui.hotkey("ctrl", "s")

def press_enter():   pyautogui.press("enter")
def press_escape():  pyautogui.press("escape")
def press_key(key: str): pyautogui.press(key)

def type_text(text: str, press_enter_after: bool = False):
    if not text:
        return
    if _PYPERCLIP:
        pyperclip.copy(str(text))
        time.sleep(0.15)
        paste()
    else:
        pyautogui.write(str(text), interval=0.03)
    if press_enter_after:
        time.sleep(0.1)
        pyautogui.press("enter")

def take_screenshot():
    if _OS == "Windows":
        pyautogui.hotkey("win", "shift", "s")
    elif _OS == "Darwin":
        pyautogui.hotkey("command", "shift", "3")
    else:
        for cmd in [["scrot"], ["gnome-screenshot"], ["import", "-window", "root", "screenshot.png"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return
        pyautogui.hotkey("ctrl", "print_screen")

def lock_screen():
    if _OS == "Windows":
        pyautogui.hotkey("win", "l")
    elif _OS == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
    else:
        for cmd in [
            ["gnome-screensaver-command", "-l"],
            ["xdg-screensaver", "lock"],
            ["loginctl", "lock-session"],
        ]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.run(cmd, capture_output=True)
                return

def open_system_settings():
    if _OS == "Windows":
        pyautogui.hotkey("win", "i")
    elif _OS == "Darwin":
        subprocess.Popen(["open", "-a", "System Preferences"])
    else:
        for cmd in [["gnome-control-center"], ["xfce4-settings-manager"], ["kcmshell5"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return

def open_file_explorer():
    if _OS == "Windows":
        pyautogui.hotkey("win", "e")
    elif _OS == "Darwin":
        subprocess.Popen(["open", str(Path.home())])
    else:
        for cmd in [["nautilus"], ["thunar"], ["dolphin"], ["nemo"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return
        subprocess.Popen(["xdg-open", str(Path.home())])

def sleep_display():
    if _OS == "Windows":
        try:
            import ctypes
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
        except Exception as e:
            print(f"[Settings] sleep_display failed: {e}")
    elif _OS == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
    else:
        subprocess.run(["xset", "dpms", "force", "off"], capture_output=True)

def open_run():
    if _OS == "Windows":
        pyautogui.hotkey("win", "r")

def dark_mode():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell app "System Events" to tell appearance preferences '
            'to set dark mode to not dark mode'],
            capture_output=True)
    elif _OS == "Windows":
        try:
            import winreg
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            current, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, 1 - current)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, 1 - current)
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[Settings] dark_mode registry failed: {e}")
    else:
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True
            )
            current = result.stdout.strip()
            new_scheme = "'default'" if "dark" in current else "'prefer-dark'"
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", new_scheme],
                capture_output=True
            )
        except Exception as e:
            print(f"[Settings] dark_mode Linux failed: {e}")

def toggle_wifi():
    if _OS == "Darwin":
        iface = _get_macos_wifi_interface()
        result = subprocess.run(
            ["networksetup", "-getairportpower", iface],
            capture_output=True, text=True
        )
        state = "off" if "On" in result.stdout else "on"
        subprocess.run(["networksetup", "-setairportpower", iface, state],
            capture_output=True)
    elif _OS == "Windows":
        powershell_silent(
            "$adapter = Get-NetAdapter | Where-Object {$_.PhysicalMediaType -eq 'Native 802.11'};"
            "if ($adapter.Status -eq 'Up') { Disable-NetAdapter -Name $adapter.Name -Confirm:$false }"
            "else { Enable-NetAdapter -Name $adapter.Name -Confirm:$false }"
        )
    else:
        try:
            result = subprocess.run(["nmcli", "radio", "wifi"], capture_output=True, text=True)
            state  = "off" if "enabled" in result.stdout else "on"
            subprocess.run(["nmcli", "radio", "wifi", state], capture_output=True)
        except Exception as e:
            print(f"[Settings] toggle_wifi Linux failed: {e}")

def restart_computer():
    if _OS == "Windows":
        subprocess.run(["shutdown", "/r", "/t", "10", "/c", "Reinicio solicitado por Helena"], capture_output=True)
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to restart'],
            capture_output=True)
    else:
        subprocess.run(["systemctl", "reboot"], capture_output=True)

def shutdown_computer():
    if _OS == "Windows":
        subprocess.run(["shutdown", "/s", "/t", "10", "/c", "Apagado solicitado por Helena"], capture_output=True)
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to shut down'],
            capture_output=True)
    else:
        subprocess.run(["systemctl", "poweroff"], capture_output=True)

def cancel_shutdown():
    if _OS == "Windows":
        result = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
        if result.returncode == 0:
            return "Apagado o reinicio programado cancelado."
        return result.stderr.strip() or result.stdout.strip() or "No habia apagado programado para cancelar."
    return "Cancelar apagado esta implementado para Windows."

# ============================================================
# FUNCIÓN PARA CERRAR APLICACIONES ESPECÍFICAS POR NOMBRE
# ============================================================

def close_app_by_name(app_name: str):
    """Cierra una aplicación específica por su nombre usando taskkill (Windows)"""
    if _OS != "Windows":
        return f"Cerrar aplicaciones por nombre solo soportado en Windows por ahora"

    try:
        # Buscar procesos que coincidan con el nombre
        result = run_silent(f'tasklist /fi "imagename eq {app_name}.exe" /nh')

        if result and app_name.lower() in result.stdout.lower():
            run_silent(f'taskkill /f /im "{app_name}.exe"')
            print(f"[Settings] ✅ Aplicación cerrada: {app_name}")
            return f"Aplicación {app_name} cerrada"
        else:
            # Intentar buscar coincidencias parciales
            result2 = run_silent('tasklist /nh')
            if result2:
                for line in result2.stdout.splitlines():
                    if app_name.lower() in line.lower():
                        exe_name = line.split()[0]
                        run_silent(f'taskkill /f /im "{exe_name}"')
                        print(f"[Settings] ✅ Aplicación cerrada: {exe_name}")
                        return f"Aplicación {exe_name} cerrada"

            return f"No se encontró la aplicación {app_name} ejecutándose"
    except Exception as e:
        print(f"[Settings] ❌ Error cerrando {app_name}: {e}")
        return f"Error al cerrar {app_name}: {e}"


# ============================================================
# PRIORIDAD DEL PROCESO HELENA / WINDOWS PERFORMANCE MODE
# ============================================================

def _normalize_priority_level(value=None) -> str:
    raw = str(value or "high").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "alta": "high",
        "alto": "high",
        "high": "high",
        "prioridad_alta": "high",
        "performance": "high",
        "modo_performance": "high",
        "above_normal": "above_normal",
        "arriba_de_normal": "above_normal",
        "media_alta": "above_normal",
        "normal": "normal",
        "baja": "below_normal",
        "low": "below_normal",
        "below_normal": "below_normal",
        "real_time": "high",
        "realtime": "high",
        "tiempo_real": "high",
    }
    return aliases.get(raw, raw if raw in ("high", "above_normal", "normal", "below_normal") else "high")

def set_process_priority(level="high") -> str:
    """Cambia la prioridad del proceso actual de Helena. Evita tiempo real por seguridad."""
    level = _normalize_priority_level(level)
    if _OS != "Windows":
        return "FAILED: El cambio de prioridad automático está implementado para Windows."

    try:
        import os
        pid = os.getpid()
        try:
            import psutil
            proc = psutil.Process(pid)
            before = str(proc.nice())
            mapping = {
                "high": psutil.HIGH_PRIORITY_CLASS,
                "above_normal": psutil.ABOVE_NORMAL_PRIORITY_CLASS,
                "normal": psutil.NORMAL_PRIORITY_CLASS,
                "below_normal": psutil.BELOW_NORMAL_PRIORITY_CLASS,
            }
            proc.nice(mapping[level])
            current = str(proc.nice())
            print(f"[Settings] ✅ Prioridad de Helena aplicada con psutil: {level} pid={pid} current={current}")
            return f"CONFIRMED: prioridad de Helena aplicada a {level}. PID={pid}. Before={before}. After={current}."
        except Exception as psutil_error:
            print(f"[Settings] psutil priority failed, trying ctypes fallback: {psutil_error}")

            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            GetCurrentProcess = kernel32.GetCurrentProcess
            SetPriorityClass = kernel32.SetPriorityClass
            SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            SetPriorityClass.restype = ctypes.c_int

            classes = {
                "high": 0x00000080,          # HIGH_PRIORITY_CLASS
                "above_normal": 0x00008000,  # ABOVE_NORMAL_PRIORITY_CLASS
                "normal": 0x00000020,        # NORMAL_PRIORITY_CLASS
                "below_normal": 0x00004000,  # BELOW_NORMAL_PRIORITY_CLASS
            }
            handle = GetCurrentProcess()
            ok = SetPriorityClass(handle, classes[level])
            if ok:
                print(f"[Settings] ✅ Prioridad de Helena aplicada con ctypes: {level} pid={pid}")
                return f"CONFIRMED: prioridad de Helena aplicada a {level}. PID={pid}."
            err = ctypes.get_last_error()
            return f"FAILED: Windows no permitió cambiar la prioridad. Código de error: {err}."
    except Exception as e:
        print(f"[Settings] ❌ Error aplicando prioridad: {e}")
        return f"FAILED: no pude cambiar la prioridad de Helena: {e}"

def get_process_priority() -> str:
    try:
        import os
        pid = os.getpid()
        import psutil
        proc = psutil.Process(pid)
        return f"CONFIRMED: prioridad actual de Helena: {proc.nice()}. PID={pid}."
    except Exception as e:
        return f"FAILED: no pude leer la prioridad actual: {e}"

# ============================================================
# MAPA DE ACCIONES
# ============================================================

ACTION_MAP: dict[str, callable] = {
    "volume_up":           volume_up,
    "volume_down":         volume_down,
    "mute":                volume_mute,
    "unmute":              volume_mute,
    "toggle_mute":         volume_mute,
    "brightness_up":       brightness_up,
    "brightness_down":     brightness_down,
    "brightness_set":      brightness_set,
    "set_brightness":      brightness_set,
    "sleep_display":       sleep_display,
    "screen_off":          sleep_display,
    "pause_video":         pause_video,
    "play_pause":          pause_video,
    "close_app":           close_app_alt_f4,
    "close_app_alt_f4":    close_app_alt_f4,
    "cerrar_aplicacion":   close_app_alt_f4,
    "cerrar_ventana":      close_window,
    "close_window":        close_window,
    "full_screen":         full_screen,
    "fullscreen":          full_screen,
    "minimize":            minimize_window,
    "maximize":            maximize_window,
    "snap_left":           snap_left,
    "snap_right":          snap_right,
    "switch_window":       switch_window,
    "show_desktop":        show_desktop,
    "task_manager":        open_task_manager,
    "focus_search":        focus_search,
    "refresh_page":        refresh_page,
    "reload":              refresh_page,
    "close_tab":           close_tab,
    "new_tab":             new_tab,
    "next_tab":            next_tab,
    "prev_tab":            prev_tab,
    "go_back":             go_back,
    "go_forward":          go_forward,
    "zoom_in":             zoom_in,
    "zoom_out":            zoom_out,
    "zoom_reset":          zoom_reset,
    "find_on_page":        find_on_page,
    "scroll_up":           scroll_up,
    "scroll_down":         scroll_down,
    "scroll_top":          scroll_top,
    "scroll_bottom":       scroll_bottom,
    "page_up":             page_up,
    "page_down":           page_down,
    "copy":                copy,
    "paste":               paste,
    "cut":                 cut,
    "undo":                undo,
    "redo":                redo,
    "select_all":          select_all,
    "save":                save_file,
    "enter":               press_enter,
    "escape":              press_escape,
    "screenshot":          take_screenshot,
    "lock_screen":         lock_screen,
    "open_settings":       open_system_settings,
    "file_explorer":       open_file_explorer,
    "open_run":            open_run,
    "dark_mode":           dark_mode,
    "toggle_wifi":         toggle_wifi,
    "restart":             restart_computer,
    "reboot":              restart_computer,
    "reiniciar":           restart_computer,
    "shutdown":            shutdown_computer,
    "apagar":              shutdown_computer,
    "poweroff":            shutdown_computer,
    "cancel_shutdown":     cancel_shutdown,
}

_DANGEROUS_ACTIONS = set()


def _detect_action(description: str) -> dict:
    from or_client import client

    available = ", ".join(sorted(ACTION_MAP.keys())) + \
                ", volume_set, type_text, press_key, reload_n, close_app_by_name, priority_high, priority_normal, get_priority"

    prompt = f"""You are an intent detector for a computer control assistant.
The user issued a command (possibly in any language): "{description}"
Available actions: {available}
Return ONLY a valid JSON object: {{"action": "action_name", "value": null_or_value}}
Rules:
- For volume_set: value is an integer 0-100.
- For brightness_set: value is an integer 0-100. Use it when the user asks for monitor brightness/brillo.
- For type_text: value is the exact text to type.
- For press_key: value is the key name (e.g. "f5", "tab", "enter").
- For reload_n: value is an integer.
- For close_app_by_name: value is the application name (e.g. "WhatsApp", "Spotify").
- For apagar/shutdown/restart/reiniciar/cancel_shutdown: use the exact power action requested by the user.
- If user asks to give Helena more computer priority, optimize resources, reduce cuts by prioritizing the program, or set process priority, return {"action":"priority_high","value":"high"}.
- If user asks to restore normal priority, return {"action":"priority_normal","value":"normal"}.
- Return ONLY the JSON, no explanation, no markdown."""

    try:
        raw  = client.chat_json(prompt, system="Return only valid JSON. No extra text.")
        return raw
    except Exception as e:
        print(f"[Settings] Intent detection failed: {e}")
        return {"action": description.lower().replace(" ", "_"), "value": None}

def computer_settings(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params      = parameters or {}
    raw_action  = params.get("action", "").strip()
    description = params.get("description", "").strip()
    value       = params.get("value", None)

    if not raw_action and description:
        detected   = _detect_action(description)
        raw_action = detected.get("action", "")
        if value is None:
            value = detected.get("value")

    action = raw_action.lower().strip().replace(" ", "_").replace("-", "_")

    if not action:
        return "No action could be determined."

    print(f"[Settings] Action: {action}  Value: {value}  OS: {_OS}")
    if player:
        player.write_log(f"[Settings] {action}")

    if action in _DANGEROUS_ACTIONS:
        confirmed = str(params.get("confirmed", "")).lower()
        if confirmed not in ("yes", "true", "1", "confirm"):
            return (
                f"This will {action} the computer. "
                f"Please confirm by calling again with confirmed=yes."
            )

    if action in ("security_status", "defender_status", "antivirus_status", "threats", "threat_report"):
        try:
            from actions.system_control import system_control
            mapped = "threats" if action in ("threats", "threat_report") else "security_status"
            return system_control(parameters={"action": mapped}, player=player)
        except Exception as e:
            return f"FAILED: no pude consultar seguridad: {e}"

    # ========== PRIORIDAD DE HELENA / PERFORMANCE MODE ==========
    if action in ("priority_high", "set_priority_high", "high_priority", "performance_mode", "modo_performance", "prioridad_alta"):
        return set_process_priority("high")

    if action in ("priority_normal", "set_priority_normal", "normal_priority", "modo_normal", "prioridad_normal"):
        return set_process_priority("normal")

    if action in ("get_priority", "priority_status", "estado_prioridad", "prioridad_actual"):
        return get_process_priority()

    if action in ("brightness_set", "set_brightness", "brillo", "set_monitor_brightness"):
        try:
            return brightness_set(int(value or params.get("level", 50)))
        except Exception as e:
            return f"No pude ajustar el brillo: {e}"

    if action == "volume_set":
        try:
            requested = int(value if value is not None else params.get("level", 50))
            if requested < 0 or requested > 100:
                return "Volume range must be 0-100."
            return volume_set(requested)
        except Exception as e:
            return f"Could not set volume: {e}"

    if not _PYAUTOGUI:
        return "pyautogui is not installed. Run: pip install pyautogui"

    if action in ("type_text", "write_on_screen", "type", "write"):
        text = str(value or params.get("text", "")).strip()
        if not text:
            return "No text provided to type."
        enter_after = str(params.get("press_enter", "false")).lower() in ("true", "1", "yes")
        type_text(text, press_enter_after=enter_after)
        return f"Typed: {text[:80]}"

    if action == "press_key":
        key = str(value or params.get("key", "")).strip()
        if not key:
            return "No key specified."
        press_key(key)
        return f"Pressed: {key}"

    if action in ("reload_n", "refresh_n", "reload_page_n"):
        try:
            reload_page_n(int(value or 1))
            return f"Reloaded {value or 1} time(s)."
        except Exception as e:
            return f"Reload failed: {e}"

    # ========== CIERRE DE APLICACIONES ESPECÍFICAS ==========
    if action in ("close_app_by_name", "cerrar_app", "cerrar_programa", "close_app_specific", "cerrar_aplicacion_especifica"):
        app_name = str(value or params.get("app_name", "") or params.get("text", "")).strip()
        if not app_name:
            return "Especifica qué aplicación quieres cerrar (ej: 'cerrar WhatsApp')"
        return close_app_by_name(app_name)

    if action == "scroll_up":
        scroll_up(int(value or 500))
        return "Scrolled up."

    if action == "scroll_down":
        scroll_down(int(value or 500))
        return "Scrolled down."

    func = ACTION_MAP.get(action)
    if not func:
        return f"Unknown action: '{raw_action}'."

    try:
        if action in ("brightness_set", "set_brightness"):
            out = func(int(value or 50))
        else:
            out = func()
        if isinstance(out, str) and out.strip():
            return out
        return f"CONFIRMED: Done: {action}."
    except Exception as e:
        print(f"[Settings] Action failed ({action}): {e}")
        return f"FAILED: Action failed ({action}): {e}"
