# actions/discord_mode.py - modo Discord híbrido estable para HELENA

# V30: lifecycle robusto + aliases + presencia + salida continua + entrada Discord opcional.

from __future__ import annotations



import json

import os

import re

import threading

import time

import unicodedata

from pathlib import Path



_bridge = None

_context = None

_lock = threading.RLock()

_last_enter_ts = 0.0

_last_enter_target = ""



V22_PUBLIC_PERSONA_REMINDER = (

    " Modo publico gamer activado: en Discord soy carismatica, graciosa y picante de party; "

    "cariñosa con Leo pero sin detalles intimos ni sexuales. Si Leo transmite lo que alguien dijo, "

    "respondo a esa persona con humor gamer sano."

)



BASE_DIR = Path(__file__).resolve().parent.parent

DISCORD_CONFIG_PATHS = (

    BASE_DIR / "config" / "discord_config.json",

    BASE_DIR / "config" / "api_keys.json",

)

KNOWN_TARGET_ALIASES = {"taberna", "martin", "martín", "tincho", "simio", "privado"}

UNKNOWN_CHANNEL_MSG = "No reconozco ese canal de Discord. Lo dejo escrito en HUD y no cambio de canal."

BUILTIN_ALLOWED_VOICE_CHANNEL_IDS = {

    "privado": "1509434884501012551",

}





def set_discord_context(context) -> None:

    global _context

    _context = context





def _ui_log(text: str) -> None:

    ctx = _context

    try:

        if ctx and getattr(ctx, "ui", None):

            ctx.ui.write_log(text)

        print(text)

    except Exception:

        print(text)





def _on_discord_audio_16k(pcm: bytes) -> None:

    ctx = _context

    if not ctx:

        return None

    try:

        ctx.submit_discord_audio(pcm)

    except Exception as exc:

        _ui_log(f"[Discord] ⚠️ No pude pasar audio de Discord a Helena: {exc}")





def _on_discord_presence_event(event: dict) -> None:
    """Convierte eventos de presencia del canal en una intervención generada por la IA.
    
    V32.7: Rate limiting anti-loop: no responder a eventos de presencia si Helena
    acaba de hablar o si hubo un evento reciente (< 8s). Evita bucles de auto-respuesta.
    """
    ctx = _context
    try:
        kind = str(event.get("type") or "join")
        name = str(event.get("user_name") or "alguien")
        channel = str(event.get("channel_name") or "el canal")
        members = event.get("members") or []
        members_text = ", ".join(members) if isinstance(members, list) else str(members)

        # Rate limiting: evitar bucles de auto-respuesta
        now = time.time()
        if not hasattr(_on_discord_presence_event, "_last_presence_ts"):
            _on_discord_presence_event._last_presence_ts = 0.0
            _on_discord_presence_event._last_presence_kind = ""
            _on_discord_presence_event._last_presence_name = ""
        
        # Ignorar eventos muy frecuentes del mismo tipo/usuario (posible bucle)
        if (now - _on_discord_presence_event._last_presence_ts < 8.0 and
            _on_discord_presence_event._last_presence_kind == kind and
            _on_discord_presence_event._last_presence_name == name):
            _ui_log(f"[Discord] ⏭️ Evento de presencia ignorado (rate limit): {kind} {name}")
            return
        
        # También ignorar si Helena habló hace menos de 5s (evita respuesta a su propia salida)
        if ctx and hasattr(ctx, "_assistant_output_last_audio_ts"):
            if now - getattr(ctx, "_assistant_output_last_audio_ts", 0) < 5.0:
                _ui_log(f"[Discord] ⏭️ Evento de presencia ignorado (Helena acaba de hablar): {kind} {name}")
                return

        _on_discord_presence_event._last_presence_ts = now
        _on_discord_presence_event._last_presence_kind = kind
        _on_discord_presence_event._last_presence_name = name

        if kind == "join":
            prompt = (
                f"[EVENTO DISCORD PUBLICO - PRESENCIA] Entró {name} al canal {channel}. "
                f"Usuarios visibles ahora: {members_text}. "
                "Respondé en voz con UNA sola frase breve para el canal. "
                "Avisale a Leo si corresponde, por ejemplo 'Leito, entró X'. "
                "Tono gamer carismático, gracioso, de party; podés usar bardo amistoso como manko/petón/noob/NPC si queda natural. "
                "No uses detalles íntimos, sexuales ni romanticismo intenso."
            )
        else:
            prompt = (
                f"[EVENTO DISCORD PUBLICO - PRESENCIA] {name} salió del canal {channel}. "
                f"Usuarios visibles ahora: {members_text}. "
                "Respondé en voz con UNA sola frase breve para el canal, estilo gamer gracioso. "
                "No uses detalles íntimos, sexuales ni romanticismo intenso."
            )
        _ui_log(f"[Discord] 🤖 Evento de presencia enviado a Helena IA: {kind} {name}")
        if ctx and getattr(ctx, "audio_route", "local") == "discord":
            ctx.speak(prompt)
    except Exception as exc:
        _ui_log(f"[Discord] ⚠️ No pude procesar evento de presencia con IA: {exc}")



