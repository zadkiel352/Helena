# actions/code_helper.py
# AI-powered code assistant — writes, edits, explains, runs, builds, debugs, and optimizes code.
#
# Actions:
#   write        → Describe what you want, Gemini writes it, saves to file
#   edit         → Read existing file, apply natural language change
#   explain      → Explain what a piece of code or file does
#   run          → Execute a script file, return output
#   build        → Write → Run → Fix loop (max 3 attempts), speaks when done
#   screen_debug → Screenshot al, ekrandaki kodu/hatayı Gemini ile analiz et ve düzelt
#   optimize     → Mevcut kodu Gemini ile optimize et (performans, okunabilirlik, best practices)
#   auto         → (default) Intent auto-detected from context

import subprocess
import sys
import json
import re
import time
import difflib
import shutil
import hashlib
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR           = get_base_dir()
API_CONFIG_PATH    = BASE_DIR / "config" / "api_keys.json"
DESKTOP            = Path.home() / "Desktop"
DOCUMENTS          = Path.home() / "Documents"
PROJECTS_DIR       = DESKTOP / "HelenaProjects"
BACKUP_DIR         = BASE_DIR / "backups" / "code_lab"
AUDIT_DIR          = BASE_DIR / "logs"
LAST_RECEIPT_PATH  = AUDIT_DIR / "code_lab_last_operation.json"
AUDIT_LOG_PATH     = AUDIT_DIR / "code_lab_audit.log"
MAX_BUILD_ATTEMPTS = 3
GEMINI_MODEL       = "gemini-2.5-flash"
MAX_READ_CHARS     = 120_000
MAX_EDIT_CHARS     = 80_000
SAFE_RUN_TIMEOUT   = 60
PROTECTED_NAMES    = {".env", "api_keys.json"}
PROTECTED_PATTERNS = ("token", "secret", "cookie", "session", "sesion", "sesiones", "whatsapp", "private_key", "id_rsa")
SELF_EDIT_HINTS    = ("helena", "asistente", "self", "auto", "autonoma", "autónoma", "desarroll")


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _get_gemini(model: str = GEMINI_MODEL):
    import google.generativeai as genai
    genai.configure(api_key=_get_api_key())
    return genai.GenerativeModel(model)


def _clean_code(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _allowed_roots() -> tuple[Path, ...]:
    roots = [BASE_DIR, DESKTOP, DOCUMENTS, PROJECTS_DIR]
    return tuple(root.resolve() for root in roots if root.exists() or root == PROJECTS_DIR)


def _safe_resolve(raw_path: str, default_root: Path = BASE_DIR) -> Path:
    raw = (raw_path or "").strip().strip('"')
    if not raw:
        raise ValueError("No file path provided.")
    shortcuts = {
        "desktop": DESKTOP,
        "documents": DOCUMENTS,
        "projects": PROJECTS_DIR,
        "proyectos": PROJECTS_DIR,
        "helena": BASE_DIR,
    }
    path = shortcuts.get(raw.lower(), Path(raw).expanduser())
    if not path.is_absolute():
        path = default_root / path
    resolved = path.resolve()
    if not any(resolved == root or root in resolved.parents for root in _allowed_roots()):
        allowed = ", ".join(str(root) for root in _allowed_roots())
        raise PermissionError(f"Path outside CODE LAB safe roots: {resolved}. Allowed roots: {allowed}")
    return resolved


def _is_self_project_path(path: Path) -> bool:
    base = BASE_DIR.resolve()
    resolved = path.resolve()
    return resolved == base or base in resolved.parents


def _self_edit_requested(description: str, allow_self_edit: bool) -> bool:
    if allow_self_edit:
        return True
    low = (description or "").lower()
    return any(hint in low for hint in SELF_EDIT_HINTS)


def _guard_write(path: Path, description: str = "", allow_self_edit: bool = False) -> None:
    low_name = path.name.lower()
    low_path = str(path).lower()
    if low_name in PROTECTED_NAMES or any(pattern in low_path for pattern in PROTECTED_PATTERNS):
        raise PermissionError(f"Protected file blocked: {path.name}")
    if _is_self_project_path(path) and not _self_edit_requested(description, allow_self_edit):
        raise PermissionError(
            "Self-edit blocked for stability. Use allow_self_edit=true only when Leo explicitly asks Helena to modify herself."
        )


def _backup_file(path: Path, label: str = "edit") -> Path | None:
    if not path.exists() or not path.is_file():
        return None
    stamp = time.strftime("%Y%m%d_%H%M%S")
    try:
        rel = path.resolve().relative_to(BASE_DIR.resolve())
    except ValueError:
        rel = Path(path.name)
    backup_path = BACKUP_DIR / stamp / label / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)
    return backup_path


