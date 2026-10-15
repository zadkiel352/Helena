import json
import re
from datetime import datetime
from threading import Lock
from pathlib import Path
import sys
import time
from copy import deepcopy


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
_lock            = Lock()
MAX_VALUE_LENGTH = 700
MEMORY_MAX_CHARS = 9000

# V28: si OpenRouter/memoria remota falla, se desactiva temporalmente
# para no llenar el log ni trabar la conversación principal.
_REMOTE_MEMORY_DISABLED_UNTIL = 0.0
_REMOTE_MEMORY_FAILURES = 0
_REMOTE_MEMORY_LAST_LOG = 0.0
_REMOTE_MEMORY_COOLDOWN_SECONDS = 600


def _remote_memory_enabled() -> bool:
    """Memoria remota/OpenRouter opcional.

    Por seguridad y estabilidad, Helena usa memoria local por defecto.
    Para volver a activar extracción remota, poner en config/api_keys.json:
      "memory_remote_enabled": true
    o variable de entorno HELENA_ENABLE_REMOTE_MEMORY=1.
    """
    try:
        import os
        if str(os.getenv("HELENA_ENABLE_REMOTE_MEMORY", "")).strip().lower() in ("1", "true", "yes", "si", "sí"):
            return True
        cfg = BASE_DIR / "config" / "api_keys.json"
        if cfg.exists():
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return bool(data.get("memory_remote_enabled") or data.get("openrouter_memory_enabled"))
    except Exception:
        return False
    return False


def _empty_memory() -> dict:
    return {
        "identity": {},
        "preferences": {},
        "projects": {},
        "relationships": {},
        "wishes": {},
        "notes": {},
        "contact": {},
        "communication_rules": {},
        "conversation_context": {},
    }


def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()

    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data or not isinstance(data.get(key), dict):
                        data[key] = {}
                return data
            return _empty_memory()
        except Exception as e:
            print(f"[Memoria] ⚠️ Error al cargar: {e}")
            return _empty_memory()


def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


def _trim_to_limit(memory: dict) -> dict:
    serialized = json.dumps(memory, ensure_ascii=False)
    if len(serialized) <= MEMORY_MAX_CHARS:
        return memory

    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))

    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        print(f"[Memoria] 🗑️  Recortado {cat}/{key} (limit: {MEMORY_MAX_CHARS} chars)")

    return memory


def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return

    memory = _trim_to_limit(memory)

    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


def _truncate_json_value(value):
    """Recorta strings largos sin romper valores estructurados como dict/list."""
    if isinstance(value, str):
        if len(value) > MAX_VALUE_LENGTH:
            return value[:MAX_VALUE_LENGTH].rstrip() + "…"
        return value
    if isinstance(value, dict):
        return {str(k): _truncate_json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate_json_value(v) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _truncate_json_value(str(value))


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    today = datetime.now().strftime("%Y-%m-%d")

    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue

        # Si no es una entrada {"value": ...}, es una categoría/subcategoría.
        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
            continue

        if isinstance(value, dict) and "value" in value:
            raw_val = value.get("value")
            updated = value.get("updated") or today
        else:
            raw_val = value
            updated = today

        new_val = _truncate_json_value(raw_val)
        entry = {"value": new_val, "updated": updated}
        existing = target.get(key, {})

        if not isinstance(existing, dict) or existing.get("value") != new_val or existing.get("updated") != updated:
            target[key] = entry
            changed = True

    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()

    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)
        print(f"[Memoria] 💾 Guardado: {list(memory_update.keys())}")
    return memory


