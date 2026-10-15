import subprocess
import sys
import json
import re
import time
import shutil
import shlex
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
API_CONFIG_PATH  = BASE_DIR / "config" / "api_keys.json"
PROJECTS_DIR     = Path.home() / "Desktop" / "HelenaProjects"
BACKUP_DIR       = BASE_DIR / "backups" / "dev_agent"
REPORT_DIR       = BASE_DIR / "reports"
MAX_FIX_ATTEMPTS = 5
MODEL_PLANNER    = "gemini-2.5-flash"
MODEL_WRITER     = "gemini-2.5-flash"
PROTECTED_NAMES  = {".env", "api_keys.json"}
PROTECTED_PATTERNS = ("token", "secret", "cookie", "session", "sesion", "sesiones", "whatsapp", "private_key", "id_rsa")

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _get_model(model_name: str):
    import google.generativeai as genai
    genai.configure(api_key=_get_api_key())
    return genai.GenerativeModel(model_name)


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\r?\n?", "", text)
    text = re.sub(r"\r?\n?```\s*$", "", text)
    return text.strip()


def _safe_project_name(project_name: str) -> str:
    name = re.sub(r"[^\w\-]", "_", project_name or "helena_project").strip("_")
    return name[:80] or "helena_project"


def _safe_project_path(project_name: str) -> Path:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    path = (PROJECTS_DIR / _safe_project_name(project_name)).resolve()
    root = PROJECTS_DIR.resolve()
    if not (path == root or root in path.parents):
        raise PermissionError(f"Unsafe project path blocked: {path}")
    return path


def _safe_relative_file(raw_path: str) -> Path:
    rel = Path((raw_path or "").replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or not rel.name:
        raise ValueError(f"Unsafe generated file path: {raw_path}")
    low = str(rel).lower()
    if rel.name.lower() in PROTECTED_NAMES or any(pattern in low for pattern in PROTECTED_PATTERNS):
        raise ValueError(f"Protected generated file path blocked: {raw_path}")
    return rel


def _receipt(task: str, status: str, files_changed=None, backups=None, validation: str = "", notes: str = "") -> str:
    lines = [
        "DEV AGENT RESULT",
        f"Task: {task}",
        f"Status: {status}",
        f"Files changed: {', '.join(files_changed or [])}",
        f"Backups: {', '.join(str(b) for b in (backups or []))}",
        f"Validation: {validation}",
        f"Notes: {notes}",
    ]
    return "\n".join(lines)


def _analyze_structure(project_dir: Path, max_files: int = 80) -> str:
    if not project_dir.exists():
        return f"Project path does not exist: {project_dir}"
    rows = []
    for path in project_dir.rglob("*"):
        if len(rows) >= max_files:
            rows.append("... truncated")
            break
        rel = path.relative_to(project_dir)
        low = str(rel).lower()
        if path.name.lower() in PROTECTED_NAMES or any(pattern in low for pattern in PROTECTED_PATTERNS):
            continue
        rows.append(f"{'[DIR]' if path.is_dir() else '[FILE]'} {rel}")
    return "\n".join(rows) if rows else "(empty project)"


def _validate_python_project(project_dir: Path) -> str:
    py_files = [p for p in project_dir.rglob("*.py") if "__pycache__" not in p.parts]
    if not py_files:
        return "No Python files to validate."
    command = [sys.executable, "-m", "py_compile"] + [str(p) for p in py_files[:100]]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, cwd=str(project_dir))
    status = "OK" if result.returncode == 0 else "FAILED"
    return f"{status}: py_compile {len(py_files[:100])} file(s)\n{(result.stderr or result.stdout or '').strip()}"


def _backup_existing_file(path: Path, project_dir: Path, label: str = "write") -> Path | None:
    if not path.exists() or not path.is_file():
        return None
    stamp = time.strftime("%Y%m%d_%H%M%S")
    rel_project = project_dir.name / path.resolve().relative_to(project_dir.resolve())
    backup_path = BACKUP_DIR / stamp / label / rel_project
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)
    return backup_path


def _is_rate_limit(error: Exception) -> bool:
    msg = str(error).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg


def _parse_traceback(output: str, project_files: list[str]) -> tuple[str | None, int | None]:

    pattern = re.compile(r'File ["\']([^"\']+\.py)["\'],\s+line\s+(\d+)', re.IGNORECASE)
    matches = pattern.findall(output)

    for raw_path, line_str in reversed(matches):
        raw_name = Path(raw_path).name
        for pf in project_files:
            if Path(pf).name == raw_name or pf == raw_path or raw_path.endswith(pf):
                return pf, int(line_str)

    return None, None