def _file_sha256(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _parse_saved_status(status: str) -> tuple[str, str]:
    saved = ""
    backup = ""
    for line in str(status or "").splitlines():
        if line.startswith("Saved to:"):
            saved = line.split(":", 1)[1].strip()
        elif line.startswith("Backup:"):
            backup = line.split(":", 1)[1].strip()
    return saved, backup


def _write_receipt(action: str, status: str, path: Path | str | None = None, details: dict | None = None) -> str:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    p = Path(path) if path else None
    exists = bool(p and p.exists())
    receipt = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "status": status,
        "file": str(p) if p else "",
        "exists": exists,
        "size_bytes": p.stat().st_size if exists else 0,
        "sha256": _file_sha256(p) if exists else "",
        "details": details or {},
    }
    LAST_RECEIPT_PATH.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    return str(LAST_RECEIPT_PATH)


def _format_receipt(action: str, status: str, path: Path | str | None = None, details: dict | None = None) -> str:
    receipt_path = _write_receipt(action, status, path, details)
    p = Path(path) if path else None
    exists = bool(p and p.exists())
    lines = [
        "CODE LAB RESULT",
        f"Action: {action}",
        f"Status: {status}",
    ]
    if p:
        lines.append(f"File: {p}")
        lines.append(f"File exists now: {'yes' if exists else 'no'}")
        if exists:
            lines.append(f"Size: {p.stat().st_size} bytes")
            lines.append(f"SHA256: {_file_sha256(p)[:16]}...")
    for key, value in (details or {}).items():
        if value not in ("", None, [], {}):
            lines.append(f"{key}: {value}")
    lines.append(f"Audit receipt: {receipt_path}")
    return "\n".join(lines)


def _format_code_helper_receipt(
    action: str,
    status: str,
    path: Path | str | None = None,
    backup: str = "",
    notes: str = "",
    details: dict | None = None,
) -> str:
    _write_receipt(action, status, path, {**(details or {}), "backup": backup, "notes": notes})
    p = Path(path) if path else None
    lines = [
        "CODE HELPER RESULT",
        f"Action: {action}",
        f"Status: {status}",
        f"File: {p or ''}",
        f"Backup: {backup}",
        f"Notes: {notes}",
    ]
    for key, value in (details or {}).items():
        if value not in ("", None, [], {}):
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _diff_preview(before: str, after: str, filename: str, max_lines: int = 80) -> str:
    diff = list(difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"{filename}.before",
        tofile=f"{filename}.after",
        lineterm="",
    ))
    if len(diff) > max_lines:
        diff = diff[:max_lines] + [f"... diff truncated ({len(diff) - max_lines} more lines)"]
    return "\n".join(diff) if diff else "No textual changes."


def _resolve_save_path(output_path: str, language: str) -> Path:
    ext_map = {
        "python": ".py", "py": ".py",
        "javascript": ".js", "js": ".js",
        "typescript": ".ts", "ts": ".ts",
        "html": ".html", "css": ".css",
        "java": ".java", "cpp": ".cpp", "c": ".c",
        "bash": ".sh", "shell": ".sh", "powershell": ".ps1",
        "sql": ".sql", "json": ".json", "rust": ".rs", "go": ".go",
    }
    if output_path:
        return _safe_resolve(output_path, default_root=PROJECTS_DIR)
    ext = ext_map.get((language or "python").lower(), ".py")
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    return PROJECTS_DIR / f"helena_code{ext}"


def _read_file(file_path: str) -> tuple[str, str]:
    if not file_path:
        return "", "No file path provided."
    try:
        p = _safe_resolve(file_path)
    except Exception as e:
        return "", str(e)
    if not p.exists():
        return "", f"File not found: {file_path}"
    try:
        if p.stat().st_size > MAX_READ_CHARS * 4:
            return "", f"File too large for CODE LAB safe read: {p} ({p.stat().st_size} bytes)"
        return p.read_text(encoding="utf-8", errors="replace")[:MAX_READ_CHARS], ""
    except Exception as e:
        return "", f"Could not read file: {e}"