def should_extract_memory(user_text: str, helena_text: str, api_key: str = "") -> bool:
    global _REMOTE_MEMORY_DISABLED_UNTIL, _REMOTE_MEMORY_FAILURES, _REMOTE_MEMORY_LAST_LOG

    now = time.time()
    if not _remote_memory_enabled():
        # V28.4: memoria remota desactivada por defecto para que OpenRouter nunca bloquee a Helena.
        return False
    if now < _REMOTE_MEMORY_DISABLED_UNTIL:
        # Silencioso: la memoria local sigue funcionando, solo se saltea la extracción remota.
        return False

    try:
        from or_client import client

        combined = f"Usuario: {user_text[:300]}\nHelena: {helena_text[:1000]}"

        result = client.chat(
            "¿Esta conversación contiene algún dato estable y útil para recordar a largo plazo?\n"
            "Ejemplos válidos:\n"
            "- Datos personales confirmados por el usuario: nombre, ciudad, trabajo, idioma.\n"
            "- Preferencias, gustos, disgustos o forma preferida de comunicación.\n"
            "- Proyectos activos, objetivos, planes futuros o deseos.\n"
            "- Personas importantes mencionadas por el usuario.\n"
            "- Reglas útiles para asistir mejor al usuario.\n\n"
            "No guardes comandos de una sola vez, clima, resultados de búsqueda ni suposiciones.\n"
            "Responde solo SI o NO.\n\n"
            f"Conversación:\n{combined}",
            system="Eres un verificador de memoria. Responde solo SI o NO.",
            max_tokens=5,
            temperature=0.0,
        )
        _REMOTE_MEMORY_FAILURES = 0
        up = result.upper()
        return "SI" in up or "SÍ" in up or "YES" in up

    except Exception as e:
        _REMOTE_MEMORY_FAILURES += 1
        if _REMOTE_MEMORY_FAILURES >= 2:
            _REMOTE_MEMORY_DISABLED_UNTIL = now + _REMOTE_MEMORY_COOLDOWN_SECONDS

        # Loguear solo cada tanto para no spamear SYSTEM LOG.
        if now - _REMOTE_MEMORY_LAST_LOG > 60:
            _REMOTE_MEMORY_LAST_LOG = now
            if _REMOTE_MEMORY_DISABLED_UNTIL > now:
                mins = int((_REMOTE_MEMORY_DISABLED_UNTIL - now) // 60) + 1
                print(f"[Memoria] ⚠️ Memoria remota pausada {mins} min: {e}")
            else:
                print(f"[Memoria] ⚠️ Falló la verificación inicial: {e}")
        return False

def extract_memory(user_text: str, helena_text: str, api_key: str = "") -> dict:
    global _REMOTE_MEMORY_DISABLED_UNTIL, _REMOTE_MEMORY_FAILURES, _REMOTE_MEMORY_LAST_LOG
    now = time.time()
    if not _remote_memory_enabled():
        # V28.4: memoria remota desactivada por defecto para extracción.
        return {}
    if now < _REMOTE_MEMORY_DISABLED_UNTIL:
        return {}

    try:
        from or_client import client

        combined = f"Usuario: {user_text[:700]}\nHelena: {helena_text[:300]}"

        raw = client.chat(
            "Extrae hechos personales memorables de esta conversación.\n"
            "Devuelve SOLO JSON válido. Usa {} si no hay nada realmente útil para guardar.\n\n"
            "Reglas importantes:\n"
            "- Guarda los valores en ESPAÑOL natural.\n"
            "- Usa categorías compatibles: identity, preferences, projects, relationships, wishes, notes, contact, communication_rules.\n"
            "- Las claves internas pueden estar en snake_case y en español.\n"
            "- Guarda principalmente datos confirmados por el usuario.\n"
            "- No inventes ni conviertas bromas o roleplay en hechos reales.\n"
            "- No guardes recuerdos contradictorios con correcciones explícitas del usuario.\n"
            "- No guardes comandos puntuales, clima, recordatorios únicos ni resultados de búsquedas.\n\n"
            "Guía de categorías:\n"
            "  identity             → nombre, ciudad, país, trabajo, idioma.\n"
            "  preferences          → gustos, preferencias, estilo de respuesta, idioma preferido.\n"
            "  projects             → proyectos activos, código, ideas en desarrollo.\n"
            "  relationships        → personas importantes mencionadas por el usuario.\n"
            "  wishes               → planes o deseos futuros.\n"
            "  notes                → datos útiles que no entren en otra categoría.\n"
            "  contact              → datos de contacto que el usuario pidió guardar.\n"
            "  communication_rules  → reglas de formato o comportamiento al comunicarse.\n\n"
            "Formato esperado:\n"
            '{"identity":{"nombre":{"value":"Leo"}},\n'
            ' "preferences":{"idioma_memoria":{"value":"Prefiere guardar la memoria en español"}},\n'
            ' "projects":{"helena":{"value":"Está mejorando su asistente IA Helena"}},\n'
            ' "notes":{"correccion_valorant":{"value":"No juega ni jugó Valorant"}}}\n\n'
            f"Conversación:\n{combined}\n\nJSON:",
            system="Devuelve SOLO JSON válido. Sin markdown, sin explicación y sin texto extra.",
            max_tokens=1024,
            temperature=0.2,
        )

        clean = raw.strip()
        clean = re.sub(r"```(?:json)?", "", clean).strip().rstrip("`").strip()

        if not clean or clean == "{}":
            return {}

        return json.loads(clean)

    except json.JSONDecodeError:
        return {}
    except Exception as e:
        _REMOTE_MEMORY_FAILURES += 1
        if _REMOTE_MEMORY_FAILURES >= 2:
            _REMOTE_MEMORY_DISABLED_UNTIL = time.time() + _REMOTE_MEMORY_COOLDOWN_SECONDS
        if "429" not in str(e) and time.time() - _REMOTE_MEMORY_LAST_LOG > 60:
            _REMOTE_MEMORY_LAST_LOG = time.time()
            print(f"[Memoria] ⚠️ Falló la extracción; memoria remota en pausa: {e}")
        return {}


def _entry_value(entry):
    if isinstance(entry, dict) and "value" in entry:
        return entry.get("value")
    return entry


def _humanize_key(key: str) -> str:
    return str(key).replace("_", " ").strip().capitalize()


def _value_to_text(value) -> str:
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if v in (None, ""):
                continue
            parts.append(f"{_humanize_key(k)}: {_value_to_text(v)}")
        return "; ".join(parts)
    if isinstance(value, list):
        return ", ".join(_value_to_text(v) for v in value if v not in (None, ""))
    return str(value)


def _append_category(lines: list[str], title: str, items: dict, limit: int = 10) -> None:
    if not isinstance(items, dict) or not items:
        return
    section = []
    for key, entry in list(items.items())[:limit]:
        val = _entry_value(entry)
        text = _value_to_text(val)
        if text:
            section.append(f"  - {_humanize_key(key)}: {text}")
    if section:
        lines.append("")
        lines.append(title)
        lines.extend(section)


def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    _append_category(lines, "Identidad:", memory.get("identity", {}), limit=12)
    _append_category(lines, "Preferencias:", memory.get("preferences", {}), limit=15)
    _append_category(lines, "Proyectos activos / objetivos:", memory.get("projects", {}), limit=10)
    _append_category(lines, "Personas importantes:", memory.get("relationships", {}), limit=12)
    _append_category(lines, "Deseos / planes / pendientes:", memory.get("wishes", {}), limit=10)
    _append_category(lines, "Notas útiles:", memory.get("notes", {}), limit=12)
    _append_category(lines, "Contactos importantes:", memory.get("contact", {}), limit=8)
    _append_category(lines, "Reglas de comunicación:", memory.get("communication_rules", {}), limit=8)

    if not lines:
        return ""

    header = "[MEMORIA DE HELENA — usar naturalmente, nunca recitar como lista]\n"
    result = header + "\n".join(lines).strip()
    if len(result) > 2600:
        result = result[:2597] + "…"

    return result + "\n"


def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {
        "identity", "preferences", "projects", "relationships", "wishes",
        "notes", "contact", "communication_rules", "conversation_context"
    }
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Recordado: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Olvidado: {category}/{key}"
    return f"No encontrado: {category}/{key}"


forget_memory = forget
