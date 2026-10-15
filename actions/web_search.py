# web_search.py - HELENA PATCH V21
# Busqueda web robusta sin depender de ddgs ni OpenRouter.
# Motivo: ddgs puede romperse si subprocess.Popen fue parcheado globalmente,
# y OpenRouter no debe bloquear una busqueda simple si un modelo falla.

from __future__ import annotations

import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


SEARCH_TIMEOUT = 12


def _read_config() -> dict[str, Any]:
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _get_api_key() -> str:
    return str(_read_config().get("gemini_api_key", "")).strip()


def _strip_tags(text: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_duck_url(url: str) -> str:
    url = html.unescape(url or "").strip()
    if not url:
        return ""

    # DDG HTML suele envolver URLs asi: /l/?kh=-1&uddg=https%3A%2F%2F...
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") or url.startswith("/l/"):
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            return qs["uddg"][0]

    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://duckduckgo.com" + url
    return url


def _http_get(url: str, params: dict[str, str] | None = None, timeout: int = SEARCH_TIMEOUT) -> str:
    if params:
        query = urllib.parse.urlencode(params)
        url = url + ("&" if "?" in url else "?") + query

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def _parse_ddg_html(page: str, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

    # Formato clasico de html.duckduckgo.com
    blocks = re.findall(r'(?is)<div[^>]+class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*</div>', page)
    if not blocks:
        # Fallback mas permisivo por si cambia el HTML.
        blocks = re.findall(r'(?is)<a[^>]+class="[^"]*result__a[^"]*"[^>]*>.*?</a>.*?(?=<a[^>]+class="[^"]*result__a|$)', page)

    for block in blocks:
        link_match = re.search(r'(?is)<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
        if not link_match:
            continue

        url = _normalize_duck_url(link_match.group(1))
        title = _strip_tags(link_match.group(2))

        snippet = ""
        snip_match = re.search(r'(?is)<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block)
        if not snip_match:
            snip_match = re.search(r'(?is)<div[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</div>', block)
        if snip_match:
            snippet = _strip_tags(snip_match.group(1))

        if title and url and not any(r.get("url") == url for r in results):
            results.append({"title": title, "snippet": snippet, "url": url})
        if len(results) >= max_results:
            break

    # Formato lite.duckduckgo.com, como respaldo.
    if not results:
        anchors = re.findall(r'(?is)<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page)
        for href, label in anchors:
            title = _strip_tags(label)
            url = _normalize_duck_url(href)
            if not title or not url:
                continue
            if "duckduckgo.com" in url and "uddg=" not in url:
                continue
            if title.lower() in {"next", "next page", "siguiente"}:
                continue
            if not any(r.get("url") == url for r in results):
                results.append({"title": title, "snippet": "", "url": url})
            if len(results) >= max_results:
                break

    return results


def _ddg_html_search(query: str, max_results: int = 6) -> list[dict[str, str]]:
    # No usamos el paquete ddgs porque en HELENA el parche de subprocess puede romperlo.
    page = _http_get("https://html.duckduckgo.com/html/", {"q": query}, timeout=SEARCH_TIMEOUT)
    results = _parse_ddg_html(page, max_results=max_results)
    if results:
        return results

    # Segundo intento: version lite.
    page = _http_get("https://lite.duckduckgo.com/lite/", {"q": query}, timeout=SEARCH_TIMEOUT)
    return _parse_ddg_html(page, max_results=max_results)


def _gemini_search(query: str) -> str:
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("No hay gemini_api_key configurada.")

    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=(
            "Busca en la web y responde en español, con datos concretos y enlaces cuando sea útil.\n\n"
            f"Consulta: {query}"
        ),
        config={"tools": [{"google_search": {}}]},
    )

    text = ""
    try:
        for part in response.candidates[0].content.parts:
            if getattr(part, "text", None):
                text += part.text
    except Exception:
        text = str(response)

    text = text.strip()
    if not text:
        raise ValueError("Gemini devolvió una respuesta vacía.")
    return text


def _format_results(query: str, results: list[dict[str, str]]) -> str:
    if not results:
        return f"No encontré resultados para: {query}"

    lines: list[str] = [f"Resultados de búsqueda para: {query}", ""]

    # Recordatorio sano para letras/canciones: Helena puede buscar enlaces, no pegar letras completas.
    q_lower = query.lower()
    if any(word in q_lower for word in ("letra", "lyrics", "cancion", "canción")):
        lines.append("Nota: puedo ayudarte a encontrar la letra y resumir la canción, pero no conviene pegar una letra completa por copyright.")
        lines.append("")

    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        snippet = r.get("snippet", "").strip()
        url = r.get("url", "").strip()
        lines.append(f"{i}. {title or 'Resultado'}")
        if snippet:
            lines.append(f"   {snippet}")
        if url:
            lines.append(f"   {url}")
        lines.append("")
    return "\n".join(lines).strip()


def _compare(items: list[str], aspect: str) -> str:
    all_results: dict[str, list[dict[str, str]]] = {}
    for item in items:
        q = f"{item} {aspect}".strip()
        try:
            all_results[item] = _ddg_html_search(q, max_results=3)
        except Exception as e:
            print(f"[WebSearch] ⚠️ DDG compare failed for {item}: {e}")
            all_results[item] = []

    lines = [f"Comparación — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:3]:
            if r.get("title"):
                lines.append(f"  • {r['title']}")
            if r.get("snippet"):
                lines.append(f"    {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines).strip()


def web_search(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    query = str(params.get("query", "")).strip()
    mode = str(params.get("mode", "search")).lower().strip()
    items = params.get("items", []) or []
    aspect = str(params.get("aspect", "general")).strip() or "general"

    if isinstance(items, str):
        items = [items]

    if not query and not items:
        return "Decime qué querés buscar."

    if items and mode != "compare":
        mode = "compare"

    if player:
        try:
            player.write_log(f"[Búsqueda] {query or ', '.join(items)}")
        except Exception:
            pass

    print(f"[WebSearch] 🔍 Query: {query!r}  Mode: {mode}")

    if mode == "compare":
        print("[WebSearch] 🔎 Modo comparación con buscador directo.")
        return _compare([str(i) for i in items], aspect)

    # 1) Busqueda directa gratis y sin OpenRouter.
    try:
        results = _ddg_html_search(query, max_results=6)
        print(f"[WebSearch] ✅ DDG HTML OK: {len(results)} resultado(s).")
        if results:
            return _format_results(query, results)
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG HTML failed: {type(e).__name__}: {e}")

    # 2) Respaldo con Gemini Google Search si DDG falla.
    try:
        result = _gemini_search(query)
        print("[WebSearch] ✅ Gemini Google Search OK.")
        return result
    except Exception as e:
        print(f"[WebSearch] ❌ Gemini Google Search failed: {type(e).__name__}: {e}")

    return (
        "No pude realizar la búsqueda ahora. "
        "El buscador directo falló y el respaldo de Gemini Search tampoco respondió."
    )