def _save_file(path: Path, content: str, description: str = "", allow_self_edit: bool = False, make_backup: bool = True) -> str:
    try:
        path = _safe_resolve(str(path), default_root=PROJECTS_DIR)
        _guard_write(path, description=description, allow_self_edit=allow_self_edit)
        backup_path = _backup_file(path) if make_backup else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if backup_path:
            return f"Saved to: {path}\nBackup: {backup_path}"
        return f"Saved to: {path}"
    except Exception as e:
        return f"Could not save: {e}"


def _preview(code: str, lines: int = 10) -> str:
    all_lines = code.splitlines()
    preview   = "\n".join(all_lines[:lines])
    suffix    = f"\n... ({len(all_lines) - lines} more lines)" if len(all_lines) > lines else ""
    return preview + suffix


def _sync_code_lab(player, path: Path, code: str) -> None:
    if not player:
        return
    try:
        if hasattr(player, "set_code_file"):
            player.set_code_file(str(path), code)
        elif hasattr(player, "_set_code_all"):
            player._set_code_all(code)
    except Exception as exc:
        print(f"[Código] ⚠️ No pude sincronizar CODE LAB: {exc}")


def _has_error(output: str) -> bool:
    error_signals = ["error", "exception", "traceback", "syntaxerror",
                     "nameerror", "typeerror", "stderr", "failed", "crash"]
    return any(s in output.lower() for s in error_signals)


def _take_screenshot() -> Path | None:
    try:
        import pyautogui
        screenshot_path = Path.home() / "Desktop" / f"helena_debug_{int(time.time())}.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(str(screenshot_path))
        print(f"[Código] 📸 Screenshot: {screenshot_path}")
        return screenshot_path
    except Exception as e:
        print(f"[Código] ⚠️ Screenshot failed: {e}")
        return None


def _image_to_base64(path: Path) -> str:
    import base64
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _detect_intent(description: str, file_path: str, code: str) -> str:
    desc = (description or "").lower()

    screen_kw = ["ekrandaki", "screen", "ekranda", "bu hatayı", "why am i getting",
                 "neden hata", "what's wrong", "ne yanlış", "screenshot", "görüntü"]
    if any(k in desc for k in screen_kw):
        return "screen_debug"

    # Optimize keywords
    optimize_kw = ["optimize", "optimiza", "optimizar", "refactor", "refactoriza", "refactorizar",
                   "clean up", "limpia", "mejora", "mejorar", "improve", "temizle",
                   "iyileştir", "daha iyi", "make it better", "hızlandır"]
    if any(k in desc for k in optimize_kw) and (code or file_path):
        return "optimize"

    if file_path:
        p = Path(file_path)
        edit_kw  = ["edit", "edita", "editar", "update", "actualiza", "actualizar",
                    "modify", "modifica", "modificar", "change", "cambia", "cambiar",
                    "add", "agrega", "agregar", "remove", "quita", "quitar",
                    "refactor", "fix", "arregla", "arreglar", "corrige", "corregir",
                    "rename", "renombra", "replace", "reemplaza", "reemplazar",
                    "remplaza", "remplazar", "düzenle", "değiştir"]
        run_kw   = ["run", "ejecuta", "ejecutar", "execute", "launch", "start", "proba", "probar", "çalıştır"]
        build_kw = ["build", "construi", "construir", "make it work", "try", "attempt"]

        if p.exists() and any(k in desc for k in edit_kw):
            return "edit"
        if p.exists() and any(k in desc for k in run_kw):
            return "run"
        if any(k in desc for k in build_kw):
            return "build"
        if p.exists():
            return "explain"

    explain_kw = ["explain", "explica", "explicar", "what does", "describe",
                  "analiza", "analizar", "analyze", "açıkla", "ne yapıyor"]
    if any(k in desc for k in explain_kw) and (code or file_path):
        return "explain"

    build_kw = ["build", "construi", "construir", "make it work", "try and", "attempt"]
    if any(k in desc for k in build_kw):
        return "build"

    return "write"