def _classify_error(output: str) -> str:

    low = output.lower()

    if any(x in low for x in ("no module named", "modulenotfounderror", "importerror")):
        return "dependency_error"

    if "syntaxerror" in low or "invalid syntax" in low:
        return "syntax_error"

    if "cannot import" in low or "importerror" in low:
        return "import_error"

    if any(x in low for x in (
        "traceback", "exception", "error:", "nameerror", "typeerror",
        "attributeerror", "valueerror", "keyerror", "indexerror",
        "zerodivisionerror", "filenotfounderror", "permissionerror",
    )):
        return "runtime_error"

    return "none"


def _has_error(output: str, run_command: str) -> bool:

    low = output.lower()

    if "timed out" in low:
        return False

    if not output.strip():
        return False

    error_type = _classify_error(output)
    return error_type != "none"

class RateLimitError(Exception):
    pass


def _plan_project(description: str, language: str) -> dict:
    model = _get_model(MODEL_PLANNER)

    prompt = f"""You are a senior software architect. Create a minimal, complete file plan for this project.

Language: {language}
Description: {description}

Return ONLY valid JSON — no markdown, no explanation:
{{
  "project_name": "snake_case_name",
  "entry_point": "main.py",
  "files": [
    {{
      "path": "main.py",
      "description": "Entry point — what it does and which modules it imports",
      "imports": ["utils.helpers", "core.engine"]
    }},
    {{
      "path": "utils/helpers.py",
      "description": "Helper utilities — what functions it exposes",
      "imports": []
    }}
  ],
  "run_command": "python main.py",
  "dependencies": ["requests"]
}}

Critical rules:
1. List files in DEPENDENCY ORDER — files with no imports come first, entry point comes last.
2. The "imports" field must list every other project module this file imports (dot-notation, e.g. "utils.helpers").
3. Keep it minimal — only files truly needed.
4. Entry point must be in the files list.
5. Use relative paths only (e.g. "utils/helpers.py", not absolute paths).
6. Standard library modules (os, sys, json, etc.) do NOT go in "dependencies".

JSON:"""

    try:
        response = model.generate_content(prompt)
        raw = _strip_fences(response.text)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Planner returned invalid JSON: {e}\nRaw: {response.text[:300]}")
    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise

def _write_file(
    file_info: dict,
    project_description: str,
    all_files: list[dict],
    language: str,
    project_dir: Path,
    already_written: dict[str, str],
) -> str:
    model = _get_model(MODEL_WRITER)

    file_path = str(_safe_relative_file(file_info["path"]))
    file_desc = file_info.get("description", "")
    file_imports = file_info.get("imports", [])

    file_list = "\n".join(
        f"  [{i+1}] {f['path']}: {f.get('description', '')}"
        for i, f in enumerate(all_files)
    )

    dependency_context = ""
    for dep_dotted in file_imports:
        dep_path = dep_dotted.replace(".", "/") + ".py"
        if dep_path in already_written:
            code_snippet = already_written[dep_path][:2000]
            dependency_context += f"\n\n--- {dep_path} (you must import from this) ---\n{code_snippet}"

    lang_rules = ""
    if language.lower() == "python":
        lang_rules = """
Python-specific rules:
- Use type hints for all function signatures.
- Add docstrings for all public functions and classes.
- Use if __name__ == "__main__": guard in the entry point.
- For relative imports within the project, use: from utils.helpers import foo  (match the project structure exactly).
- Do NOT use implicit relative imports (from . import ...) unless it's a proper package with __init__.py.
- If this is a package subdirectory, create __init__.py files where needed."""
    elif language.lower() in ("javascript", "typescript", "js", "ts"):
        lang_rules = """
JS/TS-specific rules:
- Use ES modules (import/export), not CommonJS (require).
- Add JSDoc comments for all exported functions.
- Handle promise rejections with try/catch in async functions."""

    prompt = f"""You are a senior {language} developer writing production-quality code for a real project.

Project goal: {project_description}

Complete project file structure (in dependency order):
{file_list}

{f"Dependencies this file must import from other project files:{dependency_context}" if dependency_context else ""}

Your task: Write the complete, working code for: {file_path}
Purpose of this file: {file_desc}
{f"This file imports from: {', '.join(file_imports)}" if file_imports else "This file has no project-internal imports."}

{lang_rules}

General rules:
- Output ONLY raw code. Absolutely no explanation, no markdown, no triple backticks.
- Write COMPLETE, RUNNABLE code — no placeholders, no "# TODO", no "pass" stubs.
- Every import must either be from the standard library, listed dependencies, or the project files shown above.
- Match import paths EXACTLY to the file paths in the project structure (e.g. if file is "utils/helpers.py", import as "from utils.helpers import ...").
- Use proper error handling (try/except) where I/O or network calls are made.
- The code must work correctly when the project entry point is run from the project root directory.

Code for {file_path}:"""

    try:
        response = model.generate_content(prompt)
        code = _strip_fences(response.text)

        full_path = project_dir / file_path
        _backup_existing_file(full_path, project_dir, label="write")
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(code, encoding="utf-8")

        print(f"[DevAgent] ✅ Written: {file_path} ({len(code)} chars)")
        return code

    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise

def _install_dependencies(dependencies: list[str], project_dir: Path) -> str:
    if not dependencies:
        return "No external dependencies."

    to_install = []
    for dep in dependencies:
        pkg_name = re.split(r"[>=<!]", dep)[0].strip()
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg_name],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            to_install.append(dep)
        else:
            print(f"[DevAgent] ✓ Already installed: {pkg_name}")

    if not to_install:
        return f"All dependencies already installed: {', '.join(dependencies)}"

    print(f"[DevAgent] 📦 Installing: {to_install}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"] + to_install,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=120, cwd=str(project_dir)
        )
        if result.returncode == 0:
            return f"Installed: {', '.join(to_install)}"
        return f"Install warning (non-fatal): {result.stderr[:200]}"
    except subprocess.TimeoutExpired:
        return "Dependency install timed out (non-fatal)."
    except Exception as e:
        return f"Install error (non-fatal): {e}"

def _open_vscode(project_dir: Path) -> bool:
    vscode_candidates = [
        "code",
        rf"C:\Users\{Path.home().name}\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd",
        r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
    ]
    for cmd in vscode_candidates:
        try:
            subprocess.Popen(
                [cmd, str(project_dir)],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.5)
            print(f"[DevAgent] 💻 VSCode opened: {project_dir}")
            return True
        except Exception:
            continue
    return False

