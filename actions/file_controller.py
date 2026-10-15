# actions/file_controller.py
# Safe file management for Helena.

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

try:
    import send2trash
except Exception:
    send2trash = None


BASE_DIR = Path(__file__).resolve().parent.parent
TRASH_DIR = BASE_DIR / "trash"
PROTECTED_NAMES = {".env", "api_keys.json"}
PROTECTED_PATTERNS = (
    "token", "secret", "cookie", "session", "sesion", "sesiones",
    "whatsapp", "private_key", "id_rsa", "id_dsa", "id_ed25519",
)
MAX_READ_CHARS = 120_000


def _shortcut(raw: str) -> Path:
    shortcuts = {
        "helena": BASE_DIR,
        "desktop": Path.home() / "Desktop",
        "downloads": Path.home() / "Downloads",
        "documents": Path.home() / "Documents",
    }
    text = str(raw or "helena").strip().strip('"')
    return shortcuts.get(text.lower(), Path(text).expanduser())


def _allowed_roots() -> tuple[Path, ...]:
    roots = [BASE_DIR, Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "Downloads"]
    return tuple(root.resolve() for root in roots if root.exists() or root == BASE_DIR)


def _safe_path(raw: str) -> Path:
    target = _shortcut(raw).resolve()
    if not any(target == root or root in target.parents for root in _allowed_roots()):
        allowed = ", ".join(str(root) for root in _allowed_roots())
        raise PermissionError(f"Path blocked: {target}. Allowed roots: {allowed}")
    low_name = target.name.lower()
    low_path = str(target).lower()
    if low_name in PROTECTED_NAMES or any(pattern in low_path for pattern in PROTECTED_PATTERNS):
        raise PermissionError(f"Protected path blocked: {target}")
    windows_root = Path("C:/Windows").resolve()
    if target == windows_root or windows_root in target.parents:
        raise PermissionError(f"Windows system path blocked: {target}")
    return target


def _full_path(path: str, name: str = "") -> Path:
    base = _safe_path(path)
    if name:
        return _safe_path(str(base / name))
    return base


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def _receipt(action: str, status: str, path: Path | str = "", **details) -> str:
    lines = [
        "FILE CONTROLLER RESULT",
        f"Action: {action}",
        f"Status: {status}",
        f"Path: {path}",
    ]
    for key, value in details.items():
        if value not in ("", None, [], {}):
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _read_text(path: Path, max_chars: int = MAX_READ_CHARS) -> str:
    size = path.stat().st_size
    if size > max_chars * 4:
        return f"File too large for full read: {path} ({_format_size(size)})."
    raw = path.read_bytes()[: max_chars * 4]
    for enc in ("utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            text = raw.decode("utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n... (truncated, {len(text)} chars read)"
    return text


def list_files(path: str = "helena", show_hidden: bool = False) -> str:
    target = _safe_path(path)
    if not target.exists():
        return f"Path not found: {target}"
    if not target.is_dir():
        return f"Not a directory: {target}"
    items = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if not show_hidden and item.name.startswith("."):
            continue
        label = "[DIR]" if item.is_dir() else "[FILE]"
        size = "" if item.is_dir() else f" ({_format_size(item.stat().st_size)})"
        items.append(f"{label} {item.name}{size}")
    return f"Contents of {target} ({len(items)} items):\n" + ("\n".join(items) if items else "(empty)")


def read_file(path: str, max_chars: int = 3000) -> str:
    target = _safe_path(path)
    if not target.exists():
        return f"File not found: {target}"
    if not target.is_file():
        return f"Not a file: {target}"
    return _read_text(target, max_chars=max(1, min(int(max_chars or 3000), MAX_READ_CHARS)))


def write_file(path: str, content: str, append: bool = False, overwrite: bool = False) -> str:
    target = _safe_path(path)
    if target.exists() and not append and not overwrite:
        return _receipt("write", "FAILED", target, error="Target exists; pass overwrite=true.")
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with target.open(mode, encoding="utf-8") as f:
        f.write(content)
    return _receipt("write", "SAVED", target, mode=("append" if append else "write"))


def mkdir(path: str) -> str:
    target = _safe_path(path)
    target.mkdir(parents=True, exist_ok=True)
    return _receipt("mkdir", "OK", target)


def copy_file(source: str, destination: str, overwrite: bool = False, create_dirs: bool = True) -> str:
    src = _safe_path(source)
    dst = _safe_path(destination)
    if not src.exists():
        return _receipt("copy", "FAILED", src, error="Source not found.")
    if dst.exists() and dst.is_dir():
        dst = _safe_path(str(dst / src.name))
    if dst.exists() and not overwrite:
        return _receipt("copy", "FAILED", src, destination=dst, error="Destination exists; pass overwrite=true.")
    if create_dirs:
        dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=overwrite)
    else:
        shutil.copy2(src, dst)
    return _receipt("copy", "COPIED", src, destination=dst)


def move_file(source: str, destination: str, overwrite: bool = False, create_dirs: bool = True) -> str:
    src = _safe_path(source)
    dst = _safe_path(destination)
    if not src.exists():
        return _receipt("move", "FAILED", src, error="Source not found.")
    if dst.exists() and dst.is_dir():
        dst = _safe_path(str(dst / src.name))
    if dst.exists() and not overwrite:
        return _receipt("move", "FAILED", src, destination=dst, error="Destination exists; pass overwrite=true.")
    if create_dirs:
        dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return _receipt("move", "MOVED", src, destination=dst)


