from __future__ import annotations

import shutil
import re
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Collection
from pathlib import Path


_HTTP_URL_PATTERN = re.compile(r"""https?://[^\s<>"']+""", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,!?;:"


def is_conversation_line(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return text.strip().lower().startswith(
        ("tú:", "tu:", "leo:", "leito:", "you:", "usuario:", "helena:")
    )


def find_http_url_spans(text: str) -> list[tuple[int, int, str]]:
    """Return URL text ranges while leaving sentence punctuation outside links."""
    spans = []
    for match in _HTTP_URL_PATTERN.finditer(text):
        url = match.group(0)
        while url and url[-1] in _TRAILING_URL_PUNCTUATION:
            url = url[:-1]
        for closing, opening in ((")", "("), ("]", "["), ("}", "{")):
            while url.endswith(closing) and url.count(closing) > url.count(opening):
                url = url[:-1]
        if url:
            spans.append((match.start(), match.start() + len(url), url))
    return spans


def execute_code(
    language: str,
    code: str,
    run_hidden: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    """Run supported CODE LAB languages without depending on the Qt interface."""
    try:
        if language == "PYTHON":
            with tempfile.TemporaryDirectory() as temp_dir:
                source = Path(temp_dir) / "main.py"
                source.write_text(code, encoding="utf-8")
                result = run_hidden(
                    [sys.executable, str(source)],
                    capture_output=True,
                    text=True,
                    timeout=6,
                )
                return _execution_output(result)

        if language == "JAVA":
            if not shutil.which("javac") or not shutil.which("java"):
                return "ERROR > Java no está disponible. Instalá JDK y agregá javac/java al PATH."
            with tempfile.TemporaryDirectory() as temp_dir:
                source = Path(temp_dir) / "Main.java"
                java_code = code
                if "class Main" not in java_code:
                    java_code = (
                        "public class Main {\n    public static void main(String[] args) {\n"
                        + "\n".join("        " + line for line in java_code.splitlines())
                        + "\n    }\n}\n"
                    )
                source.write_text(java_code, encoding="utf-8")
                compilation = run_hidden(
                    ["javac", str(source)],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                if compilation.returncode != 0:
                    return "ERROR >\n" + (
                        compilation.stderr or compilation.stdout or "Error de compilación"
                    )
                result = run_hidden(
                    ["java", "Main"],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    timeout=6,
                )
                return _execution_output(result)

        if language == "JAVASCRIPT":
            if not shutil.which("node"):
                return "ERROR > Node.js no esta disponible en PATH."
            with tempfile.TemporaryDirectory() as temp_dir:
                source = Path(temp_dir) / "main.js"
                source.write_text(code, encoding="utf-8")
                result = run_hidden(
                    ["node", str(source)],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    timeout=6,
                )
                return _execution_output(result)

        return (
            f"> RUN preparado para {language}. En esta build ejecuta Python, Java y "
            "JavaScript; otros lenguajes quedan como editor/tutor."
        )
    except subprocess.TimeoutExpired:
        return "ERROR > tiempo de ejecución agotado. Puede haber un bucle infinito."
    except Exception as exc:
        return f"ERROR > {exc}"


def read_code_file(path: str | Path) -> str:
    source = Path(path).expanduser()
    return source.read_text(encoding="utf-8", errors="ignore") if source.exists() else ""


def _execution_output(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stdout or "") + (result.stderr or "")
    status = "SUCCESS >\n" if result.returncode == 0 else "ERROR >\n"
    return status + (output.strip() or "sin salida")


def build_project_summary(
    path: str | Path,
    skip_dirs: Collection[str],
    file_category: Callable[[Path], str],
    format_size: Callable[[int], str],
) -> str:
    """Create the existing compact CODE LAB project map outside the UI thread."""
    project_path = Path(path)
    if project_path.is_dir():
        return _scan_project_folder(project_path, skip_dirs, file_category)
    if project_path.suffix.lower() == ".zip":
        return _scan_project_zip(project_path, format_size)
    return (
        f"PROJECT FILE: {project_path.name}\n"
        f"SIZE: {format_size(project_path.stat().st_size)}\n"
        f"PATH: {project_path}"
    )


def _scan_project_folder(
    folder: Path,
    skip_dirs: Collection[str],
    file_category: Callable[[Path], str],
) -> str:
    lines = [f"PROJECT: {folder.name}", f"PATH: {folder}", ""]
    counts: dict[str, int] = {}
    shown = 0
    max_files = 90
    for path in sorted(
        folder.rglob("*"),
        key=lambda item: (len(item.relative_to(folder).parts), str(item).lower()),
    ):
        relative_parts = path.relative_to(folder).parts
        if any(part in skip_dirs for part in relative_parts):
            continue
        if path.is_dir():
            continue
        category = file_category(path)
        counts[category] = counts.get(category, 0) + 1
        if shown < max_files:
            depth = min(4, len(relative_parts) - 1)
            lines.append("  " * depth + "- " + str(path.relative_to(folder)))
            shown += 1
    lines.insert(
        2,
        "FILES: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        if counts
        else "FILES: 0",
    )
    if sum(counts.values()) > shown:
        lines.append(f"... +{sum(counts.values())-shown} archivos más")
    return "\n".join(lines)


def _scan_project_zip(path: Path, format_size: Callable[[int], str]) -> str:
    lines = [
        f"PROJECT ZIP: {path.name}",
        f"SIZE: {format_size(path.stat().st_size)}",
        f"PATH: {path}",
        "",
    ]
    with zipfile.ZipFile(path) as archive:
        files = [info for info in archive.infolist() if not info.is_dir()]
        lines.append(f"FILES: {len(files)}")
        for info in files[:90]:
            lines.append(f"- {info.filename}  ({format_size(info.file_size)})")
        if len(files) > 90:
            lines.append(f"... +{len(files)-90} archivos más")
    return "\n".join(lines)