def _write(description: str, language: str, output_path: str, player=None, allow_self_edit: bool = False) -> tuple[str, Path]:
    lang  = language or "python"
    model = _get_gemini()

    prompt = f"""You are an expert {lang} developer.
Write clean, working, well-commented {lang} code for the description below.

Rules:
- Output ONLY the code. No explanation, no markdown, no backticks.
- Add helpful inline comments.
- Handle errors and edge cases properly.
- Use modern best practices.

Description: {description}

Code:"""

    response = model.generate_content(prompt)
    code     = _clean_code(response.text)
    path     = _resolve_save_path(output_path, lang)
    status   = _save_file(path, code, description=description, allow_self_edit=allow_self_edit)
    if status.startswith("Could not save"):
        raise RuntimeError(status)
    return code, path


def _fix_code(code: str, error_output: str, description: str) -> str:
    model  = _get_gemini()
    prompt = f"""You are an expert debugger.
The code below failed with the following error. Fix it.
Return ONLY the corrected code — no explanation, no markdown, no backticks.

Original goal: {description}

Error:
{error_output[:2000]}

Broken code:
{code}

Fixed code:"""

    response = model.generate_content(prompt)
    return _clean_code(response.text)


def _safe_args(args: list | tuple | None) -> list[str]:
    clean = []
    for arg in args or []:
        text = str(arg)
        if any(token in text for token in ("&&", "||", ";", "|", "`", "$(")):
            raise ValueError(f"Unsafe argument blocked: {text}")
        clean.append(text)
    return clean


def _execute_file(path: Path, args: list, timeout: int) -> dict:
    started = time.time()
    try:
        path = _safe_resolve(str(path))
        args = _safe_args(args)
    except Exception as e:
        return {"exit_code": 1, "stdout": "", "stderr": str(e), "duration": 0.0, "command": ""}
    if not path.exists() or not path.is_file():
        return {"exit_code": 1, "stdout": "", "stderr": f"File not found: {path}", "duration": 0.0, "command": ""}
    if path.name.lower() in PROTECTED_NAMES:
        return {"exit_code": 1, "stdout": "", "stderr": f"Protected file cannot be executed: {path.name}", "duration": 0.0, "command": ""}
    timeout = max(1, min(int(timeout or 30), SAFE_RUN_TIMEOUT))
    interpreters = {
        ".py":  [sys.executable],
        ".js":  ["node"],
        ".ts":  ["ts-node"],
        ".sh":  ["bash"],
        ".ps1": ["powershell", "-File"],
        ".rb":  ["ruby"],
        ".php": ["php"],
    }
    interp = interpreters.get(path.suffix.lower())
    if not interp:
        return {"exit_code": 1, "stdout": "", "stderr": f"No interpreter for {path.suffix}.", "duration": 0.0, "command": ""}

    try:
        command = interp + [str(path)] + (args or [])
        result = subprocess.run(
            command,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(path.parent)
        )
        return {
            "exit_code": result.returncode,
            "stdout": (result.stdout or "").strip(),
            "stderr": (result.stderr or "").strip(),
            "duration": round(time.time() - started, 3),
            "command": " ".join(command),
        }

    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "stdout": "", "stderr": f"Timed out after {timeout}s.", "duration": round(time.time() - started, 3), "command": ""}
    except FileNotFoundError:
        return {"exit_code": 1, "stdout": "", "stderr": f"Interpreter not found: {interp[0]}.", "duration": round(time.time() - started, 3), "command": ""}
    except Exception as e:
        return {"exit_code": 1, "stdout": "", "stderr": f"Execution error: {e}", "duration": round(time.time() - started, 3), "command": ""}


def _run_file(path: Path, args: list, timeout: int) -> str:
    result = _execute_file(path, args, timeout)
    parts = [
        f"exit_code: {result['exit_code']}",
        f"duration: {result['duration']}s",
    ]
    if result.get("stdout"):
        parts.append(f"stdout:\n{result['stdout']}")
    if result.get("stderr"):
        parts.append(f"stderr:\n{result['stderr']}")
    return "\n\n".join(parts)


