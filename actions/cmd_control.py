# actions/cmd_control.py - Ejecución segura de comandos para HELENA

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()


def _open_with_default_app(path: Path) -> str:
    if not path.exists():
        return f"No encontré el archivo o carpeta: {path}"
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["cmd", "/c", "start", "", str(path)], shell=False)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return f"Abriendo: {path}"
    except Exception as exc:
        return f"No pude abrir {path}: {exc}"


def _run_command(command: str, timeout: int = 60, visible: bool = False) -> str:
    command = (command or "").strip()
    if not command:
        return "No se indicó ningún comando para ejecutar."

    blocked = ["format ", "del /f", "rmdir /s", "rm -rf", "shutdown", "cipher /w", "diskpart"]
    lowered = command.lower()
    if any(term in lowered for term in blocked):
        return "Comando bloqueado por seguridad."

    try:
        if visible and sys.platform.startswith("win"):
            subprocess.Popen(["cmd", "/k", command], cwd=str(BASE_DIR))
            return f"Comando abierto en una terminal visible: {command}"

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(BASE_DIR),
        )
        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        if result.returncode == 0:
            return output or "Comando ejecutado correctamente."
        return f"El comando terminó con error {result.returncode}: {error or output or command}"
    except subprocess.TimeoutExpired:
        return f"El comando superó el tiempo límite de {timeout} segundos."
    except Exception as exc:
        return f"No pude ejecutar el comando: {exc}"


def _task_to_command(task: str) -> str:
    """Convierte tareas simples del planner en comandos seguros."""
    text = (task or "").strip()
    low = text.lower()

    # Abrir archivos del escritorio con Bloc de notas / app por defecto.
    if "desktop" in low or "escritorio" in low:
        desktop = Path.home() / "Desktop"
        tokens = shlex.split(text.replace("\\", "/")) if text else []
        candidates = [tok for tok in tokens if "." in tok and not tok.startswith("-")]
        if candidates:
            return str(desktop / candidates[0])

    return text


def cmd_control(parameters: dict | None = None, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    task = (params.get("task") or params.get("command") or "").strip()
    visible = bool(params.get("visible", False))
    timeout = int(params.get("timeout", 60) or 60)

    if player:
        player.write_log(f"[Comandos] {task[:80]}")

    if not task:
        return "No se indicó ninguna tarea para cmd_control."

    translated = _task_to_command(task)
    possible_path = Path(translated).expanduser()
    if possible_path.exists():
        return _open_with_default_app(possible_path)

    return _run_command(translated, timeout=timeout, visible=visible)
