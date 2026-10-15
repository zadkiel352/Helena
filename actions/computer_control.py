#computer_control.py
import io
import json
import re
import string
import subprocess
import sys
import time
import random
import os
from pathlib import Path

# Importar utilidades silenciosas
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE         = _base_dir()
_CONFIG_PATH  = _BASE / "config" / "api_keys.json"
_MEMORY_PATH  = _BASE / "memory" / "long_term.json"

def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _get_os() -> str:
    return _load_config().get("os_system", "windows").lower()

_SAFE_SCREENSHOT_ROOTS = (
    Path.home(),
)

def _safe_screenshot_path(requested: str | None) -> Path:
    fallback = Path.home() / "Desktop" / "helena_screenshot.png"
    if not requested:
        return fallback
    try:
        p = Path(requested).expanduser().resolve()
        for root in _SAFE_SCREENSHOT_ROOTS:
            if p.is_relative_to(root.resolve()):
                p.parent.mkdir(parents=True, exist_ok=True)
                return p
    except Exception:
        pass
    return fallback

def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")


def _normalize_action(action: str) -> str:
    """Normaliza acciones en español/inglés a nombres internos."""
    a = (action or "").lower().strip().replace(" ", "_").replace("-", "_")
    aliases = {
        "atajo": "hotkey", "shortcut": "hotkey", "press_shortcut": "hotkey", "presionar_atajo": "hotkey",
        "tecla": "press", "presionar": "press", "apretar": "press",
        "escribir": "type", "tipear": "type", "texto": "type",
        "pegar": "paste", "copiar": "copy",
        "cerrar_ventana": "close_window", "cerrar_ventana_activa": "close_window", "close_active_window": "close_window",
        "cerrar": "close_window", "alt_f4": "close_window",
        "minimizar": "minimize_window", "maximizar": "maximize_window", "restaurar": "restore_window",
        "mostrar_escritorio": "show_desktop", "desktop": "show_desktop",
        "cerrar_app": "close_app", "cerrar_aplicacion": "close_app", "close_application": "close_app",
        "matar_proceso": "kill_process", "taskkill": "kill_process",
        "listar_ventanas": "list_windows", "ventanas": "list_windows", "programas_en_ejecucion": "list_windows",
        "listar_programas": "list_windows", "list_programs": "list_windows", "running_programs": "list_windows",
        "cambiar_ventana": "switch_window", "alt_tab": "alt_tab", "siguiente_ventana": "alt_tab",
    }
    return aliases.get(a, a)


def _normalize_keys(raw) -> list[str]:
    if isinstance(raw, (list, tuple)):
        keys = [str(k).strip().lower() for k in raw if str(k).strip()]
    elif isinstance(raw, str):
        keys = [k.strip().lower() for k in re.split(r"[+ ,]+", raw) if k.strip()]
    else:
        keys = []
    key_aliases = {
        "control": "ctrl", "ctl": "ctrl", "cmd": "win", "windows": "win",
        "escape": "esc", "return": "enter", "intro": "enter",
        "suprimir": "delete", "borrar": "delete", "espacio": "space",
    }
    return [key_aliases.get(k, k) for k in keys]


def _close_window() -> str:
    _require_pyautogui()
    pyautogui.hotkey("alt", "f4")
    return "Ventana activa cerrada con Alt+F4."


def _minimize_window() -> str:
    _require_pyautogui()
    pyautogui.hotkey("win", "down")
    return "Ventana activa minimizada."


def _maximize_window() -> str:
    _require_pyautogui()
    pyautogui.hotkey("win", "up")
    return "Ventana activa maximizada."


def _show_desktop() -> str:
    _require_pyautogui()
    pyautogui.hotkey("win", "d")
    return "Escritorio mostrado."


def _close_app_by_name(app_name: str, force: bool = False) -> str:
    name = (app_name or "").strip()
    if not name:
        return "Necesito el nombre de la aplicación a cerrar."
    try:
        import psutil
        closed = []
        target = name.lower().replace(".exe", "")
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                clean = pname.replace(".exe", "")
                if target in clean or clean in target:
                    if force:
                        proc.kill()
                    else:
                        proc.terminate()
                    closed.append(pname)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if closed:
            return f"Cerré {len(closed)} proceso(s) de {name}: {', '.join(sorted(set(closed))[:5])}."
    except Exception as e:
        print(f"[ComputerControl] ⚠️ cierre por psutil falló: {e}")

    # Fallback Windows taskkill
    try:
        exe = name if name.lower().endswith(".exe") else f"{name}.exe"
        flag = "/F" if force else ""
        result = subprocess.run(["taskkill", "/IM", exe, flag], capture_output=True, text=True, shell=False)
        if result.returncode == 0:
            return f"Cerré {exe}."
        return f"No pude cerrar {name}: {result.stderr.strip() or result.stdout.strip()}"
    except Exception as e:
        return f"No pude cerrar {name}: {e}"