def _build(description, language, output_path, args, timeout, speak=None, player=None, allow_self_edit: bool = False) -> str:
    if not description:
        return "Please describe what you want me to build, ."

    if player:
        player.write_log("[Código] Build started...")

    lang = language or "python"

    try:
        code, path = _write(description, lang, output_path, player, allow_self_edit=allow_self_edit)
        print(f"[Código] ✅ Written: {path}")
    except Exception as e:
        msg = f"Could not write initial code: {e}"
        receipt = _format_receipt("build", "FAILED", None, {"error": msg})
        if player:
            player.write_log(receipt)
        if speak: speak(msg)
        return f"{receipt}\n{msg}"

    last_output = ""
    for attempt in range(1, MAX_BUILD_ATTEMPTS + 1):
        print(f"[Código] 🔄 Attempt {attempt}/{MAX_BUILD_ATTEMPTS}")
        if player:
            player.write_log(f"[Código] Attempt {attempt}...")

        last_output = _run_file(path, args, timeout)

        if not _has_error(last_output):
            receipt = _format_receipt("build", "SAVED_AND_RAN_OK", path, {"attempts": attempt})
            if player:
                player.write_log(receipt)
            msg = f"Build complete. Saved to {path} and ran after {attempt} attempt{'s' if attempt > 1 else ''}."
            if speak: speak("Build completo. Codigo guardado y probado.")
            return f"{receipt}\n\n{msg}\n\nOutput:\n{last_output}"

        print(f"[Código] ⚠️ Error on attempt {attempt}, fixing...")
        if player:
            player.write_log(f"[Código] Fixing (attempt {attempt})...")

        try:
            code = _fix_code(code, last_output, description)
            status = _save_file(path, code, description=description, allow_self_edit=allow_self_edit)
            if status.startswith("Could not save"):
                receipt = _format_receipt("build", "FAILED", path, {"error": status, "attempt": attempt})
                if player:
                    player.write_log(receipt)
                return f"{receipt}\n{status}"
        except Exception as e:
            msg = f"Could not fix code on attempt {attempt}: {e}"
            receipt = _format_receipt("build", "FAILED", path, {"error": msg, "attempt": attempt})
            if player:
                player.write_log(receipt)
            if speak: speak(msg)
            return f"{receipt}\n{msg}"

    msg = (
        f"I was unable to build a working version after {MAX_BUILD_ATTEMPTS} attempts, . "
        f"The last error was: {last_output[:200]}"
    )
    receipt = _format_receipt("build", "SAVED_BUT_RUN_FAILED", path, {"last_error": last_output[:500]})
    if player:
        player.write_log(receipt)
    if speak: speak(msg)
    return f"{receipt}\n\n{msg}\n\nLast code saved to: {path}"

def _write_action(description, language, output_path, player, allow_self_edit: bool = False) -> str:
    if not description:
        return "Please describe what you want me to write, ."
    if player:
        player.write_log("[Código] Writing code...")
    try:
        code, path = _write(description, language, output_path, player, allow_self_edit=allow_self_edit)
        _sync_code_lab(player, path, code)
        print(f"[Código] ✅ Written: {path}")
        receipt = _format_receipt("write", "SAVED", path, {"language": language or "python", "lines": len(code.splitlines())})
        if player:
            player.write_log(receipt)
        return f"{receipt}\n\nPreview:\n{_preview(code)}"
    except Exception as e:
        receipt = _format_receipt("write", "FAILED", None, {"error": str(e)})
        if player:
            player.write_log(receipt)
        return f"{receipt}\nCould not generate code: {e}"


def _edit_action(file_path, instruction, player, allow_self_edit: bool = False, dry_run: bool = False) -> str:
    if not file_path:
        return "Please provide a file path to edit, ."
    if not instruction:
        return "Please describe what change to make, ."

    content, err = _read_file(file_path)
    if err:
        return err
    if len(content) > MAX_EDIT_CHARS:
        return f"File too large for safe AI edit: {file_path} ({len(content)} chars)."

    if player:
        player.write_log("[Código] Editing file...")

    model  = _get_gemini()
    prompt = f"""You are an expert code editor.
Apply the following change to the code below.
Return ONLY the complete updated code — no explanation, no markdown, no backticks.

Change: {instruction}

Original code:
{content}

Updated code:"""

    try:
        response = model.generate_content(prompt)
        edited   = _clean_code(response.text)
    except Exception as e:
        return f"Could not edit code: {e}"

    try:
        target_path = _safe_resolve(file_path)
        _guard_write(target_path, description=instruction, allow_self_edit=allow_self_edit)
    except Exception as e:
        return str(e)

    diff = _diff_preview(content, edited, target_path.name)
    changed = content != edited
    if dry_run:
        _sync_code_lab(player, target_path, edited)
        receipt = _format_receipt("edit", "DRY_RUN_NO_FILE_CHANGED", target_path, {"changed_preview": changed})
        if player:
            player.write_log(receipt)
        return f"{receipt}\n\nDiff:\n{diff}"

    status = _save_file(target_path, edited, description=instruction, allow_self_edit=allow_self_edit)
    if status.startswith("Could not save"):
        receipt = _format_receipt("edit", "FAILED", target_path, {"error": status})
        if player:
            player.write_log(receipt)
        return f"{receipt}\n{status}"
    _sync_code_lab(player, target_path, edited)
    print(f"[Código] ✅ Edited: {file_path}")
    _, backup_path = _parse_saved_status(status)
    receipt = _format_receipt("edit", "SAVED", target_path, {"changed": changed, "backup": backup_path})
    if player:
        player.write_log(receipt)
    return f"{receipt}\n\nDiff:\n{diff}\n\nPreview:\n{_preview(edited)}"


