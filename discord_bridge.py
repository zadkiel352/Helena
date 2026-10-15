# discord_bridge.py - HELENA Discord Voice Bridge V30
# V30: salida Discord continua + recepción opcional del canal con discord-ext-voice-recv.
# Sin privileged intents; si falta recepción, degrada a modo híbrido local.
from __future__ import annotations

import asyncio
import json
import math
import os
import threading
import time
import traceback
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
BUILTIN_ALLOWED_VOICE_CHANNEL_IDS = {
    "privado": "1509434884501012551",
}


def _read_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print(f"[Discord] ⚠️ No pude leer config/api_keys.json: {exc}")
    return {}


def _cfg(name: str, default: str = "") -> str:
    data = _read_config()
    value = os.getenv(name.upper()) or data.get(name) or data.get(name.upper()) or default
    return str(value).strip() if value is not None else default


def _normalize_alias(value: str) -> str:
    value = str(value or "").strip().lower()
    value = "".join(
        ch for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )
    for ch in ('"', "'", "`", "´"):
        value = value.replace(ch, "")
    return " ".join(value.split())


def _cfg_mapping(name: str) -> dict:
    data = _read_config()
    raw = data.get(name) or data.get(name.upper()) or {}
    return raw if isinstance(raw, dict) else {}

def _cfg_bool(name: str, default: bool = False) -> bool:
    raw = _cfg(name, "1" if default else "0").strip().lower()
    return raw not in ("0", "false", "no", "off", "apagado", "")


def _cfg_int(name: str, default: int = 0) -> int:
    try:
        return int(_cfg(name, str(default)))
    except Exception:
        return default


def _to_int(value) -> Optional[int]:
    try:
        s = str(value).strip()
        return int(s) if s else None
    except Exception:
        return None


def _pcm_s16_to_np(pcm: bytes) -> np.ndarray:
    if not pcm:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def _np_to_pcm_s16(audio: np.ndarray) -> bytes:
    if audio.size == 0:
        return b""
    audio = np.clip(audio, -0.98, 0.98)
    return (audio * 32767.0).astype(np.int16).tobytes()


