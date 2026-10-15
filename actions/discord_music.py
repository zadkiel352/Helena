# actions/discord_music.py - Discord Music Player for HELENA V35
# V35_DISCORD_MUSIC_PLAYER: Queue-based music playback with voice priority
# V35_1_DISCORD_MUSIC_YTDLP_RESOLVER: Added yt-dlp resolution, source validation, local file support
# V35_2_DISCORD_MUSIC_REAL_AUDIO_BRIDGE_FIX: Integrate with real Discord voice client
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from queue import Queue
import random

try:
    import discord
    from discord.ui import View, Button
    DISCORD_UI_AVAILABLE = True
except ImportError:
    DISCORD_UI_AVAILABLE = False

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
MEMORY_DIR = BASE_DIR / "memory"

_discord_music_player = None
_lock = threading.RLock()


def _log(text: str) -> None:
    message = f"[DiscordMusic] {text}"
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", errors="replace").decode("ascii"))


def _read_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        _log(f"⚠️ No pude leer config/api_keys.json: {exc}")
    return {}


def _cfg(name: str, default: str = "") -> str:
    data = _read_config()
    value = os.getenv(name.upper()) or data.get(name) or data.get(name.upper()) or default
    return str(value).strip() if value is not None else default


def _cfg_bool(name: str, default: bool = False) -> bool:
    raw = _cfg(name, "1" if default else "0").strip().lower()
    return raw not in ("0", "false", "no", "off", "apagado", "")


def _cfg_int(name: str, default: int = 0) -> int:
    try:
        return int(_cfg(name, str(default)))
    except Exception:
        return default


# Import unified music preferences module
try:
    from memory.music_preferences import (
        load_music_preferences,
        save_music_preferences,
        add_liked_artist,
        add_liked_track,
        add_liked_genre,
        add_recent_track,
        get_music_seed,
        get_music_status,
        ensure_music_preferences_file
    )
    MUSIC_PREFS_AVAILABLE = True
except ImportError:
    MUSIC_PREFS_AVAILABLE = False
    _log("[DiscordMusic] music_preferences module not available, using fallback")


def _track_source(track: MusicTrack) -> str:
    """Helper para obtener source de forma compatible con source_type."""
    return getattr(track, "source_type", None) or getattr(track, "source", "unknown")