def _explain_action(file_path, code, player) -> str:
    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide code or a file path to explain, ."

    if player:
        player.write_log("[Código] Analyzing code...")

    model  = _get_gemini()
    prompt = f"""Explain what this code does in simple, clear language.
Focus on: what it does, how it works, and any important details.
Be concise — 3 to 6 sentences maximum.

Code:
{code[:4000]}

Explanation:"""

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Could not explain code: {e}"


def _run_action(file_path, args, timeout, player) -> str:
    if not file_path:
        return "Please provide a file path to run, ."
    try:
        p = _safe_resolve(file_path)
    except Exception as e:
        return str(e)
    if not p.exists():
        return f"File not found: {file_path}"
    if player:
        player.write_log(f"[Código] Running {p.name}...")
    result = _execute_file(p, args, timeout)
    receipt = _format_code_helper_receipt("execute", "EXECUTED", p, details=result)
    if player:
        player.write_log(receipt)
    return (
        f"{receipt}\n\n"
        f"exit_code: {result['exit_code']}\n"
        f"stdout:\n{result['stdout']}\n\n"
        f"stderr:\n{result['stderr']}\n"
        f"duration: {result['duration']}s"
    )


def _build_existing_action(file_path: str, timeout: int, player=None) -> str:
    if not file_path:
        return _format_code_helper_receipt("build", "FAILED", notes="No file_path provided for validation build.")
    try:
        p = _safe_resolve(file_path)
    except Exception as e:
        return _format_code_helper_receipt("build", "FAILED", file_path, notes=str(e))
    if not p.exists() or not p.is_file():
        return _format_code_helper_receipt("build", "FAILED", p, notes="File not found.")

    suffix = p.suffix.lower()
    if suffix == ".py":
        command = [sys.executable, "-m", "py_compile", str(p)]
        project_type = "Python"
    elif suffix in (".js", ".mjs", ".cjs"):
        command = ["node", "--check", str(p)]
        project_type = "Node"
    elif suffix == ".java":
        command = ["javac", str(p)]
        project_type = "Java"
    else:
        return _format_code_helper_receipt("build", "FAILED", p, notes=f"No safe build command for {suffix}.")

    started = time.time()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, min(int(timeout or 30), SAFE_RUN_TIMEOUT)),
            cwd=str(p.parent),
        )
        status = "OK" if result.returncode == 0 else "FAILED"
        details = {
            "project_type": project_type,
            "command": " ".join(command),
            "exit_code": result.returncode,
            "stdout": (result.stdout or "").strip(),
            "stderr": (result.stderr or "").strip(),
            "duration": round(time.time() - started, 3),
        }
        receipt = _format_code_helper_receipt("build", status, p, notes="No dependencies were installed.", details=details)
        if player:
            player.write_log(receipt)
        return receipt
    except Exception as e:
        return _format_code_helper_receipt("build", "FAILED", p, notes=str(e), details={"command": " ".join(command)})


def _agent_task_action(parameters: dict, player=None, speak=None) -> str:
    safe_params = dict(parameters or {})
    safe_params.setdefault("mode", "dry_run")
    safe_params.setdefault("max_files", 5)
    safe_params.setdefault("allow_install", False)
    safe_params["no_secrets"] = True
    try:
        from actions.dev_agent import dev_agent
        return dev_agent(parameters=safe_params, player=player, speak=speak)
    except Exception as e:
        return _format_code_helper_receipt("agent_task", "FAILED", notes=f"Delegation failed: {e}")