def send_audio_to_discord(pcm24: bytes) -> bool:

    global _bridge

    if _bridge is None:

        return False

    try:

        return bool(_bridge.enqueue_output_audio(pcm24))

    except Exception as exc:

        _ui_log(f"[Discord] ⚠️ No pude reproducir audio en Discord: {exc}")

        return False





def send_text_to_discord(message: str, channel_id: str = "") -> tuple[bool, str]:

    global _bridge

    if _bridge is None:

        return False, "Discord no está iniciado"

    try:

        return _bridge.send_text_message(message, channel_id=channel_id)

    except Exception as exc:

        _ui_log(f"[Discord] ⚠️ No pude enviar texto a Discord: {exc}")

        return False, str(exc)





def _make_bridge():

    from discord_bridge import HelenaDiscordBridge

    return HelenaDiscordBridge(

        on_audio_16k=_on_discord_audio_16k,

        on_status=_ui_log,

        on_presence_event=_on_discord_presence_event,

    )





def _start_bridge(force_new: bool = False, target: str = ""):

    global _bridge

    with _lock:

        if force_new and _bridge is not None:

            try:

                _bridge.shutdown()

            except Exception:

                pass

            _bridge = None

        if _bridge is None:

            _bridge = _make_bridge()

        _bridge.start(target=target)

        return _bridge





def _shutdown_bridge() -> str:

    global _bridge

    with _lock:

        if _bridge is None:

            return "Discord ya estaba apagado."

        try:

            _bridge.shutdown()

        finally:

            _bridge = None

        return "Reinicié el puente de Discord por completo."





def _extract_target(parameters: dict) -> str:

    target = (

        parameters.get("target")

        or parameters.get("channel")

        or parameters.get("canal")

        or parameters.get("server")

        or parameters.get("servidor")

        or parameters.get("destination")

        or parameters.get("destino")

        or ""

    )

    return str(target or "").strip()





def _normalize_alias(value: str) -> str:

    value = str(value or "").strip().lower()

    value = "".join(

        ch for ch in unicodedata.normalize("NFD", value)

        if unicodedata.category(ch) != "Mn"

    )

    return " ".join(re.sub(r"[^a-z0-9_\s-]+", " ", value).split())





def _load_discord_configs() -> list[dict]:

    configs = []

    for path in DISCORD_CONFIG_PATHS:

        try:

            if path.exists():

                data = json.loads(path.read_text(encoding="utf-8-sig"))

                if isinstance(data, dict):

                    configs.append(data)

        except Exception as exc:

            _ui_log(f"[Discord] ⚠️ No pude leer {path.name} para validar canales: {exc}")

    return configs





def _collect_confirmed_voice_ids() -> set[str]:

    ids: set[str] = set()

    ids.update(value for value in BUILTIN_ALLOWED_VOICE_CHANNEL_IDS.values() if str(value).isdigit())

    for data in _load_discord_configs():

        for key in ("discord_voice_channel_id", "DISCORD_VOICE_CHANNEL_ID"):

            value = str(data.get(key) or "").strip()

            if value.isdigit():

                ids.add(value)

        for mapping_name in (

            "discord_fallback_channels",

            "discord_voice_channels",

            "discord_known_voice_channels",

            "discord_allowed_voice_channel_ids",

        ):

            raw = data.get(mapping_name) or data.get(mapping_name.upper()) or {}

            if isinstance(raw, dict):

                for value in raw.values():

                    value = str(value or "").strip()

                    if value.isdigit():

                        ids.add(value)

    env_voice = os.getenv("DISCORD_VOICE_CHANNEL_ID", "").strip()

    if env_voice.isdigit():

        ids.add(env_voice)

    return ids





def _is_known_alias_target(target: str) -> bool:

    norm = _normalize_alias(target)

    if not norm:

        return True

    return any(alias in norm for alias in KNOWN_TARGET_ALIASES)





def _is_valid_discord_target(target: str) -> bool:

    raw = str(target or "").strip()

    if not raw:

        return True

    if raw.isdigit():

        return raw in _collect_confirmed_voice_ids()

    return _is_known_alias_target(raw)





def _reject_unknown_target(player=None) -> str:

    try:

        target_player = player or (getattr(_context, "ui", None) if _context else None)

        if target_player and hasattr(target_player, "write_log"):

            target_player.write_log("Sistema: " + UNKNOWN_CHANNEL_MSG)

    except Exception:

        pass

    _ui_log("[Discord] Target rechazado: no es alias conocido ni ID de canal confirmado.")

    return UNKNOWN_CHANNEL_MSG



