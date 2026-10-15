# actions/send_message.py
# Universal messaging — WhatsApp, Instagram, Telegram y apps genéricas.
# Lee reglas de memory/long_term.json para aplicar formatos especiales.

import json
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pyautogui

try:
    import pyperclip
except Exception:
    pyperclip = None

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.08


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


MEMORY_PATH = _base_dir() / "memory" / "long_term.json"


def _load_memory() -> dict:
    try:
        if MEMORY_PATH.exists():
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"[SendMessage] ⚠️ No pude leer la memoria: {e}")
    return {}


def _entry_value(entry):
    if isinstance(entry, dict) and "value" in entry:
        return entry.get("value")
    return entry


def _as_dict(value) -> dict:
    value = _entry_value(value)
    return value if isinstance(value, dict) else {}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _digits_only(text: str) -> str:
    return re.sub(r"\D+", "", str(text or ""))


def _normalize_for_match(text: str) -> str:
    """Normaliza SOLO para comparar nombres. No se usa para enviar texto."""
    text = str(text or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9ñ\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _paste_text(text: str, interval_fallback: float = 0.03):
    """
    Pega texto por portapapeles para no perder acentos ni letras.
    pyautogui.write puede fallar con UTF-8, layouts de teclado o foco lento.
    """
    text = str(text or "")
    if pyperclip is not None:
        try:
            pyperclip.copy(text)
            time.sleep(0.08)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.08)
            return
        except Exception as e:
            print(f"[SendMessage] ⚠️ No pude pegar desde portapapeles, uso escritura lenta: {e}")

    # Fallback: puede perder caracteres especiales, pero evita romper el envío.
    pyautogui.write(text, interval=interval_fallback)


def _read_aliases(value: dict) -> list[str]:
    aliases = []
    for key in ("alias", "aliases", "apodos", "buscar_como", "nombres_alternativos"):
        raw = value.get(key)
        if isinstance(raw, str):
            aliases.append(raw)
        elif isinstance(raw, list):
            aliases.extend(str(x) for x in raw if x)
    return aliases


def _iter_memory_contacts(memory: dict):
    """
    Devuelve contactos guardados en distintas formas posibles de la memoria.
    Soporta contact, contacts, contactos, whatsapp_contacts y contactos_whatsapp.
    """
    containers = []
    for key in ("contact", "contacts", "contactos", "whatsapp_contacts", "contactos_whatsapp"):
        value = memory.get(key)
        if isinstance(value, dict):
            containers.append(value)

    for container in containers:
        for _, entry in container.items():
            value = _as_dict(entry)
            if not value:
                continue

            official = (
                value.get("agendado_como")
                or value.get("nombre_contacto")
                or value.get("nombre")
                or value.get("name")
            )
            if not official:
                continue

            candidates = [official]
            candidates.extend(_read_aliases(value))
            for key in ("numero_local", "numero_para_api", "numero_whatsapp_argentina", "telefono", "phone"):
                if value.get(key):
                    candidates.append(str(value.get(key)))

            yield str(official), [str(x) for x in candidates if x]


def _resolve_contact_from_memory(receiver: str, memory: dict) -> str:
    """
    Corrige el nombre del destinatario usando contactos/alias guardados.
    Ej: si llega 'jan plo' y existe alias o contacto 'Juan Pablo', usa 'Juan Pablo'.
    """
    raw = str(receiver or "").strip()
    if not raw:
        return raw

    raw_norm = _normalize_for_match(raw)
    raw_digits = _digits_only(raw)

    contacts = list(_iter_memory_contacts(memory))

    # 1) Coincidencia exacta por alias/nombre/número.
    for official, candidates in contacts:
        for candidate in candidates:
            cand_norm = _normalize_for_match(candidate)
            cand_digits = _digits_only(candidate)
            if raw_norm and raw_norm == cand_norm:
                return official
            if raw_digits and cand_digits and _same_phone(raw, candidate):
                return official

    # 2) Coincidencia difusa, pero solo si es bastante fuerte.
    best_name = raw
    best_score = 0.0
    for official, candidates in contacts:
        for candidate in candidates:
            cand_norm = _normalize_for_match(candidate)
            if not raw_norm or not cand_norm:
                continue
            score = SequenceMatcher(None, raw_norm, cand_norm).ratio()
            if score > best_score:
                best_score = score
                best_name = official

    if best_score >= 0.82:
        print(f"[SendMessage] 🔎 Contacto corregido: '{raw}' → '{best_name}' ({best_score:.2f})")
        return best_name

    return raw