_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def _random_data(data_type: str) -> str:
    dt = data_type.lower().strip()

    if dt == "first_name":
        return random.choice(_FIRST_NAMES)

    if dt == "last_name":
        return random.choice(_LAST_NAMES)

    if dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

    if dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last  = random.choice(_LAST_NAMES).lower()
        num   = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"

    if dt == "username":
        return f"{random.choice(_FIRST_NAMES).lower()}{random.randint(100, 9999)}"

    if dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        raw   = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice("!@#$%")
            + "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(raw, len(raw)))

    if dt == "phone":
        return f"+1{random.randint(200,999)}{random.randint(1_000_000, 9_999_999)}"

    if dt == "birthday":
        y = random.randint(1980, 2000)
        m = random.randint(1, 12)
        d = random.randint(1, 28)
        return f"{m:02d}/{d:02d}/{y}"

    if dt == "address":
        num    = random.randint(100, 9999)
        street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
        return f"{num} {street}"

    if dt == "zip_code":
        return str(random.randint(10000, 99999))

    if dt == "city":
        return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])

    return f"random_{data_type}_{random.randint(1000, 9999)}"

def _user_profile() -> dict:
    """Read identity fields from long-term memory."""
    try:
        if _MEMORY_PATH.exists():
            data     = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
            identity = data.get("identity", {})
            return {k: v.get("value", "") for k, v in identity.items()}
    except Exception:
        pass
    return {}

def _type(text: str, interval: float = 0.03) -> str:
    _require_pyautogui()
    time.sleep(0.3)
    pyautogui.typewrite(text, interval=interval)
    return f"Typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _smart_type(text: str, clear_first: bool = True) -> str:
    _require_pyautogui()
    if clear_first:
        _clear_field()
        time.sleep(0.1)

    if len(text) > 20 and _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        return f"Smart-typed (clipboard): {text[:60]}{'…' if len(text) > 60 else ''}"

    pyautogui.typewrite(text, interval=0.04)
    return f"Smart-typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _click(x=None, y=None, button: str = "left", clicks: int = 1) -> str:
    _require_pyautogui()
    if x is not None and y is not None:
        pyautogui.click(x, y, button=button, clicks=clicks)
        return f"{'Double-c' if clicks == 2 else 'C'}licked ({x}, {y}) [{button}]"
    pyautogui.click(button=button, clicks=clicks)
    return f"Clicked at current position [{button}]"


def _hotkey(*keys) -> str:
    _require_pyautogui()
    pyautogui.hotkey(*keys)
    return f"Hotkey: {'+'.join(keys)}"


def _press(key: str) -> str:
    _require_pyautogui()
    pyautogui.press(key)
    return f"Pressed: {key}"


def _scroll(direction: str = "down", amount: int = 3) -> str:
    _require_pyautogui()
    vertical   = direction in ("up", "down")
    clicks     = amount if direction in ("up", "right") else -amount
    pyautogui.scroll(clicks) if vertical else pyautogui.hscroll(clicks)
    return f"Scrolled {direction} ×{amount}"


def _move(x: int, y: int, duration: float = 0.3) -> str:
    _require_pyautogui()
    pyautogui.moveTo(x, y, duration=duration)
    return f"Mouse → ({x}, {y})"


def _drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    _require_pyautogui()
    pyautogui.moveTo(x1, y1, duration=0.2)
    pyautogui.dragTo(x2, y2, duration=duration, button="left")
    return f"Dragged ({x1},{y1}) → ({x2},{y2})"


def _clipboard_get() -> str:
    if _PYPERCLIP:
        return pyperclip.paste()
    _hotkey("ctrl", "c")
    time.sleep(0.2)
    return "(copied — pyperclip unavailable for read)"


def _clipboard_paste(text: str) -> str:
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        _require_pyautogui()
        pyautogui.hotkey("ctrl", "v")
        return f"Pasted: {text[:60]}{'…' if len(text) > 60 else ''}"
    return "pyperclip not available"


def _screenshot(save_path: str | None = None) -> str:
    _require_pyautogui()
    path = _safe_screenshot_path(save_path)
    img  = pyautogui.screenshot()
    img.save(str(path))
    return f"Screenshot saved: {path}"


def _clear_field() -> str:
    _require_pyautogui()
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    return "Field cleared"