def _open_in_lab_action(file_path, player) -> str:
    if not file_path:
        return "Please provide a file path to open in CODE LAB."
    try:
        p = _safe_resolve(file_path)
    except Exception as e:
        return str(e)
    if not p.exists():
        return f"File not found: {file_path}"
    if not p.is_file():
        return f"Not a file: {file_path}"
    if player and hasattr(player, "open_code_file"):
        player.open_code_file(str(p))
        receipt = _format_receipt("open_in_lab", "OPENED_NO_FILE_CHANGED", p)
        if player:
            player.write_log(receipt)
        return f"{receipt}\nOpened in CODE LAB: {p}"
    return "CODE LAB is not available in the current UI."


def _optimize_action(file_path, code, language, output_path, player, allow_self_edit: bool = False, dry_run: bool = False) -> str:

    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide code or a file path to optimize, ."

    if player:
        player.write_log("[Código] Optimizing code...")

    lang  = language or "python"
    model = _get_gemini()

    prompt = f"""You are an expert {lang} developer and code reviewer.
Optimize the following code for:
1. Performance — eliminate unnecessary operations, use efficient data structures
2. Readability — clear variable names, proper formatting, logical structure
3. Best practices — modern {lang} patterns, error handling, type hints if applicable
4. Remove dead code, redundant comments, and unnecessary complexity

Return ONLY the optimized code — no explanation, no markdown, no backticks.

Original code:
{code[:6000]}

Optimized code:"""

    try:
        response  = model.generate_content(prompt)
        optimized = _clean_code(response.text)
    except Exception as e:
        return f"Could not optimize code: {e}"

    # Kaydet
    if file_path:
        try:
            save_path = _safe_resolve(file_path)
        except Exception as e:
            return str(e)
    else:
        save_path = _resolve_save_path(output_path, lang)

    diff_preview = _diff_preview(code, optimized, save_path.name)
    changed = code != optimized
    if dry_run:
        _sync_code_lab(player, save_path, optimized)
        receipt = _format_receipt("optimize", "DRY_RUN_NO_FILE_CHANGED", save_path, {"changed_preview": changed})
        if player:
            player.write_log(receipt)
        return f"{receipt}\nLines: {len(code.splitlines())} -> {len(optimized.splitlines())}\n\nDiff:\n{diff_preview}"

    status = _save_file(save_path, optimized, description="optimize", allow_self_edit=allow_self_edit)
    if status.startswith("Could not save"):
        receipt = _format_receipt("optimize", "FAILED", save_path, {"error": status})
        if player:
            player.write_log(receipt)
        return f"{receipt}\n{status}"
    _sync_code_lab(player, save_path, optimized)
    print(f"[Código] ✅ Optimized: {save_path}")

    original_lines  = len(code.splitlines())
    optimized_lines = len(optimized.splitlines())
    diff = original_lines - optimized_lines
    _, backup_path = _parse_saved_status(status)
    receipt = _format_receipt("optimize", "SAVED", save_path, {"changed": changed, "backup": backup_path})
    if player:
        player.write_log(receipt)

    return (
        f"{receipt}\n"
        f"Lines: {original_lines} → {optimized_lines} "
        f"({'−' if diff > 0 else '+'}{abs(diff)} lines)\n\n"
        f"Diff:\n{diff_preview}\n\nPreview:\n{_preview(optimized)}"
    )