def _apply_pcm_volume(chunk: bytes, volume_percent: int) -> bytes:
    """Aplicar volumen a chunk PCM s16le."""
    if volume_percent >= 100:
        return chunk
    if volume_percent <= 0:
        return b'\x00' * len(chunk)
    
    try:
        import struct
        # Interpretar como s16le (16-bit signed little-endian)
        samples = struct.unpack('<' + 'h' * (len(chunk) // 2), chunk)
        
        # Aplicar volumen
        factor = volume_percent / 100.0
        scaled_samples = [int(s * factor) for s in samples]
        
        # Clipping
        clipped_samples = [max(-32768, min(32767, s)) for s in scaled_samples]
        
        # Convertir de vuelta a bytes
        return struct.pack('<' + 'h' * len(clipped_samples), *clipped_samples)
    except Exception as exc:
        _log(f"[DiscordMusic] PCM volume error: {exc}")
        return chunk


def _check_ytdlp() -> bool:
    """Check if yt-dlp is available."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


@dataclass
class MusicTrack:
    url: str  # playback_url: actual URL for FFmpeg
    title: str = ""  # display_title: clean title for user display
    source: str = "url"  # url, file, ytdlp
    source_type: str = ""  # alias compatible con source
    added_by: str = "user"
    duration: Optional[float] = None  # Duration in seconds
    resolved: bool = True  # Whether the source was successfully resolved
    query: str = ""  # original search query
    http_headers: dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        """Sincronizar source y source_type para compatibilidad."""
        if not self.source_type and self.source:
            self.source_type = self.source
        elif not self.source and self.source_type:
            self.source = self.source_type


@dataclass
class DiscordMusicConfig:
    enabled: bool
    default_volume: int
    duck_volume: int
    max_queue: int
    ffmpeg_path: str
    show_text_controls: bool = False
    buttons_enabled: bool = True
    ephemeral_success_messages: bool = False
    memory_enabled: bool = True
    voice_priority_enabled: bool = True
    pause_while_helena_speaks: bool = False
    resume_buffer_max_bytes: int = 220000
    resume_after_voice_delay_ms: int = 500
    buffer_high_bytes: int = 260000
    buffer_low_bytes: int = 180000

    @classmethod
    def load(cls) -> "DiscordMusicConfig":
        return cls(
            enabled=_cfg_bool("discord_music_enabled", True),
            default_volume=_cfg_int("discord_music_default_volume", 10),
            duck_volume=_cfg_int("discord_music_duck_volume", 5),
            max_queue=_cfg_int("discord_music_max_queue", 20),
            ffmpeg_path=_cfg("ffmpeg_path", "ffmpeg"),
            show_text_controls=_cfg_bool("discord_music_show_text_controls", False),
            buttons_enabled=_cfg_bool("discord_music_buttons_enabled", True),
            ephemeral_success_messages=_cfg_bool("discord_music_ephemeral_success_messages", False),
            memory_enabled=_cfg_bool("discord_music_memory_enabled", True),
            voice_priority_enabled=_cfg_bool("discord_music_voice_priority_enabled", True),
            pause_while_helena_speaks=_cfg_bool("discord_music_pause_while_helena_speaks", True),
            resume_buffer_max_bytes=_cfg_int("discord_music_resume_buffer_max_bytes", 220000),
            resume_after_voice_delay_ms=_cfg_int("discord_music_resume_after_voice_delay_ms", 500),
            buffer_high_bytes=_cfg_int("discord_music_buffer_high_bytes", 260000),
            buffer_low_bytes=_cfg_int("discord_music_buffer_low_bytes", 180000),
        )


if DISCORD_UI_AVAILABLE:
    # Global registry to prevent garbage collection of active views
    _ACTIVE_MUSIC_VIEWS = {}
    
    # Global music player instance for button routing
    _music_player_instance = None
    
    def get_music_player_instance():
        """Get the global music player instance for button routing."""
        return _music_player_instance
    
    def set_music_player_instance(player):
        """Set the global music player instance for button routing."""
        global _music_player_instance
        _music_player_instance = player
    
    class MusicControlView(View):
        """Discord UI View with music control buttons - ACK-only diagnostic mode."""
        
        def __init__(self, music_player):
            super().__init__(timeout=3600)
            self.music_player = music_player
            self.pause_button.label = "Resume" if music_player.is_paused else "Pause"
        
        async def on_error(self, interaction: discord.Interaction, error: Exception, item):
            """Handle view errors."""
            _log(f"[DiscordMusicUI] view on_error: {repr(error)}")
            _log(traceback.format_exc())
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Error interno del botón.", ephemeral=True)
                else:
                    await interaction.followup.send("Error interno del botón.", ephemeral=True)
            except Exception as e:
                _log(f"[DiscordMusicUI] failed to report button error: {repr(e)}")
        
        @discord.ui.button(label="Vol -", style=discord.ButtonStyle.secondary, row=0, custom_id="helena_music_vol_down")
        async def volume_down(self, interaction: discord.Interaction):
            """Decrease volume by 10 - handled by global interaction router."""
            pass  # Handled by global on_interaction router
        
        @discord.ui.button(label="Pause", style=discord.ButtonStyle.primary, row=0, custom_id="helena_music_pause")
        async def pause_button(self, interaction: discord.Interaction):
            """Pause or resume playback - handled by global interaction router."""
            pass  # Handled by global on_interaction router
        
        @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, row=0, custom_id="helena_music_skip")
        async def skip(self, interaction: discord.Interaction):
            """Skip to next track - handled by global interaction router."""
            pass  # Handled by global on_interaction router
        
        @discord.ui.button(label="Vol +", style=discord.ButtonStyle.secondary, row=0, custom_id="helena_music_vol_up")
        async def volume_up(self, interaction: discord.Interaction):
            """Increase volume by 10 - handled by global interaction router."""
            pass  # Handled by global on_interaction router
        
        @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, row=0, custom_id="helena_music_stop")
        async def stop(self, interaction: discord.Interaction):
            """Stop playback and clear queue - handled by global interaction router."""
            pass  # Handled by global on_interaction router
        
        @discord.ui.button(label="Playlist", style=discord.ButtonStyle.secondary, row=1, custom_id="helena_music_playlist")
        async def playlist(self, interaction: discord.Interaction):
            """Show playlist/queue - handled by global interaction router."""
            pass  # Handled by global on_interaction router
        
        @discord.ui.button(label="Loop", style=discord.ButtonStyle.secondary, row=1, custom_id="helena_music_loop")
        async def loop(self, interaction: discord.Interaction):
            """Toggle loop mode - handled by global interaction router."""
            pass  # Handled by global on_interaction router
        
        @discord.ui.button(label="Shuffle", style=discord.ButtonStyle.secondary, row=1, custom_id="helena_music_shuffle")
        async def shuffle(self, interaction: discord.Interaction):
            """Shuffle queue - handled by global interaction router."""
            pass  # Handled by global on_interaction router
        
        @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1, custom_id="helena_music_back")
        async def back(self, interaction: discord.Interaction):
            """Play previous track - handled by global interaction router."""
            pass  # Handled by global on_interaction router


class DiscordMusicPlayer:
    def __init__(self):
        self.config = DiscordMusicConfig.load()
        self.queue: list[MusicTrack] = []
        self.current_track: Optional[MusicTrack] = None
        self.is_playing = False
        self.is_paused = False
        self.volume = self.config.default_volume
        self.ffmpeg_process: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._playback_thread: Optional[threading.Thread] = None
        self._playback_started_event = threading.Event()
        self._playback_error: Optional[str] = None
        self._bridge = None
        self._voice_client = None
        self._helena_speaking = False
        self._skip_requested = False
        self.panel_message = None  # Reference to panel message for updates
        self.panel_view = None  # Reference to panel view for updates
        self.loop_mode = False  # Loop mode for current track
        self.history: list[MusicTrack] = []  # Track history for back button
        
        # Set global instance for button routing
        if DISCORD_UI_AVAILABLE:
            set_music_player_instance(self)
    
    def handle_button_action(self, action: str) -> str:
        """Handle music button action from global interaction router."""
        try:
            _log(f"[DiscordMusicUI] handle_button_action: {action}")
            
            if action == "pause":
                if self.is_paused:
                    result = self.resume()
                else:
                    result = self.pause()
            elif action == "stop":
                result = self.stop()
            elif action == "skip":
                result = self.skip()
            elif action == "vol_down":
                result = self.volume_down()
            elif action == "vol_up":
                result = self.volume_up()
            elif action == "queue" or action == "playlist":
                result = self.queue_status()
            elif action == "loop":
                result = self.toggle_loop()
            elif action == "shuffle":
                result = self.shuffle_queue()
            elif action == "back":
                result = self.play_previous()
            else:
                result = f"Acción desconocida: {action}"
            
            _log(f"[DiscordMusicUI] handle_button_action result: {result}")
            
            # Update panel after button action (except for queue/playlist which show ephemeral)
            if action not in ["queue", "playlist"]:
                self._update_music_panel(action)
            
            return result
        except Exception as exc:
            _log(f"[DiscordMusicUI] handle_button_action error: {repr(exc)}")
            _log(traceback.format_exc())
            return "Error al ejecutar acción de botón."
    
    def _update_music_panel(self, reason: str = "unknown") -> None:
        """Update the existing music panel message."""
        if not self._bridge:
            _log(f"[DiscordMusicUI] panel update skipped: no bridge (reason: {reason})")
            return

        if not self.panel_message:
            self._send_music_panel()
            return

        try:
            if self.panel_view is not None and DISCORD_UI_AVAILABLE:
                self.panel_view.pause_button.label = "Resume" if self.is_paused else "Pause"
            panel_text = self._build_music_panel_text()

            async def update_panel():
                try:
                    await self.panel_message.edit(content=panel_text, view=self.panel_view)
                    _log(f"[DiscordMusicUI] panel updated successfully (reason: {reason})")
                except Exception as exc:
                    _log(f"[DiscordMusicUI] panel update failed: {exc}")
            
            if self._bridge.loop and self._bridge.loop.is_running():
                asyncio.run_coroutine_threadsafe(update_panel(), self._bridge.loop)
            else:
                _log("[DiscordMusicUI] panel update skipped: bridge loop not running")
        except Exception as exc:
            _log(f"[DiscordMusicUI] panel update error: {exc}")
            _log(traceback.format_exc())

    def _build_music_panel_text(self) -> str:
        display_title = self._safe_display_title(self.current_track) if self.current_track else "No track"
        queue_preview = "\n".join(
            f"{index}. {self._safe_display_title(track)}"
            for index, track in enumerate(self.queue[:5], 1)
        )
        if len(self.queue) > 5:
            queue_preview += f"\n... y {len(self.queue) - 5} más"
        if self.is_playing and not self.is_paused:
            status = "🔊 Playing"
        elif self.is_paused:
            status = "⏸️ Paused"
        else:
            status = "⏹ Stopped"

        controls_text = ""
        if self.config.show_text_controls:
            controls_text = """
Controls:
⏸ Helena, pausá la música
▶ Helena, reanudá la música
⏹ Helena, detené la música
⏭ Helena, saltá canción
🔊 Helena, volumen 50
📜 Helena, cola"""

        error_text = f"\n\nPlayback error:\n{self._playback_error}" if self._playback_error else ""

        return f"""🎵 MUSIC PANEL

Now Playing:
{display_title}

Status:
{status}

Volume:
{self.volume}%

Playlist:
{queue_preview or "La cola está vacía."}{controls_text}{error_text}"""

    def set_bridge(self, bridge) -> None:
        """Set reference to Discord bridge for voice client access."""
        self._bridge = bridge

    def set_helena_speaking(self, speaking: bool) -> None:
        """Set Helena speaking state for ducking/priority."""
        self._helena_speaking = speaking
        if speaking and self.is_playing and not self.is_paused:
            _log("[DiscordMusic] Helena voice active: ducking music")
        elif not speaking and self.is_playing:
            _log("[DiscordMusic] Helena voice inactive: restoring music volume")

    def _get_effective_volume(self) -> int:
        """Get effective volume considering ducking and voice priority."""
        if self._helena_speaking and self.config.voice_priority_enabled:
            return min(self.volume, self.config.duck_volume)
        return self.volume
    
    def _can_read_music_now(self, voice_inactive_time: float) -> tuple[bool, str]:
        """V35_9_6: Combined gate check - returns (can_read, reason)."""
        # V35_9_6: Periodic auto-clear of voice_active
        if self._bridge and hasattr(self._bridge, 'check_and_auto_clear_voice_active'):
            self._bridge.check_and_auto_clear_voice_active()
        
        # Check stop
        if self._stop_event.is_set():
            return False, "stopped"
        
        # Check manual pause
        if self.is_paused:
            return False, "manual_pause"
        
        # Check voice gate
        if self._bridge and hasattr(self._bridge, 'is_voice_active'):
            voice_active = self._bridge.is_voice_active()
            if voice_active and self.config.pause_while_helena_speaks:
                return False, "voice_active"
        
        # Check post-voice cooldown
        if voice_inactive_time > 0.0:
            cooldown_elapsed = (time.time() - voice_inactive_time) * 1000  # ms
            if cooldown_elapsed < self.config.resume_after_voice_delay_ms:
                return False, "post_voice_cooldown"
        
        # Check buffer gate with hysteresis
        if self._bridge and hasattr(self._bridge, 'get_output_buffer_size'):
            buffer_size = self._bridge.get_output_buffer_size()
            # Use hysteresis: enter high at buffer_high_bytes, exit low at buffer_low_bytes
            if hasattr(self, '_buffer_gate_state') and self._buffer_gate_state:
                # Already in buffer_high state, exit only when below low threshold
                if buffer_size > self.config.buffer_low_bytes:
                    return False, "buffer_high"
            else:
                # Not in buffer_high state, enter only when above high threshold
                if buffer_size > self.config.buffer_high_bytes:
                    return False, "buffer_high"
        
        # All checks passed
        return True, "ready"

    def _check_ffmpeg(self) -> bool:
        """Check if FFmpeg is available."""
        try:
            result = subprocess.run(
                [self.config.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
        return False

    def _sanitize_input(self, text: str) -> str:
        """Sanitize user input to prevent command injection."""
        # Remove shell metacharacters
        text = str(text or "").strip()
        text = re.sub(r'[;&|`$(){}[\]<>]', '', text)
        # Limit length
        if len(text) > 500:
            text = text[:500]
        return text

    def _is_safe_path(self, path: str) -> bool:
        """Check if path is safe (within allowed directories)."""
        try:
            resolved = Path(path).resolve()
            # Allow current directory and subdirectories
            base = Path.cwd().resolve()
            try:
                resolved.relative_to(base)
                return True
            except ValueError:
                return False
        except Exception:
            return False

    def _is_audio_file(self, path: str) -> bool:
        """Check if file has supported audio extension."""
        try:
            p = Path(path)
            return p.suffix.lower() in (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac")
        except Exception:
            return False

    def _truncate_title(self, title: str, max_length: int = 90) -> str:
        """Truncate title to max_length characters with ellipsis."""
        if not title:
            return "Unknown"
        if len(title) <= max_length:
            return title
        return title[:max_length - 3] + "..."

    def _is_url(self, text: str) -> bool:
        """Detect if text looks like a URL."""
        if not text:
            return False
        text_lower = text.lower()
        # Check for common URL patterns
        url_indicators = [
            "http://",
            "https://",
            "googlevideo.com",
            "videoplayback",
            "rr" + "---"  # Split to avoid false positive
        ]
        for indicator in url_indicators:
            if indicator in text_lower:
                return True
        return False

    def _safe_display_title(self, track: MusicTrack) -> str:
        """Get safe display title from track, never returns a URL."""
        # Try track.title first (display_title) if it exists and is not a URL
        if track.title and not self._is_url(track.title):
            return self._truncate_title(track.title)
        
        # For local files, use filename
        if track.source == "file":
            try:
                filename = Path(track.url).name
                return self._truncate_title(filename)
            except Exception:
                pass
        
        # For direct URLs without title
        if track.source == "url":
            return "URL directa de audio"
        
        # For yt-dlp without title, this shouldn't happen but handle gracefully
        if track.source == "ytdlp":
            # If track.url is not a URL (unlikely), use it as fallback
            if not self._is_url(track.url):
                return self._truncate_title(track.url)
        
        # Fallback to generic text
        return "Audio stream"

    def _resolve_query_with_ytdlp(
        self, query: str, timeout: int = 30
    ) -> tuple[Optional[str], Optional[str], Optional[float], dict[str, str]]:
        """Resolve a text search query using yt-dlp.
        Returns (playback_url, display_title, duration) or (None, None, None) if failed.
        """
        if not _check_ytdlp():
            return None, None, None, {}
        
        query = self._sanitize_input(query)
        _log(f"resolving query with yt-dlp: {query}")
        
        try:
            # Use JSON output to get complete metadata
            search_query = f"ytsearch1:{query}"
            cmd = [
                sys.executable,
                "-m",
                "yt_dlp",
                "--dump-json",
                "--format", "bestaudio/best",
                "--no-playlist",
                "--quiet",
                search_query
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                
                # Extract metadata
                playback_url = data.get("url")
                display_title = data.get("title")
                duration = data.get("duration")
                
                if playback_url:
                    _log(f"resolved title: {display_title}")
                    _log(f"resolved audio url: yes")
                    _log(f"ffmpeg input type: resolved_url")
                    _log(f"duration: {duration}s")
                    return playback_url, display_title, duration, data.get("http_headers") or {}
        except subprocess.TimeoutExpired:
            _log("yt-dlp resolution timed out")
        except json.JSONDecodeError as exc:
            _log(f"yt-dlp JSON decode failed: {exc}")
        except Exception as exc:
            _log(f"yt-dlp resolution failed: {exc}")
        
        return None, None, None, {}

    def add_to_queue(self, url: str, title: str = "") -> str:
        """Add a track to the queue with source resolution."""
        with self._lock:
            if len(self.queue) >= self.config.max_queue:
                return "La cola está llena. Esperá a que termine algún tema."
            
            url = self._sanitize_input(url)
            
            # Determine source type and resolve if needed
            source = "url"
            resolved_url = url
            display_title = title  # Use provided title if available
            resolved = True
            http_headers = {}
            
            if url.startswith(("http://", "https://")):
                source = "url"
                # For direct URLs without title, use generic display title
                if not display_title:
                    display_title = "URL directa de audio"
            elif Path(url).exists():
                if not self._is_safe_path(url):
                    return "Esa ruta no es segura. Solo uso archivos en carpetas del proyecto."
                if not self._is_audio_file(url):
                    return "Ese formato de archivo no está soportado. Usá .mp3, .wav, .ogg, .flac, .m4a o .aac."
                source = "file"
                # For local files, use filename as display title
                if not display_title:
                    display_title = Path(url).name
            else:
                # Text search - try to resolve with yt-dlp
                _log(f"text query detected, attempting resolution: {url}")
                playback_url, yt_dlp_title, duration, http_headers = self._resolve_query_with_ytdlp(url)
                if playback_url:
                    source = "ytdlp"
                    resolved_url = playback_url
                    display_title = yt_dlp_title or url  # Use yt-dlp title or fallback
                    # Store duration if available
                    if duration is not None:
                        _log(f"track duration: {duration}s")
                else:
                    resolved = False
                    if not _check_ytdlp():
                        return "Para buscar música por nombre necesito yt-dlp. Probá con un archivo local o URL directa."
                    return "No pude resolver esa búsqueda. Probá con un archivo local o URL directa."
            
            # Ensure display_title is never a URL
            if self._is_url(display_title):
                _log(f"⚠️ display_title looks like URL, replacing with safe title")
                if source == "file":
                    display_title = Path(resolved_url).name
                else:
                    display_title = "Audio stream"
            
            # Truncate display title if too long
            display_title = self._truncate_title(display_title)
            
            # Create track with duration if available
            track_duration = duration if source == "ytdlp" else None
            track = MusicTrack(
                url=resolved_url,
                title=display_title,
                source=source,
                duration=track_duration,
                resolved=resolved,
                query=url if source == "ytdlp" else "",
                http_headers=http_headers,
            )
            self.queue.append(track)
            
            # Log track metadata for debugging
            _log("track metadata:")
            _log(f"  source_type={source}")
            _log(f"  display_title={display_title}")
            _log(f"  playback_url_is_url={self._is_url(resolved_url)}")
            _log(f"  panel title={self._safe_display_title(track)}")
            if track_duration:
                _log(f"  duration={track_duration}s")
            
            _log(f"➕ Added to queue: {display_title} (source: {source}, resolved: {resolved})")
            if self.panel_message:
                self._update_music_panel("track added")
            return f"Agregué {display_title} a la cola."

    def play(self, url: str = "", title: str = "") -> str:
        """Play a track or start queue with source validation."""
        if not self.config.enabled:
            return "La música de Discord está deshabilitada en la configuración."
        
        if not self._check_ffmpeg():
            return "FFmpeg no está instalado o no está en PATH. No puedo reproducir música."
        
        # Get voice client from bridge
        if self._bridge:
            self._voice_client = getattr(self._bridge, "voice_client", None)
        
        if not self._voice_client or not getattr(self._voice_client, "is_connected", lambda: False)():
            return "No estoy conectada a Discord. Pedime que entre a Discord primero."
        
        # Check if voice client is busy with Helena's voice
        is_playing = getattr(self._voice_client, "is_playing", lambda: False)()
        if is_playing:
            # In bridge mode, is_playing is often true even when idle (keeps connection alive)
            # We use enqueue_output_audio which works with the existing player
            _log("voice_client.is_playing ignored because bridge mode is active")
        else:
            _log("voice_client.is_playing: false, bridge mode active")
        
        should_resume = False
        track_to_play = None
        with self._lock:
            if url:
                result = self.add_to_queue(url, title)
                if "agregué" not in result.lower():
                    return result
            
            if not self.queue and not self.current_track:
                return "No hay temas en la cola. Decime qué querés escuchar."
            
            if self.is_playing and not self.is_paused:
                return "Ya estoy reproduciendo música."
            
            if self.is_paused:
                should_resume = True
            else:
                # Start playing next track
                if not self.current_track and self.queue:
                    self.current_track = self.queue.pop(0)

                # Validate source before saying "Reproduciendo"
                if self.current_track:
                    if not self.current_track.resolved:
                        _log("not playing because source unsupported")
                        self.current_track = None
                        return "No pude resolver una fuente de audio reproducible."

                    if self.current_track.source not in ("file", "url", "ytdlp"):
                        _log(f"not playing because source unsupported: {self.current_track.source}")
                        self.current_track = None
                        return "No pude resolver una fuente de audio reproducible."

                    track_to_play = self.current_track
                    self._start_playback()
                    self._send_music_panel()
                else:
                    return "No pude iniciar la reproducción."

        if should_resume:
            return self.resume()

        if not self._playback_started_event.wait(timeout=20):
            return "La fuente todavía no entregó audio; no puedo confirmar que esté sonando."
        if self._playback_error:
            return f"No pude reproducir el tema: {self._playback_error}"

        if track_to_play and self.config.memory_enabled and MUSIC_PREFS_AVAILABLE:
            add_recent_track(
                title=track_to_play.title,
                query=getattr(track_to_play, "query", ""),
                source=_track_source(track_to_play)
            )

        display_title = self._safe_display_title(track_to_play) if track_to_play else "el tema"
        return f"Reproduciendo: {display_title}"

    def pause(self) -> str:
        """Pause current playback."""
        with self._lock:
            if not self.is_playing:
                return "No estoy reproduciendo música."
            
            self.is_paused = True
            self._stop_event.set()
            _log("⏸️ Paused")
            self._update_music_panel("paused")
            return "Pausé la música."

    def resume(self) -> str:
        """Resume paused playback."""
        with self._lock:
            if not self.is_playing or not self.is_paused:
                return "No hay música pausada para reanudar."
            playback_thread = self._playback_thread

        if playback_thread and playback_thread.is_alive():
            playback_thread.join(timeout=2)
            if playback_thread.is_alive():
                return "La reproducción todavía se está pausando. Probá de nuevo en un momento."

        with self._lock:
            self.is_paused = False
            self._stop_event.clear()
            self._start_playback()
            _log("▶️ Resumed")
            self._update_music_panel("resumed")
            return "Reanudé la música."

    def stop(self) -> str:
        """Stop playback and clear queue."""
        with self._lock:
            self._stop_event.set()
            self._skip_requested = False
            self.is_playing = False
            self.is_paused = False
            self.queue.clear()
            self.current_track = None
            
            # Terminate FFmpeg process cleanly
            if self.ffmpeg_process:
                try:
                    self.ffmpeg_process.terminate()
                    self.ffmpeg_process.wait(timeout=2)
                    _log("[DiscordMusic] FFmpeg terminated cleanly")
                except subprocess.TimeoutExpired:
                    try:
                        self.ffmpeg_process.kill()
                        _log("[DiscordMusic] FFmpeg killed (timeout)")
                    except Exception:
                        _log("[DiscordMusic] FFmpeg kill failed")
                except Exception as exc:
                    _log(f"[DiscordMusic] FFmpeg terminate error: {exc}")
                self.ffmpeg_process = None
            
            _log("⏹️ Stopped and cleared queue")
            self._update_music_panel("stop")
            return "Detuve la música y limpié la cola."

    def skip(self) -> str:
        """Skip to next track."""
        with self._lock:
            if not self.queue:
                return "No hay más temas en la cola."

            next_track = self.queue.pop(0)
            if self.current_track:
                self.history.append(self.current_track)
            self.current_track = next_track
            _log(f"⏭️ Skipped to: {self.current_track.title}")

            if self.is_playing:
                self._skip_requested = True
                self._stop_event.set()
                return f"Salté al siguiente tema: {self.current_track.title}"

            self._update_music_panel("track skipped")
            return f"Próximo tema: {self.current_track.title}"

    def get_queue(self) -> str:
        """Get current queue status."""
        with self._lock:
            if not self.queue and not self.current_track:
                return "La cola está vacía."
            
            lines = []
            if self.current_track:
                status = "🔊 Reproduciendo" if self.is_playing and not self.is_paused else "⏸️ Pausado"
                lines.append(f"{status}: {self.current_track.title}")
            
            if self.queue:
                lines.append("Cola:")
                for i, track in enumerate(self.queue[:10], 1):
                    lines.append(f"  {i}. {track.title}")
                if len(self.queue) > 10:
                    lines.append(f"  ... y {len(self.queue) - 10} más")
            
            return "\n".join(lines) if lines else "La cola está vacía."

    def clear_queue(self) -> str:
        """Clear the queue (except current track)."""
        with self._lock:
            if not self.queue:
                return "La cola ya está vacía."
            
            count = len(self.queue)
            self.queue.clear()
            _log(f"🗑️ Cleared queue ({count} tracks)")
            return f"Limpié la cola ({count} temas)."

    def set_volume(self, volume: int) -> str:
        """Set volume (0-100)."""
        try:
            volume = int(volume)
            if volume < 0:
                volume = 0
            elif volume > 100:
                volume = 100
        except Exception:
            return "El volumen debe ser un número entre 0 y 100."
        
        with self._lock:
            self.volume = volume
            _log(f"🔊 Volume set to {volume}%")
            self._update_music_panel("volume changed")
            return f"Volumen: {volume}%."

    def volume_down(self) -> str:
        """Decrease volume by 10."""
        with self._lock:
            new_volume = max(0, self.volume - 10)
            self.volume = new_volume
            _log(f"🔉 Volume down to {new_volume}%")
            self._update_music_panel("volume changed")
            return f"Volumen: {new_volume}%."

    def volume_up(self) -> str:
        """Increase volume by 10."""
        with self._lock:
            new_volume = min(100, self.volume + 10)
            self.volume = new_volume
            _log(f"🔊 Volume up to {new_volume}%")
            self._update_music_panel("volume changed")
            return f"Volumen: {new_volume}%."
    
    def toggle_loop(self) -> str:
        """Toggle loop mode for current track."""
        with self._lock:
            self.loop_mode = not self.loop_mode
            status = "activado" if self.loop_mode else "desactivado"
            _log(f"🔁 Loop mode {status}")
            return f"Loop {status}."
    
    def shuffle_queue(self) -> str:
        """Shuffle the queue."""
        with self._lock:
            if not self.queue:
                return "La cola está vacía, no hay nada para mezclar."
            
            if len(self.queue) < 2:
                return "La cola tiene menos de 2 temas, no se puede mezclar."
            
            import random
            random.shuffle(self.queue)
            _log(f"🔀 Queue shuffled ({len(self.queue)} tracks)")
            return f"Mezclé la cola ({len(self.queue)} temas)."
    
    def play_previous(self) -> str:
        """Play the previous track from history."""
        with self._lock:
            if not self.history:
                return "No hay canción anterior."

            previous = self.history.pop()
            if self.current_track:
                self.queue.insert(0, self.current_track)
            self.current_track = previous

            if self.is_playing:
                self._skip_requested = True
                self._stop_event.set()
            else:
                self.play()

            _log(f"⏮️ Playing previous: {previous.title}")
            return f"Volviendo a: {previous.title}."

    def queue_status(self) -> str:
        """Get current queue status (alias for get_queue)."""
        return self.get_queue()

    def _update_panel(self) -> None:
        """Update the music panel message if it exists."""
        if not self.panel_message or not self.current_track:
            return
        
        try:
            display_title = self._safe_display_title(self.current_track)
            status = "🔊 Playing" if self.is_playing and not self.is_paused else "⏸️ Paused"
            
            panel_text = f"""🎵 MUSIC PANEL

Now Playing:
{display_title}

Status:
{status}

Volume:
{self.volume}%

Controls:
⏸ Helena, pausá la música
▶ Helena, reanudá la música
⏹ Helena, detené la música
⏭ Helena, saltá canción
🔊 Helena, volumen 50
📜 Helena, cola"""
            
            # Update the panel message
            if hasattr(self.panel_message, 'edit'):
                # If using Discord UI with View, update the embed/content
                if self.panel_view and hasattr(self.panel_view, '_update_pause_button'):
                    self.panel_view._update_pause_button()
                
                # Use asyncio to update the message
                if self._bridge and hasattr(self._bridge, 'loop') and self._bridge.loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self.panel_message.edit(content=panel_text, view=self.panel_view),
                        self._bridge.loop
                    )
                    _log("[DiscordMusicUI] panel updated")
        except Exception as exc:
            _log(f"[DiscordMusicUI] panel update error: {exc}")

    def get_status(self) -> str:
        """Get current player status."""
        with self._lock:
            if not self.is_playing and not self.current_track:
                return "El reproductor está detenido."
            
            status = "🔊 Reproduciendo" if self.is_playing and not self.is_paused else "⏸️ Pausado"
            lines = [f"{status}"]
            
            if self.current_track:
                lines.append(f"Tema: {self.current_track.title}")
                lines.append(f"Volumen: {self.volume}%")
                lines.append(f"En cola: {len(self.queue)} temas")
            
            return "\n".join(lines)

    def get_debug_info(self) -> str:
        """Get diagnostic information about the music player."""
        lines = ["[DiscordMusic Debug Info]"]
        
        # Discord connection status
        if self._bridge:
            vc = getattr(self._bridge, "voice_client", None)
            lines.append(f"Discord conectado: {bool(vc and getattr(vc, 'is_connected', lambda: False)())}")
            lines.append(f"Voice client existe: {bool(vc)}")
            if vc:
                is_playing = getattr(vc, 'is_playing', lambda: False)()
                lines.append(f"Voice client is_playing: {is_playing}")
                lines.append(f"Bridge mode activo: yes (is_playing check ignored)")
        else:
            lines.append("Discord conectado: no (sin bridge)")
            lines.append("Voice client existe: no")
            lines.append("Bridge mode activo: no")
        
        # Music player status
        lines.append(f"Música reproduciendo: {self.is_playing}")
        lines.append(f"Música pausada: {self.is_paused}")
        lines.append(f"Tamaño de cola: {len(self.queue)}")
        
        if self.current_track:
            lines.append(f"Tema actual: {self.current_track.title}")
            lines.append(f"Fuente: {self.current_track.source}")
            lines.append(f"Resuelto: {self.current_track.resolved}")
        else:
            lines.append("Tema actual: ninguno")
        
        # Dependencies
        lines.append(f"FFmpeg disponible: {self._check_ffmpeg()}")
        lines.append(f"FFmpeg path: {self.config.ffmpeg_path}")
        lines.append(f"yt-dlp disponible: {_check_ytdlp()}")
        
        # Config
        lines.append(f"Música habilitada: {self.config.enabled}")
        lines.append(f"Volumen actual: {self.volume}%")
        
        return "\n".join(lines)

    def _start_playback(self) -> None:
        """Start playback in a separate thread."""
        if self._playback_thread and self._playback_thread.is_alive():
            return
        
        self._stop_event.clear()
        self.is_playing = True
        self.is_paused = False
        self._playback_error = None
        self._playback_started_event.clear()
        
        self._playback_thread = threading.Thread(
            target=self._playback_worker,
            name="DiscordMusicPlayer",
            daemon=True
        )
        self._playback_thread.start()

    def _playback_worker(self) -> None:
        """Worker thread for audio playback."""
        while True:
            with self._lock:
                track = self.current_track
                if self._stop_event.is_set() and not self._skip_requested:
                    if not self.is_paused:
                        self.is_playing = False
                    return
                if not track:
                    self.is_playing = False
                    self._update_music_panel("queue finished")
                    return
                self._skip_requested = False
                self._stop_event.clear()
                self._playback_error = None
                self._playback_started_event.clear()

            _log(f"▶️ Starting playback: {track.title} (source: {track.source})")
            try:
                if track.source == "file":
                    self._play_file(track.url)
                elif track.source == "ytdlp" and track.query:
                    self._play_ytdlp_query(track.query)
                elif track.source in ("url", "ytdlp"):
                    self._play_url(track.url, track.http_headers)
                else:
                    _log(f"⚠️ Unsupported source: {track.source}")
            except Exception as exc:
                _log(f"❌ Playback failed: {exc}")
                self._playback_error = f"No pude procesar el audio: {exc}"
                self._playback_started_event.set()

            with self._lock:
                if self._playback_error:
                    self.is_playing = False
                    self._playback_started_event.set()
                    self._update_music_panel("playback failed")
                    return

                if self._skip_requested:
                    self._skip_requested = False
                    self._stop_event.clear()
                    self._update_music_panel("track changed")
                    continue

                if self._stop_event.is_set():
                    if not self.is_paused:
                        self.is_playing = False
                    return

                if self.loop_mode and self.current_track is track:
                    self._update_music_panel("track looped")
                    continue

                if self.queue:
                    self.history.append(track)
                    self.current_track = self.queue.pop(0)
                    self._update_music_panel("track changed")
                    continue

                self.current_track = None
                self.is_playing = False
                _log("🏁 Queue finished")
                self._update_music_panel("queue finished")
                return

    def _play_file(self, filepath: str) -> None:
        """Play a local file using FFmpeg and feed to Discord bridge."""
        if not self._is_safe_path(filepath):
            _log(f"⚠️ Unsafe path rejected: {filepath}")
            return
        
        _log(f"local file requested: {filepath}")
        _log(f"file exists: {Path(filepath).exists()}")
        _log(f"ffmpeg available: {self._check_ffmpeg()}")
        
        # Convert to PCM s16le mono 24000Hz for Helena's audio system
        cmd = [
            self.config.ffmpeg_path,
            "-hide_banner",
            "-loglevel", "error",
            "-i", filepath,
            "-vn",  # No video
            "-ac", "1",  # Mono
            "-ar", "24000",  # 24kHz for Helena's system
            "-f", "s16le",  # PCM s16le
            "pipe:1"
        ]
        
        self._run_ffmpeg_to_bridge(cmd)

    def _play_url(self, url: str, headers: Optional[dict[str, str]] = None) -> None:
        """Play a URL/stream using FFmpeg and feed to Discord bridge."""
        # Truncate URL for logging
        url_log = url[:120] + "..." if len(url) > 120 else url
        _log(f"stream url: {url_log}")
        
        cmd = [
            self.config.ffmpeg_path,
            "-hide_banner",
            "-loglevel", "error",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
        ]
        if headers:
            header_lines = [
                f"{name}: {value}".replace("\r", "").replace("\n", "")
                for name, value in headers.items()
                if name and value is not None
            ]
            if header_lines:
                cmd.extend(["-headers", "\r\n".join(header_lines) + "\r\n"])
        cmd.extend([
            "-i", url,
            "-vn",  # No video
            "-ac", "1",  # Mono
            "-ar", "24000",  # 24kHz for Helena's system
            "-f", "s16le",  # PCM s16le
            "pipe:1"
        ])
        
        self._run_ffmpeg_to_bridge(cmd)

    def _play_ytdlp_query(self, query: str) -> None:
        """Stream a yt-dlp search result through FFmpeg without exposing its URL."""
        if not _check_ytdlp():
            self._playback_error = "yt-dlp dejó de estar disponible antes de reproducir."
            self._playback_started_event.set()
            _log(f"❌ {self._playback_error}")
            return

        search_query = f"ytsearch1:{self._sanitize_input(query)}"
        # V36_FIX: YouTube now returns 403 Forbidden without proper client config.
        # Using a real browser User-Agent + Android player client bypasses the block.
        ytdlp_cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--format",
            "bestaudio/best",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            "--no-progress",
            "--output",
            "-",
            "--user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "--extractor-args",
            "youtube:player_client=android",
            search_query,
        ]
        _log(f"streaming yt-dlp search directly to FFmpeg: {query}")

        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            source_process = subprocess.Popen(
                ytdlp_cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                creationflags=creation_flags,
            )
        except Exception as exc:
            self._playback_error = f"No pude iniciar yt-dlp: {exc}"
            self._playback_started_event.set()
            _log(f"❌ {self._playback_error}")
            return

        ffmpeg_cmd = [
            self.config.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-f",
            "s16le",
            "pipe:1",
        ]
        self._run_ffmpeg_to_bridge(ffmpeg_cmd, input_process=source_process)

    def _run_ffmpeg_to_bridge(
        self,
        cmd: list[str],
        input_process: Optional[subprocess.Popen] = None,
    ) -> None:
        """Run FFmpeg and feed audio to Discord bridge."""
        if not self._bridge:
            self._playback_error = "No hay una conexión activa con Discord."
            self._playback_started_event.set()
            _log(f"⚠️ {self._playback_error}")
            if input_process:
                if input_process.poll() is None:
                    input_process.terminate()
                    try:
                        input_process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        input_process.kill()
                        input_process.wait()
            return
        
        # Truncate command for logging
        cmd_log = ' '.join(cmd)
        cmd_log = cmd_log[:120] + "..." if len(cmd_log) > 120 else cmd_log
        _log(f"ffmpeg cmd: {cmd_log}")
        
        try:
            # Windows-specific flags for subprocess
            creation_flags = 0
            if os.name == 'nt':
                creation_flags = subprocess.CREATE_NO_WINDOW
            
            self.ffmpeg_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=input_process.stdout if input_process else subprocess.DEVNULL,
                bufsize=0,
                creationflags=creation_flags
            )
            if input_process and input_process.stdout:
                input_process.stdout.close()
            
            _log("ffmpeg started")
            _log(f"discord voice client connected: {bool(self._bridge.voice_client and getattr(self._bridge.voice_client, 'is_connected', lambda: False)())}")
            _log(f"using bridge mode: yes")
            _log("realtime throttle enabled: 20ms/chunk")
            
            # Read audio chunks and send to Discord bridge
            chunk_size = 960  # 20ms @ 24kHz mono s16 (PCM24 format)
            chunk_duration = 0.020  # 20ms per chunk
            buffer = bytearray()
            chunks_sent = 0
            total_bytes = 0
            first_read = True
            start_time = time.perf_counter()
            next_send_time = start_time
            
            # V35_9_6: Track when voice became inactive for cooldown and gate state
            voice_inactive_time = 0.0
            last_gate_reason = ""
            last_gate_log_time = 0.0
            self._buffer_gate_state = False
            
            while not self._stop_event.is_set():
                try:
                    # V35_9_6: Track voice state for cooldown
                    if self._bridge and hasattr(self._bridge, 'is_voice_active'):
                        voice_active = self._bridge.is_voice_active()
                        if voice_active:
                            voice_inactive_time = 0.0
                        elif voice_inactive_time == 0.0:
                            voice_inactive_time = time.time()
                    
                    # V35_9_6: Combined gate check BEFORE reading FFmpeg stdout
                    can_read, reason = self._can_read_music_now(voice_inactive_time)
                    
                    # Update buffer gate state for hysteresis
                    if reason == "buffer_high":
                        self._buffer_gate_state = True
                    elif reason == "ready":
                        self._buffer_gate_state = False
                    
                    # Log gate state changes (throttled to every 2 seconds)
                    now = time.time()
                    if reason != last_gate_reason and now - last_gate_log_time > 2.0:
                        if reason == "ready":
                            buffer_size = 0
                            if self._bridge and hasattr(self._bridge, 'get_output_buffer_size'):
                                buffer_size = self._bridge.get_output_buffer_size()
                            voice_active_str = "False"
                            if self._bridge and hasattr(self._bridge, 'is_voice_active'):
                                voice_active_str = str(self._bridge.is_voice_active())
                            _log(f"[DiscordMusic] music gate ready: buffer={buffer_size} voice_active={voice_active_str}")
                        else:
                            buffer_size = 0
                            if self._bridge and hasattr(self._bridge, 'get_output_buffer_size'):
                                buffer_size = self._bridge.get_output_buffer_size()
                            _log(f"[DiscordMusic] music gate waiting: reason={reason} buffer={buffer_size}")
                        last_gate_reason = reason
                        last_gate_log_time = now
                    
                    # Wait if cannot read
                    if not can_read:
                        time.sleep(0.05)
                        continue
                    
                    # Read from FFmpeg
                    data = self.ffmpeg_process.stdout.read(chunk_size)
                    if not data:
                        break
                    
                    if first_read:
                        _log(f"first read bytes: {len(data)}")
                        first_read = False
                    
                    buffer.extend(data)
                    
                    # Send to Discord bridge when we have a full chunk
                    while len(buffer) >= chunk_size:
                        # Respect pause state
                        while self.is_paused and not self._stop_event.is_set():
                            time.sleep(0.05)
                        
                        if self._stop_event.is_set():
                            break
                        
                        chunk = bytes(buffer[:chunk_size])
                        buffer = buffer[chunk_size:]
                        
                        # Apply volume and ducking
                        effective_volume = self._get_effective_volume()
                        chunk = _apply_pcm_volume(chunk, effective_volume)
                        
                        # Send to Discord bridge using enqueue_output_audio with source="music"
                        if self._bridge and hasattr(self._bridge, 'enqueue_output_audio'):
                            if not self._bridge.enqueue_output_audio(chunk, source="music"):
                                self._playback_error = "Discord rechazó el audio (puede estar muteada o desconectada)."
                                self._stop_event.set()
                                _log(f"⚠️ {self._playback_error}")
                                break
                            chunks_sent += 1
                            total_bytes += len(chunk)
                            if chunks_sent == 1:
                                self._playback_started_event.set()
                                _log("first audio chunk sent to Discord bridge")
                                _log("playback actually started: yes")
                                _log(f"[DiscordMusic] voice gate enabled: {self.config.pause_while_helena_speaks}")
                            
                            # Realtime throttling: wait to maintain 20ms per chunk
                            next_send_time += chunk_duration
                            current_time = time.perf_counter()
                            delay = next_send_time - current_time
                            if delay > 0:
                                time.sleep(delay)
                
                except Exception as exc:
                    _log(f"⚠️ Audio read error: {exc}")
                    break
            
            # Wait for FFmpeg to finish and get return code
            if self.ffmpeg_process:
                returncode = self.ffmpeg_process.wait(timeout=2)
                stderr_output = self.ffmpeg_process.stderr.read().decode('utf-8', errors='ignore')
            else:
                _log("FFmpeg process already terminated")
                returncode = -1
                stderr_output = ""

            input_returncode = None
            input_stderr = ""
            if input_process:
                try:
                    input_returncode = input_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    input_process.terminate()
                    try:
                        input_process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        input_process.kill()
                        input_process.wait()
                if input_process.stderr:
                    input_stderr = input_process.stderr.read().decode(
                        "utf-8", errors="replace"
                    )
                if input_stderr:
                    _log(f"yt-dlp stderr: {input_stderr[-500:]}")
            
            elapsed_time = time.perf_counter() - start_time
            expected_time = chunks_sent * chunk_duration
            drift = elapsed_time - expected_time
            
            _log(f"playback completed realtime, sent {chunks_sent} chunks, elapsed {elapsed_time:.2f}s")
            _log(f"chunks sent: {chunks_sent} elapsed: {elapsed_time:.2f}s expected: {expected_time:.2f}s drift: {drift:.2f}s")
            _log(f"ffmpeg returncode: {returncode}")
            if stderr_output:
                stderr_log = stderr_output[-500:] if len(stderr_output) > 500 else stderr_output
                _log(f"ffmpeg stderr: {stderr_log}")
            
            if chunks_sent == 0:
                _log("❌ FFmpeg delivered 0 chunks to bridge")
                if not self._playback_error:
                    error_output = (
                        input_stderr
                        if input_returncode not in (None, 0) and input_stderr.strip()
                        else stderr_output
                    )
                    detail = error_output.strip().splitlines()
                    detail = detail[-1][:240] if detail else f"FFmpeg salió con código {returncode}."
                    prefix = (
                        "yt-dlp no pudo obtener el audio."
                        if input_returncode not in (None, 0)
                        else "No se recibió audio de la fuente."
                    )
                    self._playback_error = f"{prefix} {detail}"
            elif returncode != 0 and not self._stop_event.is_set():
                detail = stderr_output.strip().splitlines()
                detail = detail[-1][:240] if detail else f"FFmpeg salió con código {returncode}."
                self._playback_error = f"La fuente de audio falló. {detail}"
            elif input_returncode not in (None, 0) and not self._stop_event.is_set():
                detail = input_stderr.strip().splitlines()
                detail = detail[-1][:240] if detail else "yt-dlp terminó con error."
                self._playback_error = f"yt-dlp interrumpió la fuente de audio. {detail}"
            self._playback_started_event.set()
            
        except subprocess.TimeoutExpired:
            _log("❌ FFmpeg timeout")
            self._playback_error = "FFmpeg agotó el tiempo de espera al terminar la reproducción."
        except Exception as exc:
            _log(f"❌ FFmpeg error: {exc}")
            self._playback_error = f"No pude iniciar o transmitir el audio: {exc}"
        finally:
            self._playback_started_event.set()
            if self.ffmpeg_process:
                try:
                    self.ffmpeg_process.terminate()
                    self.ffmpeg_process.wait(timeout=2)
                except Exception:
                    try:
                        self.ffmpeg_process.kill()
                    except Exception:
                        pass
                self.ffmpeg_process = None
            if input_process and input_process.poll() is None:
                input_process.terminate()
                try:
                    input_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    input_process.kill()

    def cleanup(self) -> None:
        """Cleanup resources."""
        self._stop_event.set()
        self.stop()
        
        if self._playback_thread and self._playback_thread.is_alive():
            self._playback_thread.join(timeout=2)

    def _send_music_panel(self) -> None:
        """Send music panel embed to Discord text channel."""
        if not self._bridge:
            _log("[DiscordMusicUI] cannot send panel: no bridge")
            return

        panel_text = self._build_music_panel_text()
        channel_id = _cfg_int("discord_music_text_channel_id") or _cfg_int("discord_text_channel_id")
        if not channel_id:
            channel_id = getattr(getattr(self._bridge, "config", None), "text_channel_id", None)
        if not channel_id:
            _log("[DiscordMusicUI] cannot send panel: no music/text channel configured")
            return

        client = getattr(self._bridge, "client", None)
        loop = getattr(self._bridge, "loop", None)
        if not client or not loop or not loop.is_running():
            _log("[DiscordMusicUI] cannot send panel: Discord client loop is not running")
            return

        if DISCORD_UI_AVAILABLE and self.config.buttons_enabled and self.panel_view is None:
            self.panel_view = MusicControlView(self)

        async def send_or_edit_panel():
            try:
                if self.panel_message:
                    await self.panel_message.edit(content=panel_text, view=self.panel_view)
                    _log("[DiscordMusicUI] existing music panel updated")
                    return

                channel = client.get_channel(int(channel_id))
                if channel is None:
                    channel = await client.fetch_channel(int(channel_id))
                message = await channel.send(
                    content=panel_text,
                    view=self.panel_view if DISCORD_UI_AVAILABLE and self.config.buttons_enabled else None,
                )
                self.panel_message = message
                if self.panel_view is not None and DISCORD_UI_AVAILABLE:
                    _ACTIVE_MUSIC_VIEWS[message.id] = self.panel_view
                _log(f"[DiscordMusicUI] music panel sent message_id={message.id}")
            except Exception as exc:
                _log(f"[DiscordMusicUI] panel send/update failed: {exc}")

        asyncio.run_coroutine_threadsafe(send_or_edit_panel(), loop)
    
    def _send_panel_fallback(self, display_title: str, status: str) -> None:
        """Log a fallback panel when a Discord UI panel cannot be sent."""
        _log(f"Music panel unavailable: {display_title} | {status} | {self.volume}%")


def get_music_player() -> DiscordMusicPlayer:
    """Get or create the singleton music player."""
    global _discord_music_player
    with _lock:
        if _discord_music_player is None:
            _discord_music_player = DiscordMusicPlayer()
        return _discord_music_player


def discord_music(parameters=None, response=None, player=None, session_memory=None):
    """
    Discord music player control.
    Actions: play, pause, resume, stop, skip, queue, clear, volume, status, like_artist, like_track, play_liked
    Parameters:
    - action: required (play|pause|resume|stop|skip|queue|clear|volume|status|like_artist|like_track|play_liked)
    - query: optional (search term or URL for play, or artist/track name for like actions)
    - url: optional (direct URL for play)
    - volume: optional (0-100 for volume action)
    """
    parameters = parameters or {}
    action = str(parameters.get("action") or "").strip().lower()
    query = str(parameters.get("query") or "").strip()
    url = str(parameters.get("url") or "").strip()
    volume = parameters.get("volume", "")
    
    music_player = get_music_player()
    
    # Try to get bridge reference
    try:
        from actions.discord_mode import _bridge
        if _bridge:
            music_player.set_bridge(_bridge)
    except Exception:
        pass
    
    if action in ("play", "reproducir", "pon", "poner", "tocar"):
        track_url = url or query
        title = query if url else ""
        return music_player.play(track_url, title)
    
    if action in ("pause", "pausar", "pausa"):
        return music_player.pause()
    
    if action in ("resume", "reanudar", "continuar", "seguir"):
        return music_player.resume()
    
    if action in ("stop", "detener", "deten", "parar"):
        return music_player.stop()
    
    if action in ("skip", "saltar", "siguiente", "next"):
        return music_player.skip()
    
    if action in ("queue", "cola", "lista", "list"):
        return music_player.get_queue()
    
    if action in ("clear", "limpiar", "vaciar"):
        return music_player.clear_queue()
    
    if action in ("volume", "volumen", "vol"):
        try:
            vol = int(volume) if volume else music_player.volume
            return music_player.set_volume(vol)
        except Exception:
            return "El volumen debe ser un número entre 0 y 100."
    
    if action in ("status", "estado", "now_playing", "np"):
        return music_player.get_status()
    
    if action in ("debug", "diagnostico", "diagnóstico"):
        return music_player.get_debug_info()
    
    if action in ("audio_debug", "diagnostico_audio", "audio_diagnostico"):
        # V35_9_6: Enhanced combined gate audio debug
        lines = ["[DiscordMusic Audio Debug]"]
        
        # Music player status
        lines.append(f"Music playing: {music_player.is_playing}")
        lines.append(f"Music paused: {music_player.is_paused}")
        lines.append(f"Music volume: {music_player.volume}%")
        lines.append(f"Duck volume: {music_player.config.duck_volume}%")
        lines.append(f"Voice priority enabled: {music_player.config.voice_priority_enabled}")
        lines.append(f"Pause while speaking: {music_player.config.pause_while_helena_speaks}")
        
        # V35_9_6: Buffer-aware resume config
        lines.append(f"Resume buffer max: {music_player.config.resume_buffer_max_bytes} bytes")
        lines.append(f"Resume after voice delay: {music_player.config.resume_after_voice_delay_ms} ms")
        lines.append(f"Buffer high threshold: {music_player.config.buffer_high_bytes} bytes")
        lines.append(f"Buffer low threshold: {music_player.config.buffer_low_bytes} bytes")
        
        # Bridge voice status
        voice_active = False
        if music_player._bridge and hasattr(music_player._bridge, 'is_voice_active'):
            voice_active = music_player._bridge.is_voice_active()
            lines.append(f"Voice active: {voice_active}")
        else:
            lines.append("Voice active: unknown (no bridge)")
        
        # V35_9_6: Voice active age
        if music_player._bridge and hasattr(music_player._bridge, '_last_voice_chunk_time'):
            last_voice_time = music_player._bridge._last_voice_chunk_time
            if last_voice_time > 0:
                age = time.time() - last_voice_time
                lines.append(f"Voice active age: {age:.1f}s")
            else:
                lines.append("Voice active age: never")
        else:
            lines.append("Voice active age: unknown")
        
        # V35_9_6: Output buffer size and safety
        buffer_size = 0
        if music_player._bridge and hasattr(music_player._bridge, 'get_output_buffer_size'):
            buffer_size = music_player._bridge.get_output_buffer_size()
            lines.append(f"Output buffer size: {buffer_size} bytes")
            if music_player._bridge.is_output_buffer_safe_for_music(music_player.config.resume_buffer_max_bytes):
                lines.append("Buffer safe for music: yes")
            else:
                lines.append("Buffer safe for music: no")
        else:
            lines.append("Output buffer size: unknown")
            lines.append("Buffer safe for music: unknown")
        
        # V35_9_6: Combined gate status
        can_read, gate_reason = music_player._can_read_music_now(0.0)
        lines.append(f"Can read music now: {can_read}")
        lines.append(f"Gate reason: {gate_reason}")
        
        # V35_9_6: Post-voice cooldown remaining
        if hasattr(music_player, '_voice_inactive_time') and music_player._voice_inactive_time > 0.0:
            cooldown_elapsed = (time.time() - music_player._voice_inactive_time) * 1000
            cooldown_remaining = max(0, music_player.config.resume_after_voice_delay_ms - cooldown_elapsed)
            lines.append(f"Post-voice cooldown remaining: {cooldown_remaining:.0f} ms")
        else:
            lines.append("Post-voice cooldown remaining: 0 ms")
        
        # V35_9_6: Buffer high state
        if hasattr(music_player, '_buffer_gate_state'):
            lines.append(f"Buffer high state: {music_player._buffer_gate_state}")
        else:
            lines.append("Buffer high state: unknown")
        
        # Current track
        if music_player.current_track:
            lines.append(f"Current track: {music_player.current_track.title}")
        else:
            lines.append("Current track: none")
        
        # Queue size
        lines.append(f"Queue size: {len(music_player.queue)}")
        
        return "\n".join(lines)
    
    if action in ("memory_status", "estado_memoria", "memoria_musical", "music_preferences_status"):
        if MUSIC_PREFS_AVAILABLE:
            return get_music_status()
        else:
            return "Módulo de preferencias no disponible."
    
    # Preference commands
    if action in ("like_artist", "recordar_artista", "me_gusta_artista", "favorito_artista"):
        if not query:
            return "Decime qué artista te gusta. Ejemplo: Helena, recordá que me gusta Ramones."
        if MUSIC_PREFS_AVAILABLE:
            return add_liked_artist(query)
        else:
            return "Módulo de preferencias no disponible."
    
    if action in ("like_track", "guardar_favorito", "me_gesta_tema"):
        if not query:
            return "Decime qué tema te gusta. Ejemplo: Helena, guardá este tema en favoritos."
        if MUSIC_PREFS_AVAILABLE:
            return add_liked_track(query)
        else:
            return "Módulo de preferencias no disponible."
    
    if action in ("play_liked", "reproducir_favorito", "pon_algo_que_me_gusta"):
        if not MUSIC_PREFS_AVAILABLE:
            return "Módulo de preferencias no disponible."
        
        seed = get_music_seed()
        if not seed:
            return "No tengo artistas ni temas favoritos guardados. Decime qué te gusta primero."
        
        search_query = f"{seed} popular song"
        _log(f"[DiscordMusic] Playing from preferences: {seed}")
        return music_player.play("", search_query)
    
    return f"Acción desconocida: {action}. Usá: play, pause, resume, stop, skip, queue, clear, volume, status, like_artist, like_track, play_liked."