def _run_project(run_command: str, project_dir: Path, timeout: int = 30) -> str:
    print(f"[DevAgent] 🚀 Running: {run_command}")
    try:
        if any(token in run_command for token in ("&&", "||", ";", "|", "`", "$(")):
            return f"Unsafe run command blocked: {run_command}"
        parts = shlex.split(run_command)
        if not parts:
            return "Empty run command."
        if parts[0].lower() == "python":
            parts[0] = sys.executable

        result = subprocess.run(
            parts,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout,
            cwd=str(project_dir)
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        combined_parts = []
        if stdout:
            combined_parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            combined_parts.append(f"STDERR:\n{stderr}")

        return "\n\n".join(combined_parts) if combined_parts else "Ran with no output."

    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s — long-running app (server/GUI) is likely working."
    except FileNotFoundError as e:
        return f"Command not found: {e}"
    except Exception as e:
        return f"Run error: {e}"

def _try_auto_install(error_output: str, project_dir: Path) -> bool:
    """ModuleNotFoundError varsa eksik paketi otomatik kurmaya çalışır."""
    pattern = re.compile(
        r"No module named ['\"]([a-zA-Z0-9_\-\.]+)['\"]", re.IGNORECASE
    )
    match = pattern.search(error_output)
    if not match:
        return False

    pkg = match.group(1).replace("_", "-").split(".")[0]
    print(f"[DevAgent] 🔧 Auto-installing missing package: {pkg}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=60, cwd=str(project_dir)
        )
        return result.returncode == 0
    except Exception:
        return False

def _fix_files(
    error_output: str,
    project_description: str,
    all_files: list[dict],
    file_codes: dict[str, str],
    language: str,
    project_dir: Path,
    entry_point: str,
) -> dict[str, str]:

    model = _get_model(MODEL_PLANNER)

    error_file, error_line = _parse_traceback(error_output, list(file_codes.keys()))
    error_type = _classify_error(error_output)

    files_to_fix: list[str] = []

    if error_file:
        files_to_fix.append(error_file)
        if error_type == "import_error":
            for fi in all_files:
                if error_file.replace("/", ".").replace(".py", "") in fi.get("imports", []):
                    p = fi["path"]
                    if p not in files_to_fix:
                        files_to_fix.append(p)
    else:
        files_to_fix.append(entry_point)

    updated_codes: dict[str, str] = {}

    for fix_path in files_to_fix:
        current_code = file_codes.get(fix_path, "")

        other_ctx = ""
        for fp, code in file_codes.items():
            if fp != fix_path and code:
                snippet = code[:1500] + ("..." if len(code) > 1500 else "")
                other_ctx += f"\n--- {fp} ---\n{snippet}\n"

        line_hint = f"\nError appears to be near line {error_line} in this file." if (
            error_line and fix_path == error_file
        ) else ""

        prompt = f"""You are an expert {language} debugger. Fix the broken file below.

Project goal: {project_description}

All project files:
{chr(10).join(f"  - {f['path']}: {f.get('description', '')}" for f in all_files)}

Other files for context (read-only — fix only the target file):
{other_ctx[:3500]}

File to fix: {fix_path}{line_hint}
Error type: {error_type}

Error output:
{error_output[:2500]}

Current (broken) code:
{current_code}

Rules:
- Output ONLY the complete fixed code. No explanation, no markdown, no backticks.
- Fix ALL errors visible in the error output.
- Keep all existing correct logic — do not remove working features.
- Ensure import paths match the actual project file structure exactly.
- Do NOT introduce new bugs or remove error handling.

Fixed code for {fix_path}:"""

        try:
            response = model.generate_content(prompt)
            fixed = _strip_fences(response.text)

            safe_fix_path = str(_safe_relative_file(fix_path))
            full_path = project_dir / safe_fix_path
            _backup_existing_file(full_path, project_dir, label="fix")
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(fixed, encoding="utf-8")

            updated_codes[safe_fix_path] = fixed
            print(f"[DevAgent] 🔧 Fixed: {fix_path}")

        except Exception as e:
            if _is_rate_limit(e):
                raise RateLimitError(str(e))
            print(f"[DevAgent] ⚠️ Could not fix {fix_path}: {e}")

    return updated_codes

def _build_project(
    description: str,
    language: str,
    project_name: str,
    timeout: int,
    allow_install: bool = False,
    open_editor: bool = False,
    max_files: int = 20,
    speak=None,
    player=None,
) -> str:

    def log(msg: str):
        print(f"[DevAgent] {msg}")
        if player:
            player.write_log(f"[DevAgent] {msg}")

    log("Planning project structure...")
    try:
        plan = _plan_project(description, language)
    except RateLimitError:
        msg = "Rate limit reached, . Please try again in a moment."
        if speak: speak(msg)
        return msg
    except ValueError as e:
        msg = f"Planning failed: {e}"
        if speak: speak(msg)
        return msg

    proj_name    = _safe_project_name(project_name or plan.get("project_name", "helena_project"))
    project_dir  = _safe_project_path(proj_name)
    project_dir.mkdir(parents=True, exist_ok=True)

    files        = plan.get("files", [])
    if len(files) > max_files:
        return _receipt(description, "FAILED", validation="", notes=f"Plan requested {len(files)} files; max_files={max_files}.")
    entry_point  = plan.get("entry_point", "main.py")
    run_command  = plan.get("run_command", f"python {entry_point}")
    dependencies = plan.get("dependencies", [])

    log(f"Project: {proj_name} | Files: {len(files)} | Entry: {entry_point}")

    def _dep_sort_key(fi: dict) -> int:
        return len(fi.get("imports", []))

    sorted_files = sorted(files, key=_dep_sort_key)

    file_codes: dict[str, str] = {}

    for file_info in sorted_files:
        try:
            file_path = str(_safe_relative_file(file_info.get("path", "")))
            file_info["path"] = file_path
        except ValueError as exc:
            log(str(exc))
            continue
        if not file_path:
            continue

        log(f"Writing {file_path}...")
        for attempt in range(2):
            try:
                code = _write_file(
                    file_info=file_info,
                    project_description=description,
                    all_files=files,
                    language=language,
                    project_dir=project_dir,
                    already_written=file_codes,
                )
                file_codes[file_path] = code
                time.sleep(0.4)
                break
            except RateLimitError:
                if attempt == 0:
                    log("Rate limit — waiting 20s...")
                    time.sleep(20)
                else:
                    log(f"Rate limit retry failed for {file_path}, skipping.")
            except Exception as e:
                log(f"Failed to write {file_path}: {e}")
                break

    if not file_codes:
        msg = "I could not write any project files, ."
        if speak: speak(msg)
        return msg

    if dependencies and allow_install:
        install_result = _install_dependencies(dependencies, project_dir)
        log(install_result)
    elif dependencies:
        log(f"Dependencies reported but not installed automatically: {', '.join(dependencies)}")

    if open_editor:
        _open_vscode(project_dir)

    last_output   = ""
    auto_installs = 0

    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        log(f"Running project (attempt {attempt}/{MAX_FIX_ATTEMPTS})...")
        last_output = _run_project(run_command, project_dir, timeout)
        log(f"Output preview: {last_output[:150]}")

        if not _has_error(last_output, run_command):
            msg = (
                f"Project '{proj_name}' is working, . "
                f"Built in {attempt} attempt{'s' if attempt > 1 else ''}. "
                f"Saved to: {project_dir}"
            )
            if speak: speak(msg)
            validation = _validate_python_project(project_dir) if language.lower() in ("python", "py") else "Run completed."
            return f"{_receipt(description, 'OK', files_changed=list(file_codes.keys()), validation=validation, notes=f'Saved to: {project_dir}')}\n\nOutput:\n{last_output}"

        if attempt == MAX_FIX_ATTEMPTS:
            break

        error_type = _classify_error(last_output)
        if allow_install and error_type == "dependency_error" and auto_installs < 3:
            installed = _try_auto_install(last_output, project_dir)
            if installed:
                auto_installs += 1
                log("Missing dependency installed, retrying...")
                time.sleep(1)
                continue

        log(f"Fixing errors (type: {error_type})...")
        try:
            updated = _fix_files(
                error_output=last_output,
                project_description=description,
                all_files=files,
                file_codes=file_codes,
                language=language,
                project_dir=project_dir,
                entry_point=entry_point,
            )
            file_codes.update(updated)
            time.sleep(1)
        except RateLimitError:
            msg = "Rate limit reached during fix. Project saved, check it manually in VSCode."
            if speak: speak(msg)
            return msg
        except Exception as e:
            log(f"Fix step failed: {e}")

    msg = (
        f"I couldn't fully fix '{proj_name}' after {MAX_FIX_ATTEMPTS} attempts, . "
        f"Project is saved at {project_dir} — open it in VSCode and check manually."
    )
    if speak: speak(msg)
    validation = _validate_python_project(project_dir) if language.lower() in ("python", "py") else "Run failed."
    return f"{_receipt(description, 'PARTIAL', files_changed=list(file_codes.keys()), validation=validation, notes=msg)}\n\nLast error:\n{last_output[:600]}"


def dev_agent(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    p            = parameters or {}
    description  = p.get("description", "").strip()
    language     = p.get("language", "python").strip()
    project_name = p.get("project_name", "").strip()
    timeout      = int(p.get("timeout", 30))
    mode         = str(p.get("mode", "apply")).lower().strip()
    max_files    = int(p.get("max_files", 20))
    allow_install = bool(p.get("allow_install", False))
    open_editor  = bool(p.get("open_editor", False))

    if not description:
        return "Please describe the project you want me to build, ."

    project_dir = _safe_project_path(project_name or _safe_project_name(description[:40]))

    if mode == "dry_run":
        structure = _analyze_structure(project_dir) if project_dir.exists() else "(new project)"
        return _receipt(description, "DRY_RUN", validation="Not executed.", notes=f"Project dir: {project_dir}\nStructure:\n{structure}\nLimits: max_files={max_files}, no secrets, backup before overwrite.")

    if mode == "validate":
        validation = _validate_python_project(project_dir)
        return _receipt(description, "VALIDATED", validation=validation, notes=f"Project dir: {project_dir}")

    if mode not in ("apply", "build"):
        return _receipt(description, "FAILED", validation="", notes="Unknown mode. Use dry_run, apply, or validate.")

    return _build_project(
        description  = description,
        language     = language,
        project_name = project_name,
        timeout      = timeout,
        allow_install = allow_install,
        open_editor  = open_editor,
        max_files    = max_files,
        speak        = speak,
        player       = player,
    )