def _screen_debug_action(description, file_path, player, speak=None) -> str:

    if player:
        player.write_log("[Código] Taking screenshot for analysis...")

    print("[Código] 📸 Capturing screen for debug...")


    screenshot_path = _take_screenshot()
    if not screenshot_path:
        return "Could not take screenshot, . Please make sure PyAutoGUI is installed."


    file_content = ""
    if file_path:
        file_content, err = _read_file(file_path)
        if err:
            print(f"[Código] ⚠️ Could not read file: {err}")

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=_get_api_key())

        image_bytes  = screenshot_path.read_bytes()
        image_base64 = _image_to_base64(screenshot_path)

        user_question = description or "What error or problem do you see on the screen? How can it be fixed?"

        context = ""
        if file_content:
            context = f"\n\nAdditionally, here is the related file content:\n```\n{file_content[:4000]}\n```"

        analysis_prompt = f"""You are an expert programmer and debugger analyzing a screenshot.

User's question: {user_question}{context}

Please:
1. Identify any errors, exceptions, or problems visible on the screen
2. Explain what is causing the problem in simple terms
3. Provide a concrete fix or solution
4. If there's code visible, show the corrected version

Be specific and actionable. If you see an error message, quote it exactly."""

        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            analysis_prompt,
        ]

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
        )

        analysis = response.text.strip()
        print(f"[Código] ✅ Screen analysis complete")

        try:
            screenshot_path.unlink()
        except Exception:
            pass

        if file_path and file_content:

            code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", analysis, re.DOTALL)
            if code_match:
                fixed_code = code_match.group(1).strip()
                save_path  = _safe_resolve(file_path)
                _save_file(save_path, fixed_code, description=description, allow_self_edit=True)
                analysis += f"\n\n✅ Fixed code has been saved to: {file_path}"
                print(f"[Código] ✅ Fixed code saved: {file_path}")

        return analysis

    except Exception as e:

        try:
            screenshot_path.unlink()
        except Exception:
            pass
        return f"Screen analysis failed: {e}"


def code_helper(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None
) -> str:
    """
    Called from main.py.

    parameters:
        action      : write | edit | refactor | explain | run | execute | build | agent_task | screen_debug | optimize | open_in_lab | auto
        description : What the code should do / what change to make / what problem to analyze
        language    : Programming language (default: python)
        output_path : Where to save — user specifies full path or filename
        file_path   : Path to existing file (edit / explain / run / build / optimize)
        code        : Raw code string (explain/optimize without a file)
        args        : CLI argument list for run/build
        timeout     : Execution timeout in seconds (default: 30)
        allow_self_edit : true only when Leo explicitly asks Helena to modify Helena/project code
        dry_run     : preview edit/optimize diff without saving
    """
    p           = parameters or {}
    action      = p.get("action", "auto").lower().strip()
    description = p.get("description", "").strip()
    language    = p.get("language", "python").strip()
    output_path = p.get("output_path", "").strip()
    file_path   = p.get("file_path", "").strip()
    code        = p.get("code", "").strip()
    args        = p.get("args", [])
    timeout     = int(p.get("timeout", 30))
    allow_self_edit = bool(p.get("allow_self_edit", False))
    dry_run     = bool(p.get("dry_run", False))

    if action == "auto":
        action = _detect_intent(description, file_path, code)
        print(f"[Código] 🤖 Auto-detected: {action}")

    aliases = {
        "refactor": "edit",
        "execute": "run",
        "agent": "agent_task",
    }
    original_action = action
    action = aliases.get(action, action)

    if action == "write":
        return _write_action(description, language, output_path, player, allow_self_edit=allow_self_edit)

    elif action == "edit":
        result = _edit_action(
            file_path,
            description or p.get("instruction", ""),
            player,
            allow_self_edit=allow_self_edit,
            dry_run=dry_run,
        )
        if original_action == "refactor":
            status = "DRY_RUN" if dry_run else ("FAILED" if "FAILED" in result or result.startswith(("Could not", "Path outside", "Self-edit")) else "SAVED")
            backup_match = re.search(r"backup:\s*(.+)", result, re.IGNORECASE)
            backup = backup_match.group(1).strip() if backup_match else ""
            return f"{_format_code_helper_receipt('refactor', status, file_path, backup=backup, notes='Diff included below.')}\n\n{result}"
        return result

    elif action == "explain":
        return _explain_action(file_path, code, player)

    elif action == "run":
        return _run_action(file_path, args, timeout, player)

    elif action == "open_in_lab":
        return _open_in_lab_action(file_path, player)

    elif action == "build":
        if file_path:
            return _build_existing_action(file_path, timeout, player)
        return _build(description, language, output_path, args, timeout, speak, player, allow_self_edit=allow_self_edit)

    elif action == "agent_task":
        return _agent_task_action({**p, "description": description or p.get("goal", "")}, player=player, speak=speak)

    elif action == "optimize":
        return _optimize_action(file_path, code, language, output_path, player, allow_self_edit=allow_self_edit, dry_run=dry_run)

    elif action == "screen_debug":
        return _screen_debug_action(description, file_path, player, speak)

    else:
        return f"Unknown action: '{action}'. Use write, edit/refactor, explain, run/execute, build, agent_task, optimize, open_in_lab, or screen_debug."