def _resample_linear(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if audio.size == 0 or src_rate == dst_rate:
        return audio.astype(np.float32, copy=False)
    duration = audio.size / float(src_rate)
    dst_size = max(1, int(round(duration * dst_rate)))
    x_old = np.linspace(0.0, duration, num=audio.size, endpoint=False)
    x_new = np.linspace(0.0, duration, num=dst_size, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def gemini_pcm24_mono_to_discord_pcm48_stereo(pcm24: bytes) -> bytes:
    mono24 = _pcm_s16_to_np(pcm24)
    if mono24.size == 0:
        return b""
    mono48 = _resample_linear(mono24, 24000, 48000)
    stereo = np.repeat(mono48[:, None], 2, axis=1).reshape(-1)
    return _np_to_pcm_s16(stereo)


def discord_pcm48_stereo_to_gemini_pcm16(pcm48: bytes) -> bytes:
    """Convierte audio recibido de Discord a PCM mono 16 kHz para Gemini Live."""
    if not pcm48:
        return b""
    stereo = _pcm_s16_to_np(pcm48)
    if stereo.size == 0:
        return b""
    if stereo.size % 2:
        stereo = stereo[:-1]
    mono48 = stereo.reshape(-1, 2).mean(axis=1)
    mono16 = _resample_linear(mono48, 48000, 16000)
    return _np_to_pcm_s16(mono16)


def make_test_tone_pcm24(duration_s: float = 0.55, freq: float = 880.0) -> bytes:
    sr = 24000
    t = np.linspace(0.0, duration_s, int(sr * duration_s), endpoint=False)
    tone = 0.25 * np.sin(2.0 * math.pi * freq * t)
    fade = min(600, tone.size // 4)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade)
        tone[:fade] *= ramp
        tone[-fade:] *= ramp[::-1]
    return _np_to_pcm_s16(tone.astype(np.float32))


@dataclass
class DiscordBridgeConfig:
    token: str
    guild_id: Optional[int]
    voice_channel_id: Optional[int]
    text_channel_id: Optional[int]
    user_id: Optional[int]
    test_beep_on_join: bool
    debug_audio: bool
    presence_ai_greetings: bool
    presence_announce_join: bool
    presence_announce_leave: bool
    presence_cooldown_seconds: int
    enable_input: bool
    listen_all_users: bool
    listen_user_id: Optional[int]

    @classmethod
    def load(cls) -> "DiscordBridgeConfig":
        return cls(
            token=_cfg("discord_bot_token", ""),
            guild_id=_to_int(_cfg("discord_guild_id", "")),
            voice_channel_id=_to_int(_cfg("discord_voice_channel_id", "")),
            text_channel_id=_to_int(_cfg("discord_text_channel_id", "")),
            user_id=_to_int(_cfg("discord_user_id", "")),
            test_beep_on_join=_cfg_bool("discord_test_beep_on_join", True),
            debug_audio=_cfg_bool("discord_debug_audio", True),
            presence_ai_greetings=_cfg_bool("discord_presence_ai_greetings", True),
            presence_announce_join=_cfg_bool("discord_presence_announce_join", True),
            presence_announce_leave=_cfg_bool("discord_presence_announce_leave", True),
            presence_cooldown_seconds=max(10, _cfg_int("discord_presence_cooldown_seconds", 120)),
            enable_input=_cfg_bool("discord_enable_input", False),
            listen_all_users=_cfg_bool("discord_listen_all_users", False),
            listen_user_id=_to_int(_cfg("discord_listen_user_id", "")),
        )


class QueuePCMSourceBase:
    FRAME_BYTES = 3840  # 20ms @ 48kHz stereo s16
    MAX_BUFFER_BYTES = 768 * 1024  # ~4s @ 48kHz stereo s16
    TRIM_BUFFER_BYTES = 384 * 1024  # ~2s: conserva continuidad antes de recortar atraso extremo
    PREBUFFER_BYTES = FRAME_BYTES * 12  # ~240ms: absorbe jitter de red/API sin entrecortar

    def __init__(self, on_drained: Optional[Callable[[], None]] = None):
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._closed = False
        self._on_drained = on_drained
        self._last_drain_notice = 0.0
        self._last_high_buffer_notice = 0.0
        self._priming = True

    def enqueue_gemini_pcm24(self, pcm24: bytes) -> int:
        pcm48 = gemini_pcm24_mono_to_discord_pcm48_stereo(pcm24)
        if not pcm48:
            return self.buffered_bytes
        with self._lock:
            self._buf.extend(pcm48)
            if len(self._buf) >= self.PREBUFFER_BYTES:
                self._priming = False
            if len(self._buf) > self.MAX_BUFFER_BYTES:
                keep = min(len(self._buf), self.TRIM_BUFFER_BYTES)
                del self._buf[: len(self._buf) - keep]
                now = time.time()
                if now - self._last_high_buffer_notice > 3.0:
                    self._last_high_buffer_notice = now
                    print("[Discord] Buffer alto, descartando audio viejo para evitar atraso.")
            return len(self._buf)

    def read_frame(self) -> bytes:
        if self._closed:
            return b""
        with self._lock:
            if self._priming and len(self._buf) < self.PREBUFFER_BYTES:
                return b"\x00" * self.FRAME_BYTES
            if len(self._buf) >= self.FRAME_BYTES:
                out = bytes(self._buf[: self.FRAME_BYTES])
                del self._buf[: self.FRAME_BYTES]
                return out
            self._priming = True
        now = time.time()
        if self._on_drained and now - self._last_drain_notice > 60.0:
            self._last_drain_notice = now
            try:
                self._on_drained()
            except Exception:
                pass
        return b"\x00" * self.FRAME_BYTES

    def cleanup(self):
        self._closed = True
        with self._lock:
            self._buf.clear()

    def clear(self):
        with self._lock:
            self._buf.clear()
            self._priming = True

    @property
    def buffered_bytes(self) -> int:
        with self._lock:
            return len(self._buf)


class HelenaDiscordBridge:
    def __init__(
        self,
        on_audio_16k: Callable[[bytes], None],
        on_status: Optional[Callable[[str], None]] = None,
        on_presence_event: Optional[Callable[[dict], None]] = None,
    ):
        self.on_audio_16k = on_audio_16k
        self.on_status = on_status or print
        self.on_presence_event = on_presence_event
        self.config = DiscordBridgeConfig.load()
        self.client = None
        self.voice_client = None
        self.audio_source = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.started = threading.Event()
        self.ready = threading.Event()
        self.running = False
        self._out_chunks = 0
        self._last_out_log = 0.0
        self._last_player_done = 0.0
        self._played_test_beep = False
        self.output_muted = False
        self._last_mute_log = 0.0
        self._presence_cooldowns: dict[str, float] = {}
        self._source_cls = None
        self._recv_voice = None
        self._recv_sink = None
        self._recv_available = False
        self._recv_enabled = False
        self._recv_chunks = 0
        self._last_recv_log = 0.0
        self._op_lock = threading.RLock()
        self._shutting_down = False
        self._last_join_attempt = 0.0
        self.target_alias: str = ""
        self.target_voice_channel_id: Optional[int] = None
        self.target_label: str = "La Taberna de Aden"
        # V35_9_2: Voice priority tracking
        self._voice_active = False
        self._voice_active_lock = threading.RLock()
        
        # V35_9_4: Voice active auto-clear protection
        self._last_voice_chunk_time = 0.0
        self._voice_active_auto_clear_timeout = 3.0  # seconds

    def log(self, msg: str) -> None:
        try:
            self.on_status(msg)
        except Exception:
            print(msg)

    # V35_9_2: Voice priority functions
    def set_voice_active(self, active: bool) -> None:
        """Set Helena voice active state for audio priority."""
        with self._voice_active_lock:
            if self._voice_active != active:
                self._voice_active = active
                self.log(f"[DiscordBridge] Helena voice active={active}")
                # V35_9_2_FIX: Don't clear buffer - let music gate handle pausing
                # Clearing buffer causes audio skips and frame jumps

    def is_voice_active(self) -> bool:
        """Check if Helena voice is currently active."""
        with self._voice_active_lock:
            return self._voice_active
    
    def check_and_auto_clear_voice_active(self) -> None:
        """V35_9_4: Auto-clear voice_active if stuck (no voice chunks for timeout)."""
        with self._voice_active_lock:
            if self._voice_active:
                now = time.time()
                idle_time = now - self._last_voice_chunk_time
                if idle_time > self._voice_active_auto_clear_timeout:
                    self._voice_active = False
                    self.log(f"[DiscordBridge] voice_active auto-clear after {idle_time:.1f}s idle")
    
    def get_output_buffer_size(self) -> int:
        """V35_9_5: Get current output buffer size in bytes."""
        if self.audio_source:
            try:
                return self.audio_source.buffered_bytes
            except Exception:
                return 0
        return 0
    
    def is_output_buffer_safe_for_music(self, max_bytes: int = 220000) -> bool:
        """V35_9_5: Check if output buffer is safe for music resume."""
        buffer_size = self.get_output_buffer_size()
        return buffer_size <= max_bytes


    def _member_display_name(self, member) -> str:
        try:
            return str(getattr(member, "display_name", None) or getattr(member, "name", None) or member)
        except Exception:
            return "alguien"

    def _current_channel_members(self) -> list[str]:
        try:
            vc = self.voice_client
            channel = getattr(vc, "channel", None)
            members = list(getattr(channel, "members", []) or [])
            names = []
            for m in members:
                try:
                    if getattr(m, "bot", False):
                        continue
                    names.append(self._member_display_name(m))
                except Exception:
                    pass
            return names
        except Exception:
            return []

    def _should_accept_voice_user(self, user) -> bool:
        try:
            if user is None:
                return False
            if getattr(user, "bot", False):
                return False
            if self.client and getattr(user, "id", None) == getattr(getattr(self.client, "user", None), "id", None):
                return False
            if self.config.listen_all_users:
                return True
            target_id = self.config.listen_user_id or self.config.user_id
            return bool(target_id and getattr(user, "id", None) == target_id)
        except Exception:
            return False

    def _handle_discord_voice_pcm48(self, user, pcm48: bytes) -> None:
        if not self._should_accept_voice_user(user):
            return
        pcm16 = discord_pcm48_stereo_to_gemini_pcm16(pcm48)
        if not pcm16:
            return
        try:
            self.on_audio_16k(pcm16)
            self._recv_chunks += 1
            now = time.time()
            if self.config.debug_audio and (self._recv_chunks == 1 or now - self._last_recv_log > 8.0):
                self._last_recv_log = now
                name = self._member_display_name(user)
                mode = "todos" if self.config.listen_all_users else "Leo"
                self.log(f"[Discord] 🎙️ Audio recibido desde Discord ({mode}): {name}, chunk #{self._recv_chunks}, bytes16={len(pcm16)}.")
        except Exception as exc:
            now = time.time()
            if now - self._last_recv_log > 3.0:
                self._last_recv_log = now
                self.log(f"[Discord] ⚠️ No pude enviar audio recibido a Gemini: {exc}")

    def describe_members(self) -> str:
        names = self._current_channel_members()
        if not self.is_voice_connected():
            return "Todavía no estoy conectada a un canal de voz."
        channel = getattr(getattr(self.voice_client, "channel", None), "name", "el canal")
        if not names:
            return f"Estoy en {channel}, pero no veo usuarios humanos conectados ahora."
        if len(names) == 1:
            return f"En {channel} veo a: {names[0]}."
        return f"En {channel} veo a: " + ", ".join(names[:-1]) + f" y {names[-1]}."

    def set_output_muted(self, muted: bool) -> bool:
        self.output_muted = bool(muted)
        if self.output_muted:
            try:
                if self.audio_source:
                    self.audio_source.clear()
            except Exception:
                pass
            try:
                if self.voice_client and self.voice_client.is_playing():
                    self.voice_client.stop()
            except Exception:
                pass
        # Intento marcar self-mute real en Discord también, pero el mute interno es la protección principal.
        if self.loop and self.loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._set_self_mute_async(self.output_muted), self.loop)
            try:
                fut.result(timeout=5)
            except Exception as exc:
                self.log(f"[Discord] ⚠️ No pude cambiar self-mute real, uso mute interno: {exc}")
        if not self.output_muted:
            self._call_soon(self._ensure_player_async())
        self.log("[Discord] 🔇 Helena muteada en Discord." if self.output_muted else "[Discord] 🔊 Helena desmuteada en Discord.")
        return True

    async def _set_self_mute_async(self, muted: bool):
        if self.voice_client and self.voice_client.is_connected():
            channel = getattr(self.voice_client, "channel", None)
            guild = getattr(channel, "guild", None)
            if guild and channel:
                await guild.change_voice_state(channel=channel, self_mute=bool(muted), self_deaf=False)

    def is_output_muted(self) -> bool:
        return bool(self.output_muted)

    async def _handle_voice_state_update(self, member, before, after):
        """Detecta entradas/salidas del canal actual sin escuchar audio."""
        try:
            self.config = DiscordBridgeConfig.load()
            if not self.config.presence_ai_greetings:
                return
            if not self.is_voice_connected():
                return
            if getattr(member, "bot", False):
                return
            if self.client and getattr(member, "id", None) == getattr(getattr(self.client, "user", None), "id", None):
                return
            # No generar saludo automático cuando entra Leo/Zadkiel.
            # Eso evitaba respuestas autónomas innecesarias justo después de entrar a Discord.
            if self.config.user_id and getattr(member, "id", None) == self.config.user_id:
                return

            current_id = self._current_voice_channel_id()
            before_ch = getattr(before, "channel", None)
            after_ch = getattr(after, "channel", None)
            before_id = getattr(before_ch, "id", None)
            after_id = getattr(after_ch, "id", None)
            if not current_id:
                return

            event = None
            channel = None
            if self.config.presence_announce_join and after_id == current_id and before_id != current_id:
                event = "join"
                channel = after_ch
            elif self.config.presence_announce_leave and before_id == current_id and after_id != current_id:
                event = "leave"
                channel = before_ch
            else:
                return

            name = self._member_display_name(member)
            cooldown_key = f"{event}:{getattr(member, 'id', name)}"
            now = time.time()
            last = self._presence_cooldowns.get(cooldown_key, 0.0)
            if now - last < self.config.presence_cooldown_seconds:
                return
            self._presence_cooldowns[cooldown_key] = now

            channel_name = getattr(channel, "name", "el canal")
            msg = f"[Discord] 👋 Detecté que {name} {'entró a' if event == 'join' else 'salió de'} {channel_name}."
            self.log(msg)

            payload = {
                "type": event,
                "user_name": name,
                "channel_name": channel_name,
                "guild_name": getattr(getattr(channel, "guild", None), "name", "Discord"),
                "members": self._current_channel_members(),
                "muted": self.output_muted,
            }
            if self.output_muted:
                self.log("[Discord] 🔇 Estoy muteada; registro el evento pero no lo digo en voz.")
                return
            if self.on_presence_event:
                try:
                    self.on_presence_event(payload)
                except Exception as exc:
                    self.log(f"[Discord] ⚠️ Error enviando evento de presencia a Helena: {exc}")
        except Exception as exc:
            self.log(f"[Discord] ⚠️ Error procesando presencia de voz: {exc}")

    def _resolve_target_channel_id(self, target: str = "") -> tuple[Optional[int], str]:
        """Devuelve (channel_id, label). Sin target usa el canal principal de La Taberna."""
        self.config = DiscordBridgeConfig.load()
        raw_target = str(target or "").strip()
        norm = _normalize_alias(raw_target)

        # Sin destino explícito: canal principal configurado.
        if not norm or norm in ("home", "default", "principal", "taberna", "la taberna", "la taberna de aden", "aden", "mi servidor"):
            return self.config.voice_channel_id, "La Taberna de Aden"

        # Si el usuario o el LLM pasa directamente un ID numérico.
        direct = _to_int(raw_target)
        if direct:
            confirmed = {self.config.voice_channel_id}
            for value in BUILTIN_ALLOWED_VOICE_CHANNEL_IDS.values():
                cid = _to_int(value)
                if cid:
                    confirmed.add(cid)
            for mapping_name in (
                "discord_fallback_channels",
                "discord_voice_channels",
                "discord_known_voice_channels",
                "discord_allowed_voice_channel_ids",
            ):
                for value in _cfg_mapping(mapping_name).values():
                    cid = _to_int(value)
                    if cid:
                        confirmed.add(cid)
            if direct in confirmed:
                return direct, raw_target
            self.log("[Discord] Target numérico rechazado: no está confirmado como canal de voz.")
            return self.config.voice_channel_id, "La Taberna de Aden"

        aliases: dict[str, str] = {}
        aliases.update({_normalize_alias(key): value for key, value in BUILTIN_ALLOWED_VOICE_CHANNEL_IDS.items()})
        for mapping_name in (
            "discord_fallback_channels",
            "discord_voice_channels",
            "discord_known_voice_channels",
            "discord_allowed_voice_channel_ids",
        ):
            for key, value in _cfg_mapping(mapping_name).items():
                aliases[_normalize_alias(key)] = str(value).strip()

        # Aliases de seguridad para el canal de Martín/Tincho/Simio.
        # Si están en config/api_keys.json, prevalecen; si no, no inventamos IDs.
        for key in ("martin", "tincho", "simio", "privado"):
            if key in aliases and key in norm:
                cid = _to_int(aliases[key])
                if cid:
                    return cid, key

        for key, value in aliases.items():
            if key and key in norm:
                cid = _to_int(value)
                if cid:
                    return cid, key

        # Fallback: si pidió algo desconocido, no cambiamos de canal.
        return self.config.voice_channel_id, "La Taberna de Aden"

    def set_target(self, target: str = "") -> None:
        self.target_alias = str(target or "").strip()
        cid, label = self._resolve_target_channel_id(self.target_alias)
        self.target_voice_channel_id = cid
        self.target_label = label or "La Taberna de Aden"
        if self.target_alias:
            self.log(f"[Discord] Canal solicitado: {self.target_alias} → {self.target_label} ({self.target_voice_channel_id})")

    def _desired_voice_channel_id(self) -> Optional[int]:
        return self.target_voice_channel_id or self.config.voice_channel_id

    def _current_voice_channel_id(self) -> Optional[int]:
        try:
            return getattr(getattr(self.voice_client, "channel", None), "id", None)
        except Exception:
            return None

    def is_on_requested_channel(self) -> bool:
        desired = self._desired_voice_channel_id()
        return bool(self.is_voice_connected() and desired and self._current_voice_channel_id() == desired)

    def is_voice_connected(self) -> bool:
        try:
            return bool(self.voice_client and self.voice_client.is_connected())
        except Exception:
            return False

    def start(self, target: str = "") -> None:
        with self._op_lock:
            self.config = DiscordBridgeConfig.load()
            self.set_target(target)
            if not self.config.token:
                raise RuntimeError("Falta discord_bot_token en config/api_keys.json o variable DISCORD_BOT_TOKEN.")

            # Ya conectado: si el destino es distinto, mover; si no, solo asegurar player.
            if self.is_voice_connected():
                if not self.is_on_requested_channel() and self.loop and self.loop.is_running():
                    self.log("[Discord] Ya estoy en voz, pero en otro canal. Me muevo al canal solicitado...")
                    fut = asyncio.run_coroutine_threadsafe(self._ensure_joined(), self.loop)
                    try:
                        fut.result(timeout=18)
                    except Exception as exc:
                        self.log(f"[Discord] ⚠️ No pude moverme al canal solicitado todavía: {exc}")
                    return
                self.ready.set()
                self.log(f"[Discord] Bot ya conectado al canal de voz correcto: {self.target_label}.")
                self._call_soon(self._ensure_player_async())
                return

            # Bot corriendo pero sin canal: reintentar join.
            if self.running and self.loop and self.loop.is_running() and self.client:
                now = time.time()
                if now - self._last_join_attempt < 3.0:
                    self.log("[Discord] Ya estoy procesando una entrada a Discord; evito repetir orden.")
                    return
                self._last_join_attempt = now
                self.log("[Discord] Bot iniciado. Reintentando entrada al canal de voz...")
                fut = asyncio.run_coroutine_threadsafe(self._ensure_joined(), self.loop)
                try:
                    fut.result(timeout=18)
                except Exception as exc:
                    self.log(f"[Discord] ⚠️ No pude reentrar al canal todavía: {exc}")
                return

            # Si quedó un hilo muerto, limpiar flags.
            if self.thread and not self.thread.is_alive():
                self.running = False
                self.ready.clear()
                self.thread = None

            self.ready.clear()
            self.started.clear()
            self._shutting_down = False
            self.running = True
            self.thread = threading.Thread(target=self._thread_main, name="HelenaDiscordBridgeV30", daemon=True)
            self.thread.start()
            self.started.wait(timeout=10)
            self.log("[Discord] Bridge V30 iniciado. Esperando on_ready del bot...")
            self.ready.wait(timeout=20)
            if not self.ready.is_set():
                self.log("[Discord] ⚠️ El bot inició, pero todavía no confirmó entrada al canal de voz.")
                if not (self.thread and self.thread.is_alive()):
                    self.log("[Discord] ⚠️ El hilo del bot ya terminó: el login falló. Probablemente el token es inválido/expirado (discord_bot_token en config/api_keys.json). Resetéalo en el Developer Portal de Discord.")

    def _call_soon(self, coro):
        if self.loop and self.loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        return None

    def _thread_main(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.started.set()
        try:
            self.loop.run_until_complete(self._run_bot())
        finally:
            self.running = False
            self.ready.clear()
            try:
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            try:
                self.loop.close()
            except Exception:
                pass

    def _on_source_drained(self) -> None:
        now = time.time()
        if self.config.debug_audio and now - self._last_player_done > 60.0:
            self._last_player_done = now
            self.log("[Discord] 🔇 Player en espera. Sin audio pendiente; sigo conectado.")

    async def _run_bot(self) -> None:
        try:
            import discord
        except Exception as exc:
            self.running = False
            self.log(f"[Discord] ❌ Falta discord.py. Instalá requirements_discord.txt. Detalle: {exc}")
            return
        try:
            from discord.ext import voice_recv
            self._recv_voice = voice_recv
            self._recv_available = True
        except Exception:
            self._recv_voice = None
            self._recv_available = False

        class DiscordQueuePCMSource(discord.AudioSource):
            def __init__(self, on_drained=None):
                super().__init__()
                self._base = QueuePCMSourceBase(on_drained=on_drained)

            def is_opus(self) -> bool:
                return False

            def enqueue_gemini_pcm24(self, pcm: bytes) -> int:
                return self._base.enqueue_gemini_pcm24(pcm)

            def read(self) -> bytes:
                return self._base.read_frame()

            def cleanup(self) -> None:
                self._base.cleanup()

            def clear(self) -> None:
                self._base.clear()

            @property
            def buffered_bytes(self) -> int:
                return self._base.buffered_bytes

        self._source_cls = DiscordQueuePCMSource
        self.audio_source = self._source_cls(on_drained=self._on_source_drained)

        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True

        bridge = self

        class HelenaDiscordClient(discord.Client):
            async def on_ready(self):
                bridge.log(f"[Discord] ✅ Bot conectado como {self.user}")
                joined = await bridge._ensure_joined()
                if joined:
                    try:
                        from actions.discord_music import get_music_player
                        get_music_player().set_bridge(bridge)
                    except Exception as exc:
                        bridge.log(f"[Discord] ⚠️ No pude inicializar el reproductor musical: {exc}")

            async def on_voice_state_update(self, member, before, after):
                await bridge._handle_voice_state_update(member, before, after)

            async def on_interaction(self, interaction):
                try:
                    custom_id = None
                    if interaction.data:
                        custom_id = interaction.data.get("custom_id")
                    print(f"[DiscordMusicUI] interaction received: type={interaction.type} custom_id={custom_id} user={interaction.user} channel={interaction.channel_id}")
                    
                    # Route music button interactions
                    if custom_id and custom_id.startswith("helena_music_"):
                        print(f"[DiscordMusicUI] routing button custom_id={custom_id}")
                        
                        # ACK silently (no ephemeral message for successful actions)
                        if not interaction.response.is_done():
                            await interaction.response.defer(thinking=False)
                            print("[DiscordMusicUI] ack sent (silent)")
                        
                        # Import music player module
                        try:
                            import sys
                            import os
                            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                            from actions.discord_music import get_music_player_instance
                            
                            # Get music player instance
                            player = get_music_player_instance()
                            if not player:
                                result = "Reproductor de música no iniciado."
                                await interaction.followup.send(result, ephemeral=True)
                            else:
                                # Map custom_id to action
                                action = custom_id.replace("helena_music_", "")
                                result = player.handle_button_action(action)
                                
                                print(f"[DiscordMusicUI] button action completed silently: {action}")
                                
                                # Only send followup for errors or special cases (e.g., playlist)
                                if result.startswith("Error") or action in ["queue", "playlist"]:
                                    print(f"[DiscordMusicUI] sending followup for: {action}")
                                    await interaction.followup.send(result, ephemeral=True)
                                else:
                                    print(f"[DiscordMusicUI] panel updated after button: {action}")
                        except Exception as e:
                            print(f"[DiscordMusicUI] route error: {repr(e)}")
                            print(traceback.format_exc())
                            try:
                                await interaction.followup.send("Error en botón de música. Revisá consola.", ephemeral=True)
                            except:
                                pass
                except Exception as e:
                    print("[DiscordMusicUI] interaction debug error:", repr(e))

        self.client = HelenaDiscordClient(intents=intents)
        try:
            await self.client.start(self.config.token)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if not self._shutting_down:
                self.log(f"[Discord] ❌ Error del bot: {exc}")
        finally:
            self.running = False
            self.ready.clear()

    async def _resolve_voice_channel(self):
        if not self.client:
            raise RuntimeError("Cliente Discord no inicializado.")
        channel_id = self._desired_voice_channel_id()
        if not channel_id:
            raise RuntimeError("V30 requiere discord_voice_channel_id fijo o alias válido en config/api_keys.json.")

        guild = None
        channel = None

        # Si hay guild_id explícito, se intenta primero ahí.
        if self.config.guild_id:
            guild = self.client.get_guild(self.config.guild_id)
            if guild is not None:
                channel = guild.get_channel(channel_id)

        # Si no hay guild o el canal no pertenece a ese guild, resolver por ID global.
        if channel is None:
            try:
                channel = self.client.get_channel(channel_id)
            except Exception:
                channel = None
        if channel is None:
            channel = await self.client.fetch_channel(channel_id)

        # Muy importante para múltiples servidores: el guild real es el del canal solicitado.
        real_guild = getattr(channel, "guild", None)
        if real_guild is not None:
            guild = real_guild

        if guild is None:
            if self.client.guilds:
                guild = self.client.guilds[0]
            else:
                raise RuntimeError("El bot no está dentro de ningún servidor de Discord.")
        return guild, channel

    async def _disconnect_all_voice_clients(self, reason: str = "cleanup") -> None:
        """Desconecta cualquier voice_client viejo para evitar quedar en dos canales/servidores."""
        clients = []
        try:
            if self.voice_client:
                clients.append(self.voice_client)
        except Exception:
            pass
        try:
            if self.client:
                for vc in getattr(self.client, "voice_clients", []) or []:
                    if vc and vc not in clients:
                        clients.append(vc)
        except Exception:
            pass
        for vc in clients:
            try:
                if hasattr(vc, "stop_listening") and vc.is_listening():
                    vc.stop_listening()
            except Exception:
                pass
            try:
                if vc.is_playing():
                    vc.stop()
            except Exception:
                pass
            try:
                if vc.is_connected():
                    await vc.disconnect(force=True)
            except Exception as exc:
                self.log(f"[Discord] ⚠️ Limpieza de voz ({reason}) falló parcialmente: {exc}")
        self.voice_client = None
        self._recv_enabled = False
        self._recv_sink = None
        self.ready.clear()
        self._reset_audio_source(clear_counter=True)
        await asyncio.sleep(0.8)

    async def _connect_fresh(self, guild, channel, reason: str = "join") -> bool:
        await self._disconnect_all_voice_clients(reason=reason)
        self.log(f"[Discord] Intentando entrar a: {guild.name} / {channel.name}")
        connect_kwargs = {"self_deaf": False, "self_mute": False, "timeout": 20, "reconnect": True}
        if self.config.enable_input and self._recv_voice is not None:
            connect_kwargs["cls"] = self._recv_voice.VoiceRecvClient
        self.voice_client = await channel.connect(**connect_kwargs)
        try:
            await guild.change_voice_state(channel=channel, self_mute=False, self_deaf=False)
        except Exception:
            pass
        self._reset_audio_source(clear_counter=False)
        self._ensure_player()
        self._ensure_receiver()
        self.ready.set()
        if self._recv_enabled:
            mode = "todo el canal" if self.config.listen_all_users else "solo Leo"
            self.log(f"[Discord] 🟢 Modo Discord full-duplex activo: escucha {mode} y responde por Discord.")
        else:
            self.log("[Discord] 🟢 Modo híbrido V30 activo: Discord SOLO salida. Entrada por micrófono local del programa.")
        self.log(f"[Discord] 🎧 Helena entró a: {guild.name} / {channel.name}")
        if self.config.test_beep_on_join and not self._played_test_beep:
            self._played_test_beep = True
            self.log("[Discord] 🔔 Enviando tono corto de prueba. Si lo escuchás, la salida de audio funciona.")
            self.enqueue_output_audio(make_test_tone_pcm24())
        return True

    async def _ensure_joined(self) -> bool:
        self.config = DiscordBridgeConfig.load()
        try:
            guild, channel = await self._resolve_voice_channel()
            desired_id = getattr(channel, "id", None)
            desired_guild_id = getattr(guild, "id", None)

            if self.is_voice_connected():
                current_channel = getattr(self.voice_client, "channel", None)
                current_id = getattr(current_channel, "id", None)
                current_guild = getattr(current_channel, "guild", None)
                current_guild_id = getattr(current_guild, "id", None)

                if desired_id and current_id != desired_id:
                    self.log(f"[Discord] 🔁 Cambiando canal de Helena: {getattr(current_channel, 'name', '-')} → {channel.name}")
                    # Si cambia de servidor/guild, move_to no es confiable: desconectar y conectar limpio.
                    if current_guild_id and desired_guild_id and current_guild_id != desired_guild_id:
                        self.log("[Discord] 🧹 Cambio entre servidores detectado; hago disconnect → connect limpio.")
                        return await self._connect_fresh(guild, channel, reason="cross_guild_move")
                    try:
                        if self.voice_client.is_playing():
                            self.voice_client.stop()
                    except Exception:
                        pass
                    try:
                        await asyncio.wait_for(self.voice_client.move_to(channel), timeout=10)
                        try:
                            await guild.change_voice_state(channel=channel, self_mute=False, self_deaf=False)
                        except Exception:
                            pass
                        await asyncio.sleep(0.4)
                        if self._current_voice_channel_id() != desired_id:
                            self.log("[Discord] ⚠️ move_to no confirmó el canal; reconecto limpio.")
                            return await self._connect_fresh(guild, channel, reason="move_verify_failed")
                        self._reset_audio_source(clear_counter=True)
                        self._ensure_player()
                        self._ensure_receiver()
                        self.ready.set()
                        self.log(f"[Discord] ✅ Helena cambió de canal a: {guild.name} / {channel.name}")
                        return True
                    except Exception as exc:
                        self.log(f"[Discord] ⚠️ move_to falló ({exc}); reconecto limpio.")
                        return await self._connect_fresh(guild, channel, reason="move_to_failed")

                self.ready.set()
                self._ensure_player()
                self._ensure_receiver()
                self.log(f"[Discord] Bot ya conectado al canal de voz correcto: {self.target_label}.")
                return True

            # Antes de entrar, limpiar cualquier cliente de voz viejo que haya quedado vivo.
            return await self._connect_fresh(guild, channel, reason="join")
        except Exception as exc:
            self.ready.clear()
            self.log(f"[Discord] ❌ No pude entrar/cambiar al canal de voz: {exc}")
            return False

    def _reset_audio_source(self, clear_counter: bool = True) -> None:
        try:
            if self.audio_source:
                self.audio_source.cleanup()
        except Exception:
            pass
        if self._source_cls:
            self.audio_source = self._source_cls(on_drained=self._on_source_drained)
        if clear_counter:
            self._out_chunks = 0

    def _ensure_player(self) -> None:
        if not self.voice_client or not self.voice_client.is_connected():
            return
        try:
            if self.voice_client.is_playing():
                return
        except Exception:
            pass
        if self.audio_source is None:
            self._reset_audio_source(clear_counter=False)
        try:
            self.voice_client.play(self.audio_source, after=self._player_after)
            self.log("[Discord] 🔊 Player de Discord iniciado para reproducir audio real.")
        except Exception as exc:
            self.log(f"[Discord] ⚠️ No pude iniciar player de Discord: {exc}")

    def _ensure_receiver(self) -> None:
        self.config = DiscordBridgeConfig.load()
        self._recv_enabled = False
        if not self.config.enable_input:
            return
        if self._recv_voice is None:
            self.log("[Discord] ⚠️ Entrada de audio Discord pedida, pero falta discord-ext-voice-recv. Mantengo modo híbrido local.")
            return
        if not self.voice_client or not self.voice_client.is_connected():
            return
        if not hasattr(self.voice_client, "listen"):
            self.log("[Discord] ⚠️ Este voice client no soporta recepción de audio. Reconectá Discord tras instalar discord-ext-voice-recv.")
            return
        try:
            if hasattr(self.voice_client, "is_listening") and self.voice_client.is_listening():
                self._recv_enabled = True
                return
        except Exception:
            pass

        bridge = self
        voice_recv = self._recv_voice

        class HelenaReceiveSink(voice_recv.AudioSink):
            def wants_opus(self) -> bool:
                return False

            def write(self, user, data) -> None:
                pcm = getattr(data, "pcm", None)
                if pcm:
                    bridge._handle_discord_voice_pcm48(user, pcm)

            def cleanup(self) -> None:
                pass

        try:
            self._recv_sink = HelenaReceiveSink()
            self.voice_client.listen(self._recv_sink)
            self._recv_enabled = True
            mode = "todos los usuarios" if self.config.listen_all_users else "usuario configurado"
            self.log(f"[Discord] 🎙️ Entrada de voz Discord activa: escuchando {mode}.")
        except Exception as exc:
            self._recv_enabled = False
            self.log(f"[Discord] ⚠️ No pude activar recepción de voz Discord: {exc}")

    def _player_after(self, error) -> None:
        if error and not self._shutting_down:
            self.log(f"[Discord] Player terminó con error: {error}")

    async def _ensure_player_async(self):
        self._ensure_player()

    def enqueue_output_audio(self, pcm24: bytes, source: str = "voice") -> bool:
        """Enqueue audio chunk with source priority (voice or music)."""
        if self.output_muted:
            now = time.time()
            if now - self._last_mute_log > 4.0:
                self._last_mute_log = now
                self.log("[Discord] 🔇 Audio bloqueado: Helena está muteada en Discord.")
            return False
        if not self.voice_client or not self.voice_client.is_connected():
            return False
        
        # V35_9_4: Track last voice chunk time for auto-clear protection
        if source == "voice":
            self._last_voice_chunk_time = time.time()
        
        # V35_9_4: Check and auto-clear voice_active if stuck (throttled to once per second)
        now = time.time()
        if now - self._last_out_log > 1.0:
            self.check_and_auto_clear_voice_active()
        
        # V35_9_4: Music gating is now handled BEFORE reading FFmpeg in discord_music.py
        # No need to drop chunks here - music player pauses reading when voice is active
        
        if self.audio_source is None:
            self._reset_audio_source(clear_counter=False)
        buffered = self.audio_source.enqueue_gemini_pcm24(pcm24)
        self._out_chunks += 1
        if self.config.debug_audio and (self._out_chunks == 1 or now - self._last_out_log > 8.0):
            self._last_out_log = now
            self.log(f"[DiscordBridge] enqueue {source} chunk, buffer={buffered} bytes")
        self._ensure_player()
        return True

    def play_test_tone(self) -> bool:
        if not self.voice_client or not self.voice_client.is_connected():
            return False
        self.log("[Discord] 🔔 Prueba manual: enviando tono a Discord.")
        return self.enqueue_output_audio(make_test_tone_pcm24())

    def leave(self) -> None:
        if not self.loop or not self.loop.is_running():
            self.ready.clear()
            self.voice_client = None
            return
        fut = asyncio.run_coroutine_threadsafe(self._leave_async(), self.loop)
        try:
            fut.result(timeout=10)
        except Exception as exc:
            self.log(f"[Discord] ⚠️ Error saliendo de Discord: {exc}")

    async def _leave_async(self):
        try:
            if self.voice_client:
                try:
                    if hasattr(self.voice_client, "stop_listening") and self.voice_client.is_listening():
                        self.voice_client.stop_listening()
                except Exception:
                    pass
                try:
                    if self.voice_client.is_playing():
                        self.voice_client.stop()
                except Exception:
                    pass
                if self.voice_client.is_connected():
                    await self.voice_client.disconnect(force=True)
            self.voice_client = None
            self._recv_enabled = False
            self._recv_sink = None
            self.ready.clear()
            self._reset_audio_source(clear_counter=True)
            self._played_test_beep = False
            self.output_muted = False
            self.log("[Discord] 👋 Helena salió del canal de voz. El bot queda listo para volver a entrar.")
        except Exception as exc:
            self.log(f"[Discord] ⚠️ No pude salir limpiamente: {exc}")

    def shutdown(self) -> None:
        self._shutting_down = True
        self.ready.clear()
        if self.loop and self.loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._shutdown_async(), self.loop)
            try:
                fut.result(timeout=12)
            except Exception as exc:
                self.log(f"[Discord] ⚠️ Error apagando puente Discord: {exc}")
        self.running = False
        self.voice_client = None
        self.client = None
        self.output_muted = False
        self._reset_audio_source(clear_counter=True)

    async def _shutdown_async(self):
        try:
            await self._leave_async()
        except Exception:
            pass
        try:
            if self.client and not self.client.is_closed():
                await self.client.close()
        except Exception as exc:
            self.log(f"[Discord] ⚠️ No pude cerrar cliente Discord: {exc}")


    def send_text_message(self, message: str, channel_id: str = "") -> tuple[bool, str]:
        """Envía texto al canal de texto configurado sin escribir en ventanas activas."""
        message = str(message or "").strip()
        if not message:
            return False, "mensaje vacío"
        if not self.client or not self.loop or not self.loop.is_running():
            return False, "Discord no está iniciado"
        cid = _to_int(channel_id) or self.config.text_channel_id or _to_int(_cfg("discord_text_channel_id", ""))
        if not cid:
            return False, "discord_text_channel_id no configurado"
        fut = asyncio.run_coroutine_threadsafe(self._send_text_message_async(cid, message), self.loop)
        try:
            return fut.result(timeout=12)
        except Exception as exc:
            return False, str(exc)

    async def _send_text_message_async(self, channel_id: int, message: str) -> tuple[bool, str]:
        try:
            channel = None
            try:
                channel = self.client.get_channel(int(channel_id)) if self.client else None
            except Exception:
                channel = None
            if channel is None and self.client:
                channel = await self.client.fetch_channel(int(channel_id))
            if channel is None:
                return False, f"no encontré canal de texto {channel_id}"
            chunks = []
            text = str(message or "")
            while text:
                chunks.append(text[:1900])
                text = text[1900:]
            if not chunks:
                chunks = [""]
            for chunk in chunks:
                await channel.send(chunk)
            self.log(f"[Discord] 💬 Texto enviado al canal #{getattr(channel, 'name', channel_id)} ({len(chunks)} parte/s).")
            return True, f"Texto enviado a Discord en #{getattr(channel, 'name', channel_id)}."
        except Exception as exc:
            return False, str(exc)

    def debug_status(self) -> str:
        vc = self.voice_client
        connected = self.is_voice_connected()
        channel = getattr(getattr(vc, "channel", None), "name", "-") if vc else "-"
        playing = False
        try:
            playing = bool(vc and vc.is_playing())
        except Exception:
            pass
        buf = getattr(self.audio_source, "buffered_bytes", 0) if self.audio_source else 0
        client_closed = True
        try:
            client_closed = bool(self.client is None or self.client.is_closed())
        except Exception:
            pass
        members = ", ".join(self._current_channel_members()) or "sin usuarios humanos visibles"
        input_mode = "canal completo" if self.config.listen_all_users else "usuario configurado"
        input_state = "activo" if self._recv_enabled else ("pendiente/falta dependency" if self.config.enable_input else "desactivado")
        return f"Discord V30 conectado={connected}, canal={channel}, destino={self.target_label}, reproduciendo={playing}, buffer={buf}, muteado={self.output_muted}, input={input_state} ({input_mode}), miembros={members}, running={self.running}, client_closed={client_closed}."