def _focus_window(title: str) -> str:
    os_name = _get_os()

    if os_name == "windows":
        try:
            script = f'(New-Object -ComObject WScript.Shell).AppActivate("{title}")'
            powershell_silent(script)
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (Windows) failed: {e}"

    if os_name == "mac":
        script = (
            f'tell application "System Events" to '
            f'set frontmost of (first process whose name contains "{title}") to true'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (macOS) failed: {e}"

    if os_name == "linux":
        try:
            result = subprocess.run(
                ["wmctrl", "-a", title],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                time.sleep(0.3)
                return f"Focused window: {title}"
        except FileNotFoundError:
            pass
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", title, "windowactivate"],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except FileNotFoundError:
            return "focus_window (Linux) requires wmctrl or xdotool"
        except Exception as e:
            return f"focus_window (Linux) failed: {e}"

    return f"focus_window: unknown OS '{os_name}'"

def _powershell_text(script: str, timeout: int = 10) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        out = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
        return result.returncode, out.strip()
    except Exception as exc:
        return 1, str(exc)

def _window_rows(limit: int = 80) -> tuple[str | None, list[dict]]:
    os_name = _get_os()
    if os_name != "windows":
        return "Listar ventanas/programas en ejecucion esta implementado para Windows.", []
    limit = max(1, min(80, int(limit or 30)))
    script = (
        "Get-Process | Where-Object { $_.MainWindowTitle } | "
        "Sort-Object ProcessName | "
        f"Select-Object -First {limit} ProcessName,Id,MainWindowTitle,MainWindowHandle | "
        "ConvertTo-Json -Compress"
    )
    code, out = _powershell_text(script)
    if code != 0:
        return f"No pude listar ventanas: {out}", []
    if not out:
        return None, []
    try:
        data = json.loads(out)
        rows = data if isinstance(data, list) else [data]
        return None, rows
    except Exception as exc:
        return f"No pude interpretar la lista de ventanas: {exc}. Salida: {out[:300]}", []

def _is_iconic(handle: int) -> bool | None:
    if _get_os() != "windows" or not handle:
        return None
    try:
        import ctypes
        return bool(ctypes.windll.user32.IsIconic(int(handle)))
    except Exception:
        return None

def _list_windows(limit: int = 30) -> str:
    err, rows = _window_rows(limit)
    if err:
        return err
    if not rows:
        return "No encontre ventanas visibles."
    lines = ["Ventanas visibles:"]
    for row in rows:
        handle = int(row.get("MainWindowHandle") or 0)
        minimized = _is_iconic(handle)
        state = "minimized" if minimized else "visible"
        lines.append(
            f"- title={row.get('MainWindowTitle')} | process={row.get('ProcessName')} | "
            f"PID={row.get('Id')} | handle={handle} | state={state}"
        )
    return "\n".join(lines)

def _alt_tab(steps: int = 1) -> str:
    _require_pyautogui()
    steps = max(1, min(20, int(steps or 1)))
    pyautogui.keyDown("alt")
    try:
        for _ in range(steps):
            pyautogui.press("tab")
            time.sleep(0.08)
    finally:
        pyautogui.keyUp("alt")
    return f"Cambie de ventana con Alt+Tab ({steps} paso(s))."

def _switch_window(title: str = "", steps: int = 1, process: str = "", pid: str = "", confirmed: bool = False) -> str:
    title = (title or "").strip()
    process = (process or "").strip().lower().replace(".exe", "")
    pid = str(pid or "").strip()
    if title or process or pid:
        err, rows = _window_rows(80)
        if err:
            return err
        matches = []
        for row in rows:
            row_title = str(row.get("MainWindowTitle") or "")
            row_process = str(row.get("ProcessName") or "").lower().replace(".exe", "")
            row_pid = str(row.get("Id") or "")
            if title and title.lower() not in row_title.lower():
                continue
            if process and process not in row_process:
                continue
            if pid and pid != row_pid:
                continue
            matches.append(row)
        if not matches:
            return "No encontre ventanas que coincidan."
        sensitive = {"taskmgr", "regedit", "powershell", "cmd", "windowssecurity", "mmc"}
        if len(matches) > 1:
            return "Coincidencia ambigua. Opciones:\n" + "\n".join(
                f"- title={m.get('MainWindowTitle')} | process={m.get('ProcessName')} | PID={m.get('Id')}"
                for m in matches[:10]
            )
        match = matches[0]
        proc = str(match.get("ProcessName") or "").lower()
        if proc in sensitive and not confirmed:
            return f"Ventana sensible ({proc}) requiere confirmed=yes."
        return _focus_window(str(match.get("MainWindowTitle") or title or proc))
    return _alt_tab(steps)

_CRITICAL_PROCESSES = {
    "system", "idle", "registry", "wininit", "winlogon", "csrss", "services", "lsass",
    "smss", "fontdrvhost", "dwm", "securityhealthservice",
}

def _kill_process_safe(name: str = "", pid: str = "", force: bool = False, confirmed: bool = False) -> str:
    try:
        import psutil
    except Exception as exc:
        return f"kill_process requiere psutil para operar de forma segura: {exc}"

    name = (name or "").strip().lower().replace(".exe", "")
    pid = str(pid or "").strip()
    current_pid = os.getpid()
    matches = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            info = proc.info
            proc_name = (info.get("name") or "").lower().replace(".exe", "")
            proc_pid = int(info.get("pid") or 0)
            cmdline = " ".join(info.get("cmdline") or []).lower()
            if pid and str(proc_pid) != pid:
                continue
            if name and name not in proc_name and name not in cmdline:
                continue
            if not pid and not name:
                continue
            matches.append((proc, proc_name, cmdline))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not matches:
        return f"No encontre procesos que coincidan con PID={pid or '-'} nombre={name or '-'}."
    if len(matches) > 1 and not pid:
        return "Coincidencia ambigua. Opciones:\n" + "\n".join(
            f"- PID={proc.pid} | name={proc_name}" for proc, proc_name, _ in matches[:12]
        )

    results = []
    for proc, proc_name, cmdline in matches:
        blocked_reason = ""
        if proc.pid == current_pid:
            blocked_reason = "proceso actual de Helena"
        elif proc_name in _CRITICAL_PROCESSES:
            blocked_reason = "proceso critico de Windows"
        elif proc_name == "explorer" and not confirmed:
            blocked_reason = "explorer.exe requiere confirmacion explicita"
        elif proc_name.startswith("python") and ("helena" in cmdline or proc.pid == current_pid) and not confirmed:
            blocked_reason = "python actual de Helena requiere confirmacion explicita"
        elif ("discord_bridge.py" in cmdline or "discord_music" in cmdline) and not confirmed:
            blocked_reason = "Discord bridge/music requiere confirmacion explicita"
        if blocked_reason:
            results.append(f"PID={proc.pid} name={proc_name} action=blocked error={blocked_reason}")
            continue
        try:
            if force:
                proc.kill()
                action = "kill"
            else:
                proc.terminate()
                action = "terminate"
            results.append(f"PID={proc.pid} name={proc_name} action={action} success=true")
        except Exception as exc:
            results.append(f"PID={proc.pid} name={proc_name} action=failed error={exc}")
    return "\n".join(results)

def _screen_find(description: str) -> tuple[int, int] | None:
    try:
        import base64
        from or_client import client

        _require_pyautogui()
        w, h  = pyautogui.size()
        img   = pyautogui.screenshot()
        buf   = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        text = client.vision(
            f"This is a screenshot of a {w}×{h} pixel screen. "
            f"Locate the UI element: '{description}'. "
            f"Reply ONLY with center coordinates as: x,y — or NOT_FOUND",
            image_b64=b64,
            mime="image/png",
        )

        if "NOT_FOUND" in text.upper():
            return None
        match = re.search(r"(\d+)\s*,\s*(\d+)", text)
        if match:
            return int(match.group(1)), int(match.group(2))
    except Exception as e:
        print(f"[ComputerControl] ⚠️ screen_find failed: {e}")
    return None

def computer_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Dispatch table for all computer control actions.

    parameters keys (all optional unless noted):
      action        : (required) one of the actions listed below
      text          : text to type or paste
      x, y          : screen coordinates
      button        : 'left' | 'right' (default: left)
      keys          : hotkey string, e.g. 'ctrl+c'
      key           : single key name, e.g. 'enter'
      direction     : 'up' | 'down' | 'left' | 'right'
      amount        : scroll amount (default: 3)
      seconds       : wait duration
      title         : window title fragment for focus_window
      description   : natural-language element description for screen_find/click
      type          : data type for random_data
      field         : memory field name for user_data
      clear_first   : bool, clear field before typing (default: true)
      path          : save path for screenshot (must be inside home dir)

    Actions:
      type          — type text at cursor
      smart_type    — clear field + type (clipboard-backed)
      click         — left click
      double_click  — double left click
      right_click   — right click
      move          — move mouse
      drag          — click-drag between two points
      hotkey        — key combination
      press         — single key
      scroll        — scroll the wheel
      copy          — read clipboard
      paste         — write + paste clipboard
      screenshot    — capture screen (safe path only)
      wait          — sleep N seconds
      clear_field   — select-all + delete
      focus_window  — bring window to foreground
      screen_find   — AI element finder (returns x,y)
      screen_click  — AI element finder + click
      random_data   — generate fake form data
      user_data     — pull real data from memory
    """
    params = parameters or {}
    action = _normalize_action(params.get("action", ""))

    if not action:
        return "No se indicó ninguna acción para computer_control."

    if player:
        player.write_log(f"[Computadora] {action}")

    print(f"[ComputerControl] action={action} params={params}")

    try:

        if action == "type":
            return _type(params.get("text", ""))

        if action == "smart_type":
            return _smart_type(
                params.get("text", ""),
                clear_first=params.get("clear_first", True),
            )

        if action in ("click", "left_click"):
            return _click(params.get("x"), params.get("y"), "left", 1)

        if action == "double_click":
            return _click(params.get("x"), params.get("y"), "left", 2)

        if action == "right_click":
            return _click(params.get("x"), params.get("y"), "right", 1)

        if action == "move":
            return _move(int(params.get("x", 0)), int(params.get("y", 0)))

        if action == "drag":
            return _drag(
                int(params.get("x1", 0)), int(params.get("y1", 0)),
                int(params.get("x2", 0)), int(params.get("y2", 0)),
            )

        if action == "hotkey":
            raw = params.get("keys", "") or params.get("key", "")
            keys = _normalize_keys(raw)
            if not keys:
                return "No recibí teclas para el atajo."
            return _hotkey(*keys)

        if action == "press":
            return _press(params.get("key", "enter"))

        if action == "scroll":
            return _scroll(
                direction=params.get("direction", "down"),
                amount=int(params.get("amount", 3)),
            )

        if action == "copy":
            return _clipboard_get()

        if action == "paste":
            return _clipboard_paste(params.get("text", ""))

        if action == "screenshot":
            return _screenshot(params.get("path"))

        if action == "screen_find":
            coords = _screen_find(params.get("description", ""))
            return f"{coords[0]},{coords[1]}" if coords else "NOT_FOUND"

        if action == "screen_click":
            desc   = params.get("description", "")
            coords = _screen_find(desc)
            if coords:
                time.sleep(0.2)
                _click(x=coords[0], y=coords[1])
                return f"Clicked '{desc}' at {coords}"
            return f"Element not found on screen: '{desc}'"

        if action == "wait":
            secs = float(params.get("seconds", 1.0))
            secs = min(secs, 30.0)
            time.sleep(secs)
            return f"Waited {secs}s"

        if action == "clear_field":
            return _clear_field()

        if action == "focus_window":
            return _focus_window(params.get("title", ""))

        if action == "list_windows":
            return _list_windows(int(params.get("limit", 30)))

        if action == "alt_tab":
            return _alt_tab(int(params.get("steps", params.get("count", 1))))

        if action == "switch_window":
            return _switch_window(
                title=params.get("title", "") or params.get("name", "") or params.get("text", ""),
                process=params.get("process", "") or params.get("app_name", ""),
                pid=str(params.get("pid", "")),
                steps=int(params.get("steps", params.get("count", 1))),
                confirmed=str(params.get("confirmed", "")).lower() in ("yes", "true", "1", "confirm"),
            )

        if action == "close_window":
            return _close_window()

        if action == "minimize_window":
            return _minimize_window()

        if action == "maximize_window":
            return _maximize_window()

        if action == "show_desktop":
            return _show_desktop()

        if action == "kill_process":
            return _kill_process_safe(
                name=params.get("app_name") or params.get("name") or params.get("process") or params.get("description") or params.get("text") or "",
                pid=str(params.get("pid", "")),
                force=bool(params.get("force")),
                confirmed=str(params.get("confirmed", "")).lower() in ("yes", "true", "1", "confirm"),
            )

        if action == "close_app":
            app_name = params.get("app_name") or params.get("name") or params.get("description") or params.get("text") or ""
            return _close_app_by_name(app_name, force=bool(params.get("force")))

        if action == "random_data":
            dt     = params.get("type", "name")
            result = _random_data(dt)
            print(f"[ComputerControl] random {dt} -> {result}")
            return result

        if action == "user_data":
            field   = params.get("field", "name")
            profile = _user_profile()
            value   = profile.get(field, "")
            if not value:
                value = _random_data(field)
                print(f"[ComputerControl] No '{field}' in memory, using random: {value}")
            return value

        return f"Acción desconocida: '{action}'"

    except Exception as e:
        print(f"[ComputerControl] ERROR {action}: {e}")
        return f"computer_control '{action}' failed: {e}"