def rename_file(path: str, new_name: str, overwrite: bool = False) -> str:
    target = _safe_path(path)
    if not target.exists():
        return _receipt("rename", "FAILED", target, error="Source not found.")
    if not new_name or Path(new_name).name != new_name:
        return _receipt("rename", "FAILED", target, error="new_name must be a simple file name.")
    dst = _safe_path(str(target.parent / new_name))
    if dst.exists() and not overwrite:
        return _receipt("rename", "FAILED", target, destination=dst, error="Destination exists; pass overwrite=true.")
    target.rename(dst)
    return _receipt("rename", "RENAMED", target, destination=dst)


def delete_safe(path: str, confirm: bool = False, permanent: bool = False) -> str:
    target = _safe_path(path)
    if not target.exists():
        return _receipt("delete_safe", "FAILED", target, error="Not found.")
    if target.is_dir():
        count = sum(1 for _ in target.rglob("*"))
        if count > 100 and not confirm:
            return _receipt("delete_safe", "FAILED", target, error=f"Folder has {count} items; confirmation required.")
    if permanent:
        if not confirm:
            return _receipt("delete", "FAILED", target, error="Permanent delete requires confirm=true.")
        shutil.rmtree(target) if target.is_dir() else target.unlink()
        return _receipt("delete", "DELETED_PERMANENTLY", target)
    if send2trash:
        send2trash.send2trash(str(target))
        return _receipt("delete_safe", "MOVED_TO_RECYCLE_BIN", target)
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    dst = TRASH_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{target.name}"
    shutil.move(str(target), str(dst))
    return _receipt("delete_safe", "MOVED_TO_TRASH", target, destination=dst)


def find_files(name: str = "", extension: str = "", path: str = "helena", max_results: int = 20) -> str:
    root = _safe_path(path)
    if not root.exists() or not root.is_dir():
        return f"Search path not found: {root}"
    pattern = f"*{extension}" if extension else "*"
    results = []
    for item in root.rglob(pattern):
        try:
            _safe_path(str(item))
        except Exception:
            continue
        if item.is_file() and (not name or name.lower() in item.name.lower()):
            results.append(f"{item.name} ({_format_size(item.stat().st_size)}) - {item.parent}")
            if len(results) >= int(max_results or 20):
                break
    return "Found files:\n" + "\n".join(results) if results else "No files found."


def get_largest_files(path: str = "helena", count: int = 10) -> str:
    root = _safe_path(path)
    files = []
    for item in root.rglob("*"):
        if item.is_file():
            try:
                _safe_path(str(item))
                files.append((item.stat().st_size, item))
            except Exception:
                continue
    files.sort(reverse=True)
    return "\n".join(f"{_format_size(size):>10} {item}" for size, item in files[: int(count or 10)]) or "No files found."


def get_disk_usage(path: str = "helena") -> str:
    target = _safe_path(path)
    usage = shutil.disk_usage(target)
    return (
        f"Disk usage for {target}:\n"
        f"  Total : {_format_size(usage.total)}\n"
        f"  Used  : {_format_size(usage.used)} ({usage.used / usage.total * 100:.1f}%)\n"
        f"  Free  : {_format_size(usage.free)}"
    )


def get_file_info(path: str) -> str:
    target = _safe_path(path)
    if not target.exists():
        return f"Not found: {target}"
    stat = target.stat()
    mode = oct(stat.st_mode)[-3:]
    return "\n".join([
        f"Name: {target.name}",
        f"Type: {'Folder' if target.is_dir() else 'File'}",
        f"Size: {_format_size(stat.st_size)}",
        f"Location: {target.parent}",
        f"Created: {datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M')}",
        f"Modified: {datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')}",
        f"Permissions: {mode}",
    ])


def file_controller(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "")).lower().strip().replace("-", "_")
    action = {
        "create_file": "write",
        "create_folder": "mkdir",
        "delete": "delete_safe",
        "permissions": "info",
        "file_info": "info",
    }.get(action, action)
    path = params.get("path", "helena")
    name = params.get("name", "")
    content = params.get("content", "")
    overwrite = bool(params.get("overwrite", False))
    create_dirs = bool(params.get("create_dirs", True))

    try:
        full = str(_full_path(path, name))
        if action == "list":
            result = list_files(path, bool(params.get("show_hidden", False)))
        elif action == "read":
            result = read_file(full, int(params.get("max_chars", 3000)))
        elif action == "write":
            result = write_file(full, content, append=bool(params.get("append", False)), overwrite=overwrite)
        elif action == "mkdir":
            result = mkdir(full)
        elif action == "copy":
            result = copy_file(full, params.get("destination", ""), overwrite=overwrite, create_dirs=create_dirs)
        elif action == "move":
            result = move_file(full, params.get("destination", ""), overwrite=overwrite, create_dirs=create_dirs)
        elif action == "rename":
            result = rename_file(full, params.get("new_name", ""), overwrite=overwrite)
        elif action == "delete_safe":
            result = delete_safe(full, confirm=bool(params.get("confirm", False)), permanent=bool(params.get("permanent", False)))
        elif action == "find":
            result = find_files(name=name, extension=params.get("extension", ""), path=path, max_results=params.get("max_results", 20))
        elif action == "largest":
            result = get_largest_files(path=path, count=params.get("count", 10))
        elif action == "disk_usage":
            result = get_disk_usage(path)
        elif action == "info":
            result = get_file_info(full)
        else:
            result = f"Unknown action: '{action}'. Use list, read, write, copy, move, rename, delete_safe, mkdir, info, find, largest, disk_usage."
    except Exception as e:
        result = f"File controller error: {e}"

    if player:
        player.write_log(f"[file] {result[:120]}")
    return result