def _same_phone(a: str, b: str) -> bool:
    da, db = _digits_only(a), _digits_only(b)
    if not da or not db:
        return False
    return da == db or da.endswith(db) or db.endswith(da)


def _is_self_whatsapp_contact(receiver: str, memory: dict) -> bool:
    contact = _as_dict(memory.get("contact", {}).get("whatsapp_self", {}))
    rule = _as_dict(memory.get("communication_rules", {}).get("whatsapp_identity_prefix", {}))

    receiver_text = _normalize_text(receiver)

    names = [
        contact.get("agendado_como"),
        contact.get("nombre_contacto"),
        rule.get("aplicar_solo_si_destinatario_agendado_como"),
    ]
    for name in names:
        if name and receiver_text == _normalize_text(name):
            return True

    numbers = [
        contact.get("numero_local"),
        contact.get("numero_para_api"),
        contact.get("numero_whatsapp_argentina"),
        rule.get("aplicar_solo_si_numero_para_api"),
    ]
    for number in numbers:
        if number and _same_phone(receiver, str(number)):
            return True

    return False


def _format_whatsapp_message(receiver: str, message: str) -> str:
    """
    Solo agrega 'Helena :' cuando el destinatario es el contacto personal del usuario.
    Para otros contactos deja el mensaje normal, porque Helena escribe en nombre del usuario.
    """
    memory = _load_memory()
    if not _is_self_whatsapp_contact(receiver, memory):
        return message

    rule = _as_dict(memory.get("communication_rules", {}).get("whatsapp_identity_prefix", {}))
    prefix = str(rule.get("prefix") or "Helena : ")
    template = str(rule.get("formato_si_es_mi_numero") or 'Helena : "{mensaje}"')

    # Evita duplicar el prefijo si el modelo ya lo escribió.
    if _normalize_text(message).startswith(_normalize_text(prefix)):
        return message

    return template.replace("{mensaje}", message)


def _open_app(app_name: str) -> bool:
    """Opens an app via Windows search."""
    try:
        pyautogui.press("win")
        time.sleep(0.4)
        pyautogui.write(app_name, interval=0.04)
        time.sleep(0.5)
        pyautogui.press("enter")
        time.sleep(2.0)
        return True
    except Exception as e:
        print(f"[SendMessage] Could not open {app_name}: {e}")
        return False


def _search_contact(contact: str, platform: str):
    """Searches for a contact inside the messaging app."""
    time.sleep(0.5)
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.4)
    pyautogui.hotkey("ctrl", "a")
    _paste_text(contact)
    time.sleep(0.8)
    pyautogui.press("enter")
    time.sleep(0.6)


def _type_and_send(message: str):
    """Types message and sends it."""
    pyautogui.press("tab")
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "a")
    _paste_text(message)
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.3)


def _send_whatsapp(receiver: str, message: str) -> str:
    """
    Sends a WhatsApp message via the Windows desktop app.
    Steps: Open WhatsApp → Search contact → Click → Type → Send
    """
    try:
        if not _open_app("WhatsApp"):
            return "No pude abrir WhatsApp."

        time.sleep(1.5)

        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        pyautogui.hotkey("ctrl", "a")
        _paste_text(receiver)
        time.sleep(1.0)

        pyautogui.press("enter")
        time.sleep(0.8)

        _paste_text(message)
        time.sleep(0.2)
        pyautogui.press("enter")

        return f"Mensaje enviado a {receiver} por WhatsApp."

    except Exception as e:
        return f"Error de WhatsApp: {e}"


