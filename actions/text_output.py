# actions/text_output.py
# HELENA V24: Router seguro de salida textual.
# Salidas permitidas: HUD/CORE, canal de texto de Discord, WhatsApp explícito.
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
MEMORY_PATH = BASE_DIR / "memory" / "long_term.json"


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[TextOutput] ⚠️ No pude leer {path.name}: {exc}")
    return {}


def _cfg(name: str, default=None):
    data = _load_json(CONFIG_PATH)
    if name.upper() in os.environ:
        return os.environ.get(name.upper())
    return data.get(name, data.get(name.upper(), default))


def _normalize_target(value: str) -> str:
    t = str(value or "").strip().lower()
    t = t.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    t = re.sub(r"[^a-z0-9_\s-]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if t in ("", "default", "defecto", "pantalla", "core", "chat", "hud", "ventana de helena", "helena"):
        return "hud"
    if "discord" in t or t in ("dc", "canal", "canal de texto", "texto discord"):
        return "discord"
    if "whatsapp" in t or "whatts" in t or "wsp" in t or "wapp" in t or t in ("wp", "wa"):
        return "whatsapp"
    return t


def _default_whatsapp_receiver() -> str:
    cfg_receiver = str(_cfg("text_output_whatsapp_default_receiver", "") or "").strip()
    if cfg_receiver:
        return cfg_receiver
    mem = _load_json(MEMORY_PATH)
    try:
        self_contact = mem.get("contact", {}).get("whatsapp_self", {})
        if isinstance(self_contact, dict):
            value = self_contact.get("value", self_contact)
            if isinstance(value, dict):
                return str(value.get("agendado_como") or value.get("nombre_contacto") or value.get("numero_para_api") or value.get("numero_local") or "Mi numero")
    except Exception:
        pass
    return "Mi numero"


def _clip_message(message: str, max_len: int = 12000) -> str:
    message = str(message or "").strip()
    if len(message) <= max_len:
        return message
    return message[: max_len - 80].rstrip() + "\n\n[Texto recortado por seguridad. Pedime guardar el resto si hace falta.]"


def _send_to_hud(message: str, player=None, title: str = "") -> str:
    content = _clip_message(message)
    if title:
        content = f"{title}\n{content}"
    if player and hasattr(player, "write_log"):
        # En V20, las líneas que empiezan con Helena: van a CORE/conversación.
        player.write_log("Helena: " + content)
    else:
        print("Helena: " + content)
    return "Texto mostrado en el HUD."


def _send_to_discord(message: str, player=None, channel_id: str = "") -> str:
    content = _clip_message(message, max_len=6000)
    try:
        from actions.discord_mode import send_text_to_discord
        ok, detail = send_text_to_discord(content, channel_id=channel_id)
        if ok:
            if player and hasattr(player, "write_log"):
                player.write_log("Sistema: texto enviado al canal de Discord.")
            return detail or "Texto enviado al canal de Discord."
        if player and hasattr(player, "write_log"):
            player.write_log(f"Sistema: no pude enviar texto a Discord: {detail}. Lo muestro en HUD.")
        _send_to_hud(content, player=player, title="[Fallback: Discord texto no disponible]")
        return f"No pude enviar a Discord ({detail}). Lo mostré en el HUD."
    except Exception as exc:
        if player and hasattr(player, "write_log"):
            player.write_log(f"Sistema: error enviando texto a Discord: {exc}. Lo muestro en HUD.")
        _send_to_hud(content, player=player, title="[Fallback: error Discord texto]")
        return f"Error enviando a Discord: {exc}. Lo mostré en el HUD."


def _send_to_whatsapp(message: str, player=None, receiver: str = "") -> str:
    content = _clip_message(message, max_len=3500)
    receiver = str(receiver or "").strip() or _default_whatsapp_receiver()
    try:
        from actions.send_message import send_message
        result = send_message(
            parameters={"platform": "whatsapp", "receiver": receiver, "message_text": content},
            response=None,
            player=player,
            session_memory=None,
        )
        return result or f"Texto enviado por WhatsApp a {receiver}."
    except Exception as exc:
        if player and hasattr(player, "write_log"):
            player.write_log(f"Sistema: error enviando WhatsApp: {exc}. Lo muestro en HUD.")
        _send_to_hud(content, player=player, title="[Fallback: error WhatsApp]")
        return f"Error enviando por WhatsApp: {exc}. Lo mostré en el HUD."


def text_output(parameters=None, response=None, player=None, session_memory=None) -> str:
    """
    Router seguro de texto.

    parameters:
      message_text: texto a mostrar/enviar
      target: hud | discord | whatsapp
      receiver: contacto opcional para WhatsApp
      channel_id: canal opcional para Discord texto
      title: título opcional para HUD
    """
    params = parameters or {}
    message = str(params.get("message_text") or params.get("text") or params.get("message") or "").strip()
    target = _normalize_target(params.get("target") or params.get("destination") or params.get("destino") or "hud")
    receiver = str(params.get("receiver") or params.get("contact") or params.get("contacto") or "").strip()
    channel_id = str(params.get("channel_id") or params.get("discord_text_channel_id") or "").strip()
    title = str(params.get("title") or params.get("titulo") or "").strip()

    if not message:
        return "No tengo texto para enviar o mostrar."

    print(f"[TextOutput] target={target} len={len(message)}")

    if target == "discord":
        return _send_to_discord(message, player=player, channel_id=channel_id)
    if target == "whatsapp":
        return _send_to_whatsapp(message, player=player, receiver=receiver)

    # HUD es el destino seguro por defecto.
    return _send_to_hud(message, player=player, title=title)