def discord_mode(parameters=None, response=None, player=None, session_memory=None):

    """parameters: action = enter | leave | reset | status | test_audio"""

    global _bridge, _last_enter_ts

    parameters = parameters or {}

    action = str(parameters.get("action") or parameters.get("mode") or "enter").strip().lower()

    target = _extract_target(parameters)

    ctx = _context



    if action in ("enter", "join", "entrar", "connect", "conectar", "voice", "voz", "cambiar", "switch", "move", "mover"):

        if not _is_valid_discord_target(target):

            return _reject_unknown_target(player=player)



    if action in ("reset", "restart", "reiniciar", "force_restart", "hard_reset", "reconectar"):

        if ctx:

            ctx.set_audio_route("local")

        msg = _shutdown_bridge()

        return msg + " Pedime de nuevo que entre a Discord."



    if action in ("leave", "salir", "off", "local", "programa", "volver", "volve", "volvé"):

        with _lock:

            if _bridge:

                _bridge.leave()

            if ctx:

                ctx.set_audio_route("local")

        return "Helena salió de Discord y volvió al modo local."



    if action in ("test_audio", "beep", "tono", "probar_audio", "audio_test"):

        if _bridge is None:

            return "Todavía no estoy conectada a Discord. Primero pedime que entre a Discord."

        try:

            ok = bool(_bridge.play_test_tone())

        except Exception as exc:

            _ui_log(f"[Discord] ⚠️ No pude enviar tono de prueba: {exc}")

            ok = False

        return "Envié un tono de prueba por Discord." if ok else "No pude enviar el tono porque todavía no estoy conectada al canal de voz."



    if action in ("status", "estado"):

        route = getattr(ctx, "audio_route", "local") if ctx else "local"

        active = _bridge is not None and getattr(_bridge, "running", False)

        connected = _bridge is not None and bool(getattr(_bridge, "voice_client", None))

        muted = _bridge is not None and bool(getattr(_bridge, "is_output_muted", lambda: False)())

        extra = ""

        if _bridge is not None:

            try:

                extra = " | " + _bridge.debug_status()

            except Exception:

                extra = ""

        return f"Modo de audio: {route}. Discord iniciado: {active}. Voice conectado: {connected}. Muteado: {muted}. Discord puede escuchar el canal si la recepción está activa; si no, conserva entrada local + voz en Discord.{extra}"



    if action in ("mute", "mutear", "muteate", "silence", "silencio", "callate", "callar", "muda"):

        if _bridge is None:

            return "Todavía no estoy conectada a Discord."

        try:

            _bridge.set_output_muted(True)

        except Exception as exc:

            return f"No pude mutearme en Discord: {exc}"

        return "Me muteé en Discord. Sigo presente, pero no voy a hablar hasta que me desmutees."



    if action in ("unmute", "desmutear", "desmuteate", "hablar", "habla", "voz", "desilencio"):

        if _bridge is None:

            return "Todavía no estoy conectada a Discord."

        try:

            _bridge.set_output_muted(False)

        except Exception as exc:

            return f"No pude desmutearme en Discord: {exc}"

        return "Ya estoy desmuteada en Discord. Vuelvo a hablar por el canal." + V22_PUBLIC_PERSONA_REMINDER



    if action in ("members", "usuarios", "quienes", "quien", "presentes", "canal"):

        if _bridge is None:

            return "Todavía no estoy conectada a Discord."

        try:

            return _bridge.describe_members()

        except Exception as exc:

            return f"No pude leer quién está en el canal: {exc}"



    # ENTER idempotente con cooldown para evitar órdenes repetidas de Gemini.

    now = time.time()

    global _last_enter_target

    target_key = str(target or "").strip().lower()

    with _lock:

        if _bridge is not None and getattr(_bridge, "is_voice_connected", lambda: False)() and now - _last_enter_ts < 4.0:

            # Sin target: ya está en Discord.

            if not target_key:

                if ctx:

                    ctx.set_audio_route("discord")

                return "Ya estoy conectada a Discord en modo V30." + V22_PUBLIC_PERSONA_REMINDER

            # Con target repetido: no spamear move_to mientras Discord todavía procesa.

            if target_key == _last_enter_target:

                if ctx:

                    ctx.set_audio_route("discord")

                return f"Ya estoy procesando o ya hice el cambio al canal {target}."

        _last_enter_ts = now

        _last_enter_target = target_key



    _ui_log("[Discord] Orden recibida: entrar/cambiar al canal de voz.")

    try:

        bridge = _start_bridge(force_new=False, target=target)

    except Exception as exc:

        _ui_log(f"[Discord] ❌ Error iniciando Discord: {exc}")

        return f"No pude iniciar Discord: {exc}"



    if ctx:

        ctx.set_audio_route("discord")



    if getattr(bridge, "ready", None) and bridge.ready.is_set():

        return f"Helena entró a Discord: destino {target or 'La Taberna de Aden'}. Si la recepción Discord está activa, escucha el canal completo; si falta dependencia, queda en híbrido local y responde por Discord." + V22_PUBLIC_PERSONA_REMINDER

    return f"Estoy intentando entrar/cambiar Discord hacia {target or 'La Taberna de Aden'}. Si no entro en unos segundos, pedime: estado Discord." + V22_PUBLIC_PERSONA_REMINDER
