# silent_subprocess.py - Ejecuta comandos sin ventanas visibles
import subprocess
import sys
import os

# Configuración global para ocultar ventanas
STARTUP_INFO = subprocess.STARTUPINFO()
STARTUP_INFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
STARTUP_INFO.wShowWindow = subprocess.SW_HIDE

# Flags de creación para Windows
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

def run_silent(cmd, shell=True, capture_output=True, timeout=None):
    """Ejecuta un comando sin mostrar ventanas de consola"""
    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            capture_output=capture_output,
            timeout=timeout,
            startupinfo=STARTUP_INFO,
            creationflags=CREATE_NO_WINDOW
        )
        return result
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None

def popen_silent(cmd, shell=True):
    """Ejecuta un comando en segundo plano sin ventanas"""
    try:
        return subprocess.Popen(
            cmd,
            shell=shell,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=STARTUP_INFO,
            creationflags=CREATE_NO_WINDOW
        )
    except Exception:
        return None

def powershell_silent(command):
    """Ejecuta un comando de PowerShell sin ventanas"""
    return run_silent(f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{command}"')

# Parchear subprocess a nivel global para todas las llamadas
_original_popen = subprocess.Popen
_original_run = subprocess.run

def _patched_popen(*args, **kwargs):
    """Versión parcheada de subprocess.Popen que oculta ventanas"""
    if sys.platform == "win32":
        kwargs.setdefault('startupinfo', STARTUP_INFO)
        kwargs.setdefault('creationflags', CREATE_NO_WINDOW)
        # Redirigir stdout/stderr si no están especificados
        if 'stdout' not in kwargs:
            kwargs['stdout'] = subprocess.DEVNULL
        if 'stderr' not in kwargs:
            kwargs['stderr'] = subprocess.DEVNULL
    return _original_popen(*args, **kwargs)

def _patched_run(*args, **kwargs):
    """Versión parcheada de subprocess.run que oculta ventanas"""
    if sys.platform == "win32":
        kwargs.setdefault('startupinfo', STARTUP_INFO)
        kwargs.setdefault('creationflags', CREATE_NO_WINDOW)
    return _original_run(*args, **kwargs)

def enable_global_patch():
    """Activa el parche global solo cuando un llamador lo pide expresamente."""
    subprocess.Popen = _patched_popen
    subprocess.run = _patched_run