def _send_instagram(receiver: str, message: str) -> str:
    """Sends an Instagram DM via browser (instagram.com)."""
    try:
        import webbrowser

        webbrowser.open("https://www.instagram.com/direct/new/")
        time.sleep(3.5)

        _paste_text(receiver)
        time.sleep(1.5)

        pyautogui.press("down")
        time.sleep(0.3)
        pyautogui.press("enter")
        time.sleep(0.5)

        for _ in range(3):
            pyautogui.press("tab")
            time.sleep(0.1)
        pyautogui.press("enter")
        time.sleep(1.5)

        _paste_text(message)
        time.sleep(0.2)
        pyautogui.press("enter")

        return f"Mensaje enviado a {receiver} por Instagram."

    except Exception as e:
        return f"Error de Instagram: {e}"


def _send_telegram(receiver: str, message: str) -> str:
    """Sends a Telegram message via Windows desktop app."""
    try:
        if not _open_app("Telegram"):
            return "No pude abrir Telegram."

        time.sleep(1.5)

        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        _paste_text(receiver)
        time.sleep(1.0)
        pyautogui.press("enter")
        time.sleep(0.8)

        _paste_text(message)
        time.sleep(0.2)
        pyautogui.press("enter")

        return f"Mensaje enviado a {receiver} por Telegram."

    except Exception as e:
        return f"Error de Telegram: {e}"


def _send_generic(platform: str, receiver: str, message: str) -> str:
    """For any other platform not explicitly supported."""
    try:
        if not _open_app(platform):
            return f"No pude abrir {platform}."

        time.sleep(1.5)
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        _paste_text(receiver)
        time.sleep(1.0)
        pyautogui.press("enter")
        time.sleep(0.8)
        _paste_text(message)
        time.sleep(0.2)
        pyautogui.press("enter")

        return f"Mensaje enviado a {receiver} por {platform}."

    except Exception as e:
        return f"Error de {platform}: {e}"


def send_message(parameters: dict, response=None, player=None, session_memory=None) -> str:
    """
    Called from main.py.

    parameters:
        receiver     : Contact name or number to send to
        message_text : The message content
        platform     : whatsapp | instagram | telegram | <any app name>
                       Default: whatsapp
    """
    params = parameters or {}
    receiver = params.get("receiver", "").strip()
    message_text = params.get("message_text", "").strip()
    platform = params.get("platform", "whatsapp").strip().lower()

    if not receiver:
        return "Decime a quién querés que le mande el mensaje."
    if not message_text:
        return "Decime qué mensaje querés mandar."

    is_whatsapp = "whatsapp" in platform or "wp" in platform or "wapp" in platform
    memory = _load_memory() if is_whatsapp else {}

    if is_whatsapp:
        receiver_original = receiver
        receiver = _resolve_contact_from_memory(receiver, memory)
        # Formatea usando original o resuelto para detectar "Mi numero" y números propios.
        if _is_self_whatsapp_contact(receiver_original, memory) or _is_self_whatsapp_contact(receiver, memory):
            message_text = _format_whatsapp_message(receiver, message_text)

    print(f"[SendMessage] 📨 {platform} → {receiver}: {message_text[:60]}")
    if player:
        player.write_log(f"[Mensaje] Enviando a {receiver} por {platform}...")

    if is_whatsapp:
        result = _send_whatsapp(receiver, message_text)
    elif "instagram" in platform or "ig" in platform or "insta" in platform:
        result = _send_instagram(receiver, message_text)
    elif "telegram" in platform or "tg" in platform:
        result = _send_telegram(receiver, message_text)
    else:
        result = _send_generic(platform, receiver, message_text)

    print(f"[SendMessage] ✅ {result}")
    if player:
        player.write_log(f"[Mensaje] {result}")

    return result
