# -*- coding: utf-8 -*-
import asyncio
import builtins

import threading
import concurrent.futures
import json
import sys
import traceback


import time
import warnings


_ORIGINAL_PRINT = builtins.print


def _safe_print(*args, sep=" ", end="\n", file=None, flush=False):
    target = file if file is not None else sys.stdout
    try:
        return _ORIGINAL_PRINT(*args, sep=sep, end=end, file=target, flush=flush)
    except UnicodeEncodeError:
        safe_args = []
        for arg in args:
            safe_args.append(str(arg).encode("ascii", errors="replace").decode("ascii"))
        return _ORIGINAL_PRINT(*safe_args, sep=sep, end=end, file=target, flush=flush)


builtins.print = _safe_print


from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

warnings.filterwarnings("ignore", message=r".*google\.generativeai.*", category=FutureWarning)
warnings.filterwarnings("ignore", message=r".*All support for the `google\.generativeai` package.*", category=FutureWarning)

# V32.7 (launcher SILENT): si Helena corre sin consola (pythonw.exe),
# sys.stdout/sys.stderr son None y cualquier print() explotaria con
# AttributeError. Se redirigen a logs/helena_silent.log para que la app
# opere normal y deje traza de ejecucion.
if sys.stdout is None or sys.stderr is None:
    try:
        _silent_log_path = Path(__file__).resolve().parent / "logs" / "helena_silent.log"
        _silent_log_path.parent.mkdir(parents=True, exist_ok=True)
        _silent_log = open(_silent_log_path, "a", encoding="utf-8")
        sys.stdout = _silent_log
        sys.stderr = _silent_log
    except Exception:
        import io as _io
        sys.stdout = _io.StringIO()
        sys.stderr = sys.stdout


import sounddevice as sd
import numpy as np


from google import genai


from google.genai import types


from ui import HelenaUI


from memory.memory_manager import (


    load_memory, update_memory, format_memory_for_prompt,


    should_extract_memory, extract_memory


)
from memory.partial_writer import ShortTermPartialWriter
from utils.audio_metrics import AudioTimingMetrics


from actions.file_processor import file_processor


from actions.flight_finder     import flight_finder


from actions.open_app          import open_app


from actions.weather_report    import weather_action


from actions.send_message      import send_message


from actions.text_output       import text_output


from actions.reminder          import reminder


from actions.computer_settings import computer_settings


from actions.screen_processor  import screen_process


from actions.youtube_video     import youtube_video


from actions.desktop           import desktop_control


from actions.browser_control   import browser_control


from actions.file_controller   import file_controller


from actions.code_helper       import code_helper


from actions.dev_agent         import dev_agent


from actions.web_search        import web_search as web_search_action


from actions.computer_control  import computer_control


from actions.system_control    import system_control


from actions.game_updater      import game_updater


from actions.discord_mode      import discord_mode, set_discord_context, send_audio_to_discord


from actions.discord_music     import discord_music


# Suprimir advertencias


import warnings


warnings.filterwarnings("ignore")


# Configurar modo silencioso para subprocess


import os


os.environ['HELENA_SILENT_MODE'] = '1'


# Suprimir advertencia de DPI de Qt


os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"


os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"


os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"


# Importar el servidor WebSocket independiente


import websocket_server


def get_base_dir():


    if getattr(sys, "frozen", False):


        return Path(sys.executable).parent


    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()


API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"


def _load_runtime_config() -> dict:
    try:
        if API_CONFIG_PATH.exists():
            data = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        print(f"[Config] No pude leer configuracion runtime: {exc}")
    return {}


def _cfg_int(name: str, default: int, env_name: str = "") -> int:
    try:
        raw = os.getenv(env_name or name.upper(), "").strip()
        if raw:
            return int(raw)
        value = _load_runtime_config().get(name, default)
        return int(value)
    except Exception:
        return int(default)


def _cfg_str(name: str, default: str, env_name: str = "") -> str:
    try:
        raw = os.getenv(env_name or name.upper(), "").strip()
        if raw:
            return raw
        value = _load_runtime_config().get(name, default)
        return str(value or default).strip() or default
    except Exception:
        return default


def _helena_timezone():
    tz_name = _cfg_str("helena_timezone", "America/Argentina/Buenos_Aires", "HELENA_TIMEZONE")
    if ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name), tz_name
        except Exception as exc:
            print(f"[Tiempo] No pude cargar zona '{tz_name}', uso UTC-03:00: {exc}")
    return timezone(timedelta(hours=-3), name="UTC-03:00"), "America/Argentina/Buenos_Aires"


def _helena_now() -> tuple[datetime, str]:
    tz, tz_name = _helena_timezone()
    return datetime.now(timezone.utc).astimezone(tz), tz_name


_WEEKDAY_ES = {
    0: "lunes",
    1: "martes",
    2: "miercoles",
    3: "jueves",
    4: "viernes",
    5: "sabado",
    6: "domingo",
}


_MONTH_ES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}


def _helena_location() -> str:
    return _cfg_str(
        "helena_location",
        "Lomas de Zamora, Buenos Aires, Argentina",
        "HELENA_LOCATION",
    )


def _format_helena_local_date(now: datetime) -> str:
    weekday = _WEEKDAY_ES.get(now.weekday(), now.strftime("%A").lower())
    month = _MONTH_ES.get(now.month, now.strftime("%B").lower())
    return f"{weekday} {now.day:02d} de {month} de {now.year}"


def _exception_text(exc: BaseException) -> str:
    parts = [str(exc)]
    nested = getattr(exc, "exceptions", None)
    if nested:
        for item in nested:
            parts.append(_exception_text(item))
    return " ".join(parts)


def _is_recoverable_live_error(exc: BaseException) -> bool:
    text = _exception_text(exc).lower()
    recoverable = (
        "1008",
        "1011",
        "policy violation",
        "operation is not implemented",
        "operation is not supported",
        "internal error",
        "connectionclosed",
        "connection closed",
    )
    return any(token in text for token in recoverable)


class LiveSilentWatchdogRestart(RuntimeError):
    """Señal interna: Gemini Live quedó mudo aunque el mic sigue enviando audio."""


SHORT_TERM_PATH = BASE_DIR / "memory" / "short_term.json"


LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
# V32.6: tipo de audio de entrada (PCM 16kHz mono) que Helena envia a Live.
# El SDK 2.7.0 no acepta media_chunks en RealtimeInputConfig; el tipo se declara
# por chunk en LiveClientRealtimeInput via types.Blob(mime_type=...).
LIVE_INPUT_AUDIO_MIME   = "audio/pcm;rate=16000"
# V32.6: bloqueo del mic mientras Helena habla (segundos tras el ultimo chunk)
SPEAKING_TAIL_LOCAL_S   = 1.0   # ruta local: buffer de salida corto
SPEAKING_TAIL_DISCORD_S = 4.5   # V26: el canal de voz de Discord suelta audio mas tarde
ASSISTANT_GUARD_LOCAL_S   = 1.0 # guard entre chunks de audio de Gemini (local)
ASSISTANT_GUARD_DISCORD_S = 3.0
INPUT_DRAIN_MIN_GAP_S     = 1.0 # drenado completo de la cola de mic maximo 1x/segundo


CHANNELS            = 1


SEND_SAMPLE_RATE    = 16000


GEMINI_OUTPUT_SAMPLE_RATE = _cfg_int("gemini_output_sample_rate", 24000, "HELENA_GEMINI_OUTPUT_SAMPLE_RATE")
RECEIVE_SAMPLE_RATE = _cfg_int("local_output_sample_rate", 24000, "HELENA_LOCAL_OUTPUT_SAMPLE_RATE")
MIC_QUEUE_MAX_CHUNKS = max(6, _cfg_int("mic_queue_max_chunks", 18, "HELENA_MIC_QUEUE_MAX_CHUNKS"))
MIC_QUEUE_TRIM_TO_CHUNKS = max(3, min(MIC_QUEUE_MAX_CHUNKS, _cfg_int("mic_queue_trim_to_chunks", 6, "HELENA_MIC_QUEUE_TRIM_TO_CHUNKS")))
MIC_MAX_STALE_SECONDS = max(0.25, float(_cfg_int("mic_max_stale_ms", 900, "HELENA_MIC_MAX_STALE_MS")) / 1000.0)
PLAYBACK_QUEUE_MAX_CHUNKS = max(24, _cfg_int("playback_queue_max_chunks", 96, "HELENA_PLAYBACK_QUEUE_MAX_CHUNKS"))
PLAYBACK_PREBUFFER_MS = max(0, _cfg_int("playback_prebuffer_ms", 80, "HELENA_PLAYBACK_PREBUFFER_MS"))
PLAYBACK_BATCH_MS = max(20, _cfg_int("playback_batch_ms", 120, "HELENA_PLAYBACK_BATCH_MS"))


CHUNK_SIZE          = 1024
AUDIO_INPUT_BLOCKSIZE = max(1024, _cfg_int("audio_input_blocksize", 2048, "HELENA_AUDIO_INPUT_BLOCKSIZE"))
AUDIO_OUTPUT_BLOCKSIZE = max(0, _cfg_int("audio_output_blocksize", 0, "HELENA_AUDIO_OUTPUT_BLOCKSIZE"))

# HELENA V32.4: latencia de audio: streams en latencia "low" para que la voz llegue
# con el minimo retardo (poner "high" en config si aparecen underruns/clicks)
AUDIO_OUTPUT_LATENCY   = _cfg_str("audio_output_latency", "low", "HELENA_AUDIO_OUTPUT_LATENCY")
AUDIO_INPUT_LATENCY    = _cfg_str("audio_input_latency", "low", "HELENA_AUDIO_INPUT_LATENCY")
# HELENA V32.4: VAD del lado servidor (Gemini Live): silencio mas corto => la
# deteccion de fin de habla (y con ella la respuesta) se confirma antes
LIVE_SILENCE_MS        = max(120, _cfg_int("live_silence_duration_ms", 350, "HELENA_LIVE_SILENCE_DURATION_MS"))
LIVE_PREFIX_PADDING_MS = max(60, _cfg_int("live_prefix_padding_ms", 120, "HELENA_LIVE_PREFIX_PADDING_MS"))


def _pcm_s16_mono_bytes_for_ms(sample_rate: int, ms: int) -> int:
    samples = int(max(1, sample_rate) * max(0, ms) / 1000.0)
    return max(0, samples * 2)


def _get_api_key() -> str:


    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:


        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:


    try:


        return PROMPT_PATH.read_text(encoding="utf-8")


    except Exception:


        return (


            "You are Helena, a warm, affectionate, and brilliant AI companion. "


            "Be concise, direct, and always use the provided tools to complete tasks. "


            "Never simulate or guess results — always call the appropriate tool."


        )


_short_term_lock = threading.Lock()


def _empty_short_term() -> dict:


    return {


        "version": 1,


        "descripcion": "Memoria corta de Helena. Sirve para recuperar continuidad despues de microcortes o reconexiones.",


        "updated": None,


        "partials": {"usuario": "", "helena": ""},
        "active_operation": None,
        "microcut_recovery": None,


        "turns": []


    }


def _load_short_term_memory() -> dict:


    try:


        if SHORT_TERM_PATH.exists():


            data = json.loads(SHORT_TERM_PATH.read_text(encoding="utf-8"))


            if isinstance(data, dict):


                data.setdefault("partials", {"usuario": "", "helena": ""})


                data.setdefault("turns", [])
                data.setdefault("active_operation", None)
                data.setdefault("microcut_recovery", None)


                return data


    except Exception as e:


        print(f"[Memoria corta] ⚠️ No se pudo leer: {e}")


    return _empty_short_term()


def _save_short_term_memory(data: dict) -> None:


    try:


        SHORT_TERM_PATH.parent.mkdir(parents=True, exist_ok=True)


        SHORT_TERM_PATH.write_text(


            json.dumps(data, ensure_ascii=False, indent=2),


            encoding="utf-8"


        )


    except Exception as e:


        print(f"[Memoria corta] ⚠️ No se pudo guardar: {e}")


def _update_short_term_partial(user_partial: str | None = None, helena_partial: str | None = None) -> None:


    from datetime import datetime


    with _short_term_lock:


        data = _load_short_term_memory()


        partials = data.setdefault("partials", {"usuario": "", "helena": ""})


        if user_partial is not None:


            partials["usuario"] = str(user_partial).strip()


        if helena_partial is not None:


            partials["helena"] = str(helena_partial).strip()


        data["updated"] = datetime.now().isoformat(timespec="seconds")


        _save_short_term_memory(data)


def _append_short_term_turn(user_text: str, helena_text: str) -> None:


    from datetime import datetime


    user_text = (user_text or "").strip()


    helena_text = (helena_text or "").strip()


    if not user_text and not helena_text:


        return


    with _short_term_lock:


        data = _load_short_term_memory()


        turns = data.setdefault("turns", [])


        turns.append({


            "time": datetime.now().isoformat(timespec="seconds"),


            "usuario": user_text,


            "helena": helena_text


        })


        # Mantener solo los ultimos turnos para no inflar el prompt.


        data["turns"] = turns[-12:]


        data["partials"] = {"usuario": "", "helena": ""}


        data["updated"] = datetime.now().isoformat(timespec="seconds")


        _save_short_term_memory(data)


def _set_short_term_active_operation(tool_name: str, args: dict | None, status: str = "running", result: str = "") -> None:
    from datetime import datetime

    safe_args = {}
    for key, value in (args or {}).items():
        text = str(value)
        if len(text) > 500:
            text = text[:497] + "..."
        safe_args[str(key)] = text

    with _short_term_lock:
        data = _load_short_term_memory()
        data["active_operation"] = {
            "tool": str(tool_name or ""),
            "args": safe_args,
            "status": status,
            "result": str(result or "")[:1200],
            "updated": datetime.now().isoformat(timespec="seconds"),
        }
        data["updated"] = datetime.now().isoformat(timespec="seconds")
        _save_short_term_memory(data)


def _clear_short_term_active_operation() -> None:
    from datetime import datetime

    with _short_term_lock:
        data = _load_short_term_memory()
        data["active_operation"] = None
        data["updated"] = datetime.now().isoformat(timespec="seconds")
        _save_short_term_memory(data)


def _set_short_term_microcut_recovery(snapshot: dict | None) -> None:
    from datetime import datetime

    with _short_term_lock:
        data = _load_short_term_memory()
        data["microcut_recovery"] = snapshot if isinstance(snapshot, dict) else None
        data["updated"] = datetime.now().isoformat(timespec="seconds")
        _save_short_term_memory(data)


def _format_short_term_for_prompt(data: dict) -> str:


    turns = data.get("turns") or []


    partials = data.get("partials") or {}
    active_operation = data.get("active_operation") or {}
    microcut_recovery = data.get("microcut_recovery") or {}


    if not turns and not partials.get("usuario") and not partials.get("helena") and not active_operation and not microcut_recovery:


        return ""


    lines = [


        "[MEMORIA DE CORTO PLAZO / CONTEXTO RECIENTE]",


        "Usa este contexto para continuar la conversacion despues de microcortes o reconexiones.",


        "No lo trates como memoria permanente; solo sirve para no volver a cero."


    ]


    for turn in turns[-6:]:


        u = (turn.get("usuario") or "").strip()


        h = (turn.get("helena") or "").strip()


        if u:


            lines.append(f"Usuario dijo recientemente: {u}")


        if h:


            lines.append(f"Helena respondio recientemente: {h}")

    if active_operation:
        tool = active_operation.get("tool") or "herramienta"
        status = active_operation.get("status") or "running"
        args = active_operation.get("args") or {}
        result = active_operation.get("result") or ""
        lines.append(f"Operacion activa antes de un corte: {tool} ({status}).")
        if args:
            arg_text = "; ".join(f"{k}={v}" for k, v in list(args.items())[:8])
            lines.append(f"Parametros de la operacion activa: {arg_text}")
        if result:
            lines.append(f"Resultado parcial/ultimo de la operacion activa: {result}")

    if microcut_recovery:
        lines.append("[RECUPERACION DE MICROCORTES]")
        reason = (microcut_recovery.get("reason") or "").strip()
        route = (microcut_recovery.get("audio_route") or "").strip()
        mode = (microcut_recovery.get("mode") or "").strip()
        last_user = (microcut_recovery.get("last_user_text") or "").strip()
        last_code_lab = (microcut_recovery.get("last_code_lab") or "").strip()
        partial_helena = (microcut_recovery.get("partial_helena") or "").strip()
        active_file = (microcut_recovery.get("active_file") or "").strip()
        if reason:
            lines.append(f"Ultimo microcorte recuperable: {reason}")
        if route or mode:
            lines.append(f"Estado antes del corte: ruta={route or 'desconocida'}, modo={mode or 'desconocido'}.")
        if active_file:
            lines.append(f"Archivo activo antes del corte: {active_file}")
        if last_user:
            lines.append(f"Ultimo pedido de Leo antes del corte: {last_user}")
        if last_code_lab:
            lines.append(f"Contexto CODE LAB antes del corte: {last_code_lab}")
        if partial_helena:
            lines.append(f"Helena estaba diciendo/trabajando en: {partial_helena}")
        lines.append("Al reconectar, retoma exactamente esa tarea. No saludes de nuevo, no reinicies la conversacion y no pidas que Leo repita salvo que falte un dato critico.")


    if partials.get("usuario"):


        lines.append(f"Texto parcial del usuario antes de un corte: {partials['usuario']}")


    if partials.get("helena"):


        lines.append(f"Texto parcial de Helena antes de un corte: {partials['helena']}")


    return "\n".join(lines) + "\n"


_last_memory_input = ""


def _update_memory_async(user_text: str, helena_text: str) -> None:


    global _last_memory_input


    user_text   = (user_text   or "").strip()


    helena_text = (helena_text or "").strip()


    if len(user_text) < 5 or user_text == _last_memory_input:


        return


    _last_memory_input = user_text


    try:


        api_key = _get_api_key()


        if not should_extract_memory(user_text, helena_text, api_key):


            return


        data = extract_memory(user_text, helena_text, api_key)


        if data:


            update_memory(data)


            print(f"[Memoria] ✅ {list(data.keys())}")


    except Exception as e:


        if "429" not in str(e):


            print(f"[Memoria] ⚠️ {e}")


TOOL_DECLARATIONS = [


    {


        "name": "open_app",


        "description": "Abre cualquier aplicación en Windows.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "app_name": {"type": "STRING", "description": "Nombre exacto de la aplicación"}


            },


            "required": ["app_name"]


        }


    },
    {
        "name": "system_control",
        "description": "Control seguro del sistema: estado de seguridad, escaneos Defender, procesos y servicios. Acciones: processes/list_processes, kill_process con name o pid, quick_scan, full_scan, custom_scan, threats, security_status. No desactiva antivirus ni firewall.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "security_status, quick_scan, full_scan, custom_scan, threats, open_security, open_settings, processes, kill_process, services, open_path"},
                "path": {"type": "STRING"},
                "name": {"type": "STRING"},
                "pid": {"type": "STRING"},
                "process": {"type": "STRING"},
                "force": {"type": "STRING"},
                "limit": {"type": "NUMBER"}
            },
            "required": ["action"]
        }
    },


    {


        "name": "web_search",


        "description": "Busca información en internet.",


        "parameters": {


            "type": "OBJECT",


            "properties": {"query": {"type": "STRING"}},


            "required": ["query"]


        }


    },


    {


        "name": "weather_report",


        "description": "Da el reporte del clima.",


        "parameters": {


            "type": "OBJECT",


            "properties": {"city": {"type": "STRING"}},


            "required": ["city"]


        }


    },


    {


        "name": "text_output",


        "description": "Router seguro para mostrar o enviar texto. Usa HUD por defecto. Si el usuario pide mandar texto por Discord o WhatsApp, usar esta herramienta. No escribe en ventanas activas del navegador.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "message_text": {"type": "STRING", "description": "Texto completo a mostrar o enviar"},


                "target": {"type": "STRING", "description": "hud, discord o whatsapp"},


                "receiver": {"type": "STRING", "description": "Contacto opcional para WhatsApp; si se omite usa Mi numero"},


                "channel_id": {"type": "STRING", "description": "Canal de texto Discord opcional; si se omite usa discord_text_channel_id"},


                "title": {"type": "STRING", "description": "Título opcional para mostrar en HUD"}


            },


            "required": ["message_text", "target"]


        }


    },


    {


        "name": "send_message",


        "description": "Envía un mensaje por WhatsApp, Telegram u otra plataforma.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "receiver": {"type": "STRING"},


                "message_text": {"type": "STRING"},


                "platform": {"type": "STRING"}


            },


            "required": ["receiver", "message_text", "platform"]


        }


    },


    {


        "name": "reminder",


        "description": "Programa un recordatorio.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "date": {"type": "STRING"},


                "time": {"type": "STRING"},


                "message": {"type": "STRING"}


            },


            "required": ["date", "time", "message"]


        }


    },


    {


        "name": "youtube_video",


        "description": "Controla YouTube: reproducir, resumir, obtener información.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "action": {"type": "STRING"},


                "query": {"type": "STRING"}


            },


            "required": []


        }


    },


    {


        "name": "screen_process",


        "description": "Captura y analiza la pantalla o cámara.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "angle": {"type": "STRING"},


                "text": {"type": "STRING"}


            },


            "required": ["text"]


        }


    },


    {


        "name": "computer_settings",


        "description": "Controla configuraciones de la computadora. Acciones importantes: priority_high, priority_normal, security_status, threats, brightness_set con value 0-100, volume_set 0-100, shutdown/apagar, restart/reiniciar, cancel_shutdown.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "action": {"type": "STRING"},


                "description": {"type": "STRING"},


                "value": {"type": "STRING"},
                "level": {"type": "NUMBER"},
                "confirmed": {"type": "STRING"},
                "force": {"type": "BOOLEAN"}


            },


            "required": []


        }


    },


    {


        "name": "browser_control",


        "description": "Controla el navegador web Chromium/Edge. Acciones: list_tabs, list_edge_tabs, close_tab_by_title, switch_to_tab, new_tab, close_tab, go_to, search. Para Microsoft Edge usar browser=edge o action=list_edge_tabs.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "action": {"type": "STRING"},


                "url": {"type": "STRING"},


                "query": {"type": "STRING"},


                "text": {"type": "STRING"},


                "browser": {"type": "STRING"}


            },


            "required": ["action"]


        }


    },


    {


        "name": "file_controller",


        "description": "Gestiona archivos y carpetas con rutas seguras. Acciones: list, read, write, copy, move, rename, delete_safe, mkdir, info/permissions, find, largest, disk_usage.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "action": {"type": "STRING"},


                "path": {"type": "STRING"},
                "name": {"type": "STRING"},
                "destination": {"type": "STRING"},
                "new_name": {"type": "STRING"},
                "content": {"type": "STRING"},
                "overwrite": {"type": "BOOLEAN"},
                "confirm": {"type": "BOOLEAN"},
                "max_chars": {"type": "NUMBER"}


            },


            "required": ["action"]


        }


    },


    {


        "name": "desktop_control",


        "description": "Controla el escritorio: fondo de pantalla, organizar, limpiar.",


        "parameters": {


            "type": "OBJECT",


            "properties": {"action": {"type": "STRING"}},


            "required": ["action"]


        }


    },


    {


        "name": "code_helper",


        "description": "Escribe, refactoriza, explica, ejecuta o valida codigo. Acciones: explain, refactor, execute, build, agent_task, write, edit. Para cambios reales devuelve recibo CODE HELPER RESULT/CODE LAB RESULT con archivo, estado y backup.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "action": {"type": "STRING"},


                "description": {"type": "STRING"},
                "instruction": {"type": "STRING"},
                "language": {"type": "STRING"},
                "file_path": {"type": "STRING"},
                "output_path": {"type": "STRING"},
                "code": {"type": "STRING"},
                "args": {"type": "ARRAY", "items": {"type": "STRING"}},
                "timeout": {"type": "NUMBER"},
                "allow_self_edit": {"type": "BOOLEAN"},
                "dry_run": {"type": "BOOLEAN"}


            },


            "required": ["action"]


        }


    },


    {


        "name": "dev_agent",


        "description": "Analiza, planifica, valida o construye proyectos completos de forma controlada. Modos: dry_run, apply, validate. No instala dependencias ni abre editor salvo parametros explicitos.",


        "parameters": {


            "type": "OBJECT",


            "properties": {
                "description": {"type": "STRING"},
                "language": {"type": "STRING"},
                "project_name": {"type": "STRING"},
                "timeout": {"type": "NUMBER"},
                "mode": {"type": "STRING"},
                "max_files": {"type": "NUMBER"},
                "allow_install": {"type": "BOOLEAN"},
                "open_editor": {"type": "BOOLEAN"}
            },


            "required": ["description"]


        }


    },


    {


        "name": "agent_task",


        "description": "Ejecuta tareas complejas de múltiples pasos.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "goal": {"type": "STRING"},


                "priority": {"type": "STRING"}


            },


            "required": ["goal"]


        }


    },


    {


        "name": "computer_control",


        "description": "Control directo del ordenador: teclear, hacer clic, atajos, listar/cambiar ventanas y cerrar procesos con protecciones. Acciones: list_windows, switch_window con title/process/pid, alt_tab, kill_process con app_name/name/pid.",


        "parameters": {


            "type": "OBJECT",


            "properties": {
                "action": {"type": "STRING"},
                "title": {"type": "STRING"},
                "name": {"type": "STRING"},
                "app_name": {"type": "STRING"},
                "process": {"type": "STRING"},
                "pid": {"type": "STRING"},
                "text": {"type": "STRING"},
                "steps": {"type": "NUMBER"},
                "limit": {"type": "NUMBER"},
                "force": {"type": "BOOLEAN"},
                "confirmed": {"type": "STRING"}
            },


            "required": ["action"]


        }


    },


    {


        "name": "game_updater",


        "description": "Actualiza juegos de Steam o Epic Games.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "action": {"type": "STRING"},


                "game_name": {"type": "STRING"}


            },


            "required": []


        }


    },


    {


        "name": "flight_finder",


        "description": "Busca vuelos en Google Flights.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "origin": {"type": "STRING"},


                "destination": {"type": "STRING"},


                "date": {"type": "STRING"}


            },


            "required": ["origin", "destination", "date"]


        }


    },


    {


        "name": "file_processor",


        "description": "Procesa archivos de texto, codigo, imagen, PDF y otros formatos con limite de tamano y bloqueo de secretos. Acciones comunes: summarize, extract_text, info, explain, review, validate, format.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "file_path": {"type": "STRING"},


                "action": {"type": "STRING"},
                "instruction": {"type": "STRING"},
                "save": {"type": "BOOLEAN"},
                "max_chars": {"type": "NUMBER"}


            },


            "required": []


        }


    },


    {


        "name": "discord_mode",


        "description": "Conecta o desconecta a Helena del canal de voz de Discord. Usar cuando el usuario diga 'metete a Discord', 'entrar a Discord', 'salí de Discord' o similar.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "action": {"type": "STRING", "description": "enter para entrar, leave para salir, status para estado"},


                "target": {"type": "STRING", "description": "Opcional. Canal o alias solicitado: taberna, martin, martín, tincho, simio. Si está vacío usa La Taberna de Aden."}


            },


            "required": ["action"]


        }


    },    {


        "name": "discord_music",


        "description": "Reproductor de musica para Discord con cola. Acciones: play (reproducir URL o busqueda), pause (pausar), resume (reanudar), stop (detener), skip (saltar tema), queue (ver cola), clear (limpiar cola), volume (cambiar volumen 0-100), status (estado actual). La voz de Helena tiene prioridad sobre la musica.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "action": {"type": "STRING", "description": "play, pause, resume, stop, skip, queue, clear, volume, status"},


                "query": {"type": "STRING", "description": "Texto de busqueda o nombre de cancion (opcional para play)"},


                "url": {"type": "STRING", "description": "URL directa de audio (opcional para play)"},


                "volume": {"type": "NUMBER", "description": "Volumen 0-100 (para action=volume)"}


            },


            "required": ["action"]


        }


    },



    {


        "name": "shutdown_helena",


        "description": "Apaga completamente al asistente.",


        "parameters": {"type": "OBJECT", "properties": {}}


    },


    {


        "name": "save_memory",


        "description": "Guarda información importante del usuario en memoria a largo plazo.",


        "parameters": {


            "type": "OBJECT",


            "properties": {


                "category": {"type": "STRING"},


                "key": {"type": "STRING"},


                "value": {"type": "STRING"}


            },


            "required": ["category", "key", "value"]


        }


    },


]


class HelenaLive:


    def __init__(self, ui: HelenaUI):


        self.ui             = ui


        self.session        = None


        self.audio_in_queue = None


        self.out_queue      = None


        self._loop          = None

        self._session_generation = 0
        self._connection_attempt_count = 0
        self._reconnect_count = 0
        self._live_connection_established = False
        self._audio_input_queue_drop_count = 0
        self._audio_output_queue_saturation_count = 0
        self._audio_output_queue_drop_count = 0
        self._audio_send_error_count = 0
        self._audio_input_status_count = 0
        self._playback_error_count = 0
        self._last_playback_timing_log = 0.0
        self._pending_text_response_starts = []
        self._active_text_response_started_at = None
        self._response_timing_lock = threading.Lock()
        self._short_term_writer = ShortTermPartialWriter(
            lambda updates: _update_short_term_partial(**updates)
        )
        self._audio_timing_metrics = AudioTimingMetrics()
        self._last_audio_metrics_log = time.perf_counter()


        self._is_speaking   = False


        self._speaking_lock = threading.Lock()


        self.ui.on_text_command = self._on_text_command


        self.audio_route = "local"


        self._last_route_log = 0.0


        self._last_discord_input_log = 0.0


        # V26 Turn Guard: evita ecos, respuestas dobles y comandos Discord repetidos.

        self._speaking_until = 0.0
        self._assistant_audio_until = 0.0
        self._playback_active = False
        self._assistant_output_turn_active = False
        self._assistant_output_turn_complete = False
        self._assistant_output_last_audio_ts = 0.0
        self._code_lab_voice_guard_until = 0.0
        self._code_lab_local_audio_bytes = 0
        self._code_lab_local_audio_limit_bytes = 96_000
        self._code_lab_voice_notice_done = False

        self._last_local_discord_command = ""

        self._last_local_discord_command_ts = 0.0

        self._last_assistant_log_norm = ""

        self._last_assistant_log_ts = 0.0

        # V28: saludo de arranque solo una vez por ejecución.

        self._startup_greeting_done = False

        # V29.2.1 Safe Listening Gate
        # Evita que transcripciones accidentales del micrófono se traten como conversación.
        self._safe_listening_mode = False
        self._wake_window_until = 0.0
        self._last_ambient_ignore_log = 0.0

        # V29 Anti StandBy Watchdog: evita que Helena quede viva pero sin escuchar.
        now_v29 = time.time()
        self._last_mic_callback_ts = now_v29
        self._last_mic_audio_ts = now_v29
        self._last_gemini_event_ts = now_v29
        self._last_receive_any = now_v29
        self._last_gemini_audio_ts = 0.0
        self._last_turn_complete_ts = now_v29
        self._last_watchdog_log_ts = 0.0
        self._last_hard_watchdog_ts = 0.0
        self._last_forced_listening_ts = 0.0
        self._last_input_recovery_ts = 0.0
        self._last_input_wakeup_text = ""
        self._live_transcription_disabled = False
        self._input_pause_until = 0.0
        self._last_input_drain_ts = 0.0  # V32.6: frecuencia del drenado completo de mic
        self._last_user_text_command = ""
        self._last_code_lab_summary = ""
        self._recoverable_microcut_count = 0
        self._microcut_resume_pending = False


        set_discord_context(self)


    def close(self) -> None:
        self._short_term_writer.close()


    def _is_code_lab_text_first_request(self, text: str) -> bool:
        head = (text or "")[:1200].lower()
        return "[code lab / text first]" in head or "modo code lab" in head

    def _remember_text_continuity(self, text: str) -> None:
        clean = " ".join(str(text or "").split())
        if not clean:
            return
        self._last_user_text_command = clean[:1200]
        if self._is_code_lab_text_first_request(clean):
            summary = []
            for marker in ("Archivo:", "Lenguaje:", "Lineas:", "Caracteres:", "Pedido de Leo:"):
                idx = clean.find(marker)
                if idx >= 0:
                    summary.append(clean[idx: idx + 160])
            self._last_code_lab_summary = " | ".join(summary)[:900] or clean[:900]

    def _activate_code_lab_voice_guard(self) -> None:
        self._code_lab_voice_guard_until = time.time() + 180.0
        self._code_lab_local_audio_bytes = 0
        self._code_lab_voice_notice_done = False
        self._drain_queue(getattr(self, "audio_in_queue", None))
        try:
            self.ui.write_log("Sistema: CODE LAB en modo texto primero. Voz local ultra breve para evitar cortes.")
        except Exception:
            pass

    def _allow_code_lab_local_audio_chunk(self, chunk_size: int) -> bool:
        if time.time() > float(getattr(self, "_code_lab_voice_guard_until", 0.0) or 0.0):
            return True
        max_bytes = int(getattr(self, "_code_lab_local_audio_limit_bytes", 220_000) or 220_000)
        used = int(getattr(self, "_code_lab_local_audio_bytes", 0) or 0)
        if used + max(0, int(chunk_size or 0)) > max_bytes:
            if not getattr(self, "_code_lab_voice_notice_done", False):
                self._code_lab_voice_notice_done = True
                try:
                    self.ui.write_log("Sistema: audio local largo de CODE LAB bloqueado; la explicacion completa queda en HUD.")
                except Exception:
                    pass
                print("[CodeLab] Audio local largo bloqueado y cola drenada; HUD conserva el texto.")
            self._drain_queue(getattr(self, "audio_in_queue", None))
            return False
        self._code_lab_local_audio_bytes = used + max(0, int(chunk_size or 0))
        return True

    def _capture_microcut_continuity(self, reason: str = "") -> None:
        self._short_term_writer.flush()
        partials = (_load_short_term_memory().get("partials") or {})
        active_file = ""
        try:
            active_file = str(getattr(self.ui, "current_file", "") or "")
        except Exception:
            active_file = ""
        snapshot = {
            "reason": str(reason or "")[:500],
            "audio_route": str(getattr(self, "audio_route", "local") or "local"),
            "mode": "CODE LAB" if getattr(self, "_last_code_lab_summary", "") else "CONVERSATION",
            "last_user_text": str(getattr(self, "_last_user_text_command", "") or "")[:1200],
            "last_code_lab": str(getattr(self, "_last_code_lab_summary", "") or "")[:900],
            "partial_user": str(partials.get("usuario") or "")[:900],
            "partial_helena": str(partials.get("helena") or "")[:1200],
            "active_file": active_file[:500],
        }
        _set_short_term_microcut_recovery(snapshot)
        self._microcut_resume_pending = True

    def _on_text_command(self, text: str):
        text = (text or "").strip()

        # V29: evitar bloquear la UI o re-iniciar respuestas cuando Helena está hablando
        now = time.time()
        if self._is_speaking and (self._speaking_until > now or self._assistant_output_turn_active):
            print(f"[TextInput] ⏭️ Ignorado: Helena hablando (hasta {self._speaking_until:.1f}, turn_active={self._assistant_output_turn_active})")
            return

        if text:
            self._remember_text_continuity(text)
            if self._is_code_lab_text_first_request(text):
                self._activate_code_lab_voice_guard()
            # V29.4: comando local de recuperación. No depende de Gemini.
            try:
                norm = self._normalize_command_text(text)
            except Exception:
                norm = text.lower()
            wake_phrases = (
                "helena desperta", "elena desperta", "helena despertate", "elena despertate",
                "helena reinicia escucha", "elena reinicia escucha",
                "helena reinicia la escucha", "elena reinicia la escucha",
                "helena desbloquea escucha", "elena desbloquea escucha",
                "helena escucha", "elena escucha",
            )
            if any(p in norm for p in wake_phrases):
                self.set_speaking(False)
                with self._speaking_lock:
                    self._is_speaking = False
                    self._speaking_until = 0.0
                try:
                    self.ui.write_log("Sistema: escucha reiniciada. Helena vuelve a LISTENING.")
                    self.ui.set_state("LISTENING")
                except Exception:
                    pass
                print("[Recovery] 🟢 Escucha desbloqueada por comando local de Leo.")
                return

            self._short_term_writer.submit(user_partial=text)
            if self._handle_local_priority_command(text):
                return

        if not self._loop or not self.session:
            print("[TextInput] ⚠️ No hay sesión activa todavía; ignoro texto.")
            return

        async def _send_text_to_live():
            self._mark_text_response_started()
            try:
                # V33.3: limitar la sincronización síncrona para reducir latencia.
                # Solo drenar un máximo de 10 elementos para no bloquear la UI.
                drained = self._drain_queue(getattr(self, "out_queue", None))
                if drained > 10:
                    print(f"[TextInput] ⚠️ Drenado {drained} elementos de la cola (posible latencia)")
                self._input_pause_until = time.time() + 2.0
                await self.session.send_client_content(
                    turns={"parts": [{"text": text}]},
                    turn_complete=True
                )
                self._mark_activity("text")
            except Exception as exc:
                print(f"[TextInput] No pude enviar texto a Gemini; reintento: {exc}")
                await self.session.send_client_content(
                    turns={"parts": [{"text": text}]},
                    turn_complete=True
                )

        fut = asyncio.run_coroutine_threadsafe(_send_text_to_live(), self._loop)
        try:
            self._last_text_sent_to_gemini = time.time()
        except Exception:
            pass


    def _mark_text_response_started(self) -> None:
        started_at = time.perf_counter()
        with self._response_timing_lock:
            self._pending_text_response_starts.append(started_at)
            if len(self._pending_text_response_starts) > 16:
                self._pending_text_response_starts.pop(0)

    def _record_text_response_first_output(self) -> None:
        started_at = None
        with self._response_timing_lock:
            if self._active_text_response_started_at is None and self._pending_text_response_starts:
                started_at = self._pending_text_response_starts.pop(0)
                self._active_text_response_started_at = started_at
        if started_at is not None:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            print(f"[GeminiTiming] text_to_first_output_ms={elapsed_ms:.1f}")

    def _record_text_response_complete(self) -> None:
        with self._response_timing_lock:
            started_at = self._active_text_response_started_at
            self._active_text_response_started_at = None
        if started_at is not None:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            print(f"[GeminiTiming] text_response_total_ms={elapsed_ms:.1f}")


    def _record_audio_timing(self, name: str, elapsed_ms: float) -> None:
        self._audio_timing_metrics.record(name, elapsed_ms)
        now = time.perf_counter()
        if now - self._last_audio_metrics_log < 15.0:
            return
        self._last_audio_metrics_log = now
        fields = []
        for metric_name in (
            "audio_in_queue_age",
            "audio_in_callback",
            "audio_in_callback_dispatch",
            "audio_in_send",
            "audio_out_queue_wait",
            "audio_out_stream_write",
        ):
            summary = self._audio_timing_metrics.summary(metric_name)
            if summary is not None:
                fields.append(
                    f"{metric_name}_ms[p50/p95/max]="
                    f"{summary['p50_ms']:.1f}/{summary['p95_ms']:.1f}/"
                    f"{summary['max_ms']:.1f} n={summary['samples']} "
                    f"window={summary['window']}"
                )
        if fields:
            print(
                "[AudioMetrics] "
                + " ".join(fields)
                + f" in_drops={self._audio_input_queue_drop_count}"
                + f" out_drops={self._audio_output_queue_drop_count}"
                + f" mic_status={self._audio_input_status_count}"
                + f" send_errors={self._audio_send_error_count}"
                + f" playback_errors={self._playback_error_count}"
            )


    def _mark_activity(self, kind: str = ""):
        """V29: marca actividad real para que el watchdog sepa que Helena sigue viva."""
        now = time.time()
        try:
            if kind in ("local_audio", "discord_audio", "audio"):
                self._last_gemini_event_ts = now
                self._last_gemini_audio_ts = now
            elif kind in ("input", "mic", "user"):
                if kind == "mic":
                    self._last_mic_audio_ts = now
                else:
                    self._last_gemini_event_ts = now
            elif kind == "turn_complete":
                self._last_gemini_event_ts = now
                self._last_turn_complete_ts = now
            elif kind and kind != "text":
                self._last_gemini_event_ts = now
        except Exception:
            pass

    def _force_listening(self, reason: str = ""):
        """V29: libera bloqueos de habla/cola cuando Helena queda en standby."""
        now = time.time()
        with self._speaking_lock:
            self._is_speaking = False
            self._speaking_until = 0.0
        try:
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
        except Exception:
            pass
        if now - getattr(self, "_last_forced_listening_ts", 0.0) > 10.0:
            self._last_forced_listening_ts = now
            msg = "[Watchdog] 🟢 Escucha liberada"
            if reason:
                msg += f" ({reason})"
            print(msg)
            try:
                self.ui.write_log("Sistema: escucha de Helena reactivada." + (f" Motivo: {reason}" if reason else ""))
            except Exception:
                pass

    def _drain_queue(self, queue) -> int:
        removed = 0
        if queue is None:
            return removed
        try:
            while True:
                queue.get_nowait()
                removed += 1
        except Exception:
            return removed

    def _trim_queue_to(self, queue, target_size: int) -> int:
        removed = 0
        if queue is None:
            return removed
        target_size = max(0, int(target_size or 0))
        try:
            while queue.qsize() > target_size:
                queue.get_nowait()
                removed += 1
        except Exception:
            pass
        return removed

    def _put_nowait_drop_oldest(self, queue, item, trim_to: int | None = None) -> bool:
        if queue is None:
            return False
        try:
            if trim_to is not None:
                self._trim_queue_to(queue, int(trim_to))
            queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except Exception:
                pass
            try:
                queue.put_nowait(item)
                return True
            except asyncio.QueueFull:
                return False

    def _resample_pcm_s16_mono(self, pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
        if not pcm or src_rate == dst_rate:
            return pcm or b""
        try:
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            if audio.size == 0:
                return b""
            duration = audio.size / float(src_rate)
            dst_size = max(1, int(round(duration * float(dst_rate))))
            x_old = np.linspace(0.0, duration, num=audio.size, endpoint=False)
            x_new = np.linspace(0.0, duration, num=dst_size, endpoint=False)
            out = np.interp(x_new, x_old, audio)
            return (np.clip(out, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        except Exception as exc:
            now = time.time()
            if now - getattr(self, "_last_resample_error_log", 0.0) > 5.0:
                self._last_resample_error_log = now
                print(f"[AudioOut] no pude remuestrear audio; uso PCM original: {exc}")
            return pcm

    def _has_pending_local_audio(self) -> bool:
        try:
            now = time.time()
            return bool(
                getattr(self, "audio_route", "local") == "local"
                and (
                    bool(getattr(self, "_playback_active", False))
                    or (self.audio_in_queue is not None and self.audio_in_queue.qsize() > 0)
                    or (float(getattr(self, "_assistant_audio_until", 0.0) or 0.0) > now)
                )
            )
        except Exception:
            return False

    def _assistant_is_outputting_audio(self) -> bool:
        now = time.time()
        active_turn = bool(
            getattr(self, "_assistant_output_turn_active", False)
            and now - float(getattr(self, "_assistant_output_last_audio_ts", 0.0) or 0.0) < 12.0
        )
        return bool(
            getattr(self, "_playback_active", False)
            or float(getattr(self, "_assistant_audio_until", 0.0) or 0.0) > now
            or active_turn
            or self._has_pending_local_audio()
        )

    def _release_speaking_when_audio_idle(self, generation: int | None = None):
        if generation is not None and generation != getattr(self, "_session_generation", 0):
            return
        if self._has_pending_local_audio():
            return
        if getattr(self, "_assistant_output_turn_active", False):
            now = time.time()
            last_audio = float(getattr(self, "_assistant_output_last_audio_ts", 0.0) or 0.0)
            turn_done = bool(getattr(self, "_assistant_output_turn_complete", False))
            # V32.6: 1.0s en local (antes 2.0) para reducir el bloqueo del mic;
            # en Discord se mantiene 2.0s por el buffer del canal de voz.
            hold_s = 2.0 if getattr(self, "audio_route", "local") == "discord" else 1.0
            if not turn_done and now - last_audio < hold_s:
                return
            self._assistant_output_turn_active = False
            self._assistant_output_turn_complete = False
        self._assistant_audio_until = 0.0
        self.set_speaking(False)

    def _reset_session_audio_state(self):
        in_removed = self._drain_queue(getattr(self, "audio_in_queue", None))
        out_removed = self._drain_queue(getattr(self, "out_queue", None))
        self.set_speaking(False)
        self._assistant_output_turn_active = False
        self._assistant_output_turn_complete = False
        if in_removed or out_removed:
            print(f"[AudioRoute] colas limpiadas: playback={in_removed}, input={out_removed}")

    def _handle_local_wakeup_command(self, text: str) -> bool:
        """Comandos manuales: 'Helena despertá', 'reiniciá escucha', etc."""
        t = _strip_accents((text or "").lower())
        wake_words = (
            "desperta", "despertate", "reinicia escucha", "reiniciar escucha",
            "reinicia la escucha", "reiniciame la escucha", "reactiva escucha",
            "reactivar escucha", "volviendo", "me escuchas", "me escuchas?",
        )
        if any(w in t for w in wake_words):
            self._last_input_wakeup_text = text or ""
            self._force_listening("comando de Leo")
            return True
        return False

    async def _anti_standby_watchdog(self):
        """V29: recupera a Helena si el bloqueo de habla o el player de Discord quedan colgados."""
        while True:
            await asyncio.sleep(5)
            now = time.time()
            try:
                with self._speaking_lock:
                    speaking = bool(self._is_speaking)
                    until = float(getattr(self, "_speaking_until", 0.0) or 0.0)

                # Si el speaking lock venció, no dejamos el micrófono local bloqueado.
                if speaking and until and now > until + 1.5:
                    self._force_listening("speaking lock vencido")
                    continue

                # Si está en Discord y no hubo audio real reciente, no mantener estado SPEAKING.
                if getattr(self, "audio_route", "local") == "discord":
                    last_audio = max(float(getattr(self, "_last_gemini_audio_ts", 0.0) or 0.0), float(getattr(self, "_last_turn_complete_ts", 0.0) or 0.0))
                    if speaking and last_audio and now - last_audio > 18.0:
                        self._force_listening("Discord sin audio pendiente")
                        continue

                last_mic_ok = max(
                    float(getattr(self, "_last_realtime_send", 0.0) or 0.0),
                    float(getattr(self, "_last_mic_sent_to_gemini", 0.0) or 0.0),
                )
                last_gemini = max(
                    float(getattr(self, "_last_receive_any", 0.0) or 0.0),
                    float(getattr(self, "_last_gemini_event_ts", 0.0) or 0.0),
                )
                mic_active = bool(last_mic_ok and now - last_mic_ok < 12.0)
                gemini_silent = bool(last_gemini and now - last_gemini > 90.0)
                if self.session and mic_active and gemini_silent and now - getattr(self, "_last_hard_watchdog_ts", 0.0) > 90.0:
                    self._last_hard_watchdog_ts = now
                    print("[GeminiWatchdog] Gemini mudo por 90s con mic activo. Reiniciando sesión Live.")
                    try:
                        self.ui.write_log("Sistema: Gemini Live quedó mudo con micrófono activo. Reconectando sesión.")
                    except Exception:
                        pass
                    await asyncio.to_thread(
                        self._capture_microcut_continuity,
                        "Gemini mudo por 90s con mic activo",
                    )
                    self._reset_session_audio_state()
                    raise LiveSilentWatchdogRestart("Gemini mudo por 90s con mic activo")

                # Heartbeat liviano para saber que no murió; no envía nada a Gemini.
                if now - getattr(self, "_last_watchdog_log_ts", 0.0) > 60.0:
                    self._last_watchdog_log_ts = now
                    route = getattr(self, "audio_route", "local")
                    state = "SPEAKING" if speaking else "LISTENING"
                    print(f"[Watchdog] estado={state}, ruta={route}, mic_cb={int(now - getattr(self, '_last_mic_callback_ts', now))}s, gemini={int(now - getattr(self, '_last_gemini_event_ts', now))}s")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[Watchdog] ⚠️ Error no fatal: {exc}")

    def set_speaking(self, value: bool):


        now = time.time()
        # V32.6: el tiempo de bloqueo del mic depende de la ruta de audio:
        # local usa cola corta (buffer de salida minimo); Discord conserva la
        # cola larga de V26 (el canal de voz retiene el audio mas tiempo).
        tail_s = SPEAKING_TAIL_DISCORD_S if getattr(self, "audio_route", "local") == "discord" else SPEAKING_TAIL_LOCAL_S

        audioin_flushed = 0
        with self._speaking_lock:

            self._is_speaking = bool(value)

            self._speaking_until = now + tail_s if value else 0.0
            if not value:
                self._assistant_audio_until = 0.0
                # V32.7: Helena termino de hablar y el mic se reactiva: se vacia
                # la cola de AudioIn (out_queue) ANTES de soltar el lock, para
                # que los chunks acumulados durante la reproduccion nunca lleguen
                # a Gemini. El mic solo reenvia audio capturado en tiempo real.
                audioin_flushed = self._drain_queue(getattr(self, "out_queue", None))

        if audioin_flushed:
            now_log = time.time()
            if now_log - float(getattr(self, "_last_audioin_flush_log", 0.0) or 0.0) > 2.0:
                self._last_audioin_flush_log = now_log
                print(f"[AudioIn] flush al reactivar el mic: descartados={audioin_flushed} chunks de la reproduccion")


        if value:
            # V35_9_2: Mark voice active when Helena starts speaking
            try:
                from actions.discord_mode import _bridge
                if _bridge:
                    _bridge.set_voice_active(True)
                    print("[VoicePriority] set_voice_active(True) called from set_speaking")
            except Exception as exc:
                print(f"[VoicePriority] error setting voice active: {exc}")

            self.ui.set_state("SPEAKING")


            # V26: watchdog más largo. Antes eran 3s y en Discord abría el micrófono

            # mientras la frase todavía estaba saliendo por el buffer del canal.

            def auto_reset(deadline: float):

                # V32.6: tail de la ruta + margen (antes era 5.25s fijo)
                time.sleep(tail_s + 0.75)

                with self._speaking_lock:

                    still_same_window = self._is_speaking and time.time() >= deadline

                if still_same_window:

                    if self._has_pending_local_audio():
                        return
                    self.set_speaking(False)


            threading.Thread(target=auto_reset, args=(self._speaking_until,), daemon=True).start()


        elif not self.ui.muted:

            self.ui.set_state("LISTENING")


    def _extend_speaking_guard(self, seconds: float = 4.0):
        """Marca una ventana breve donde Helena está hablando.

        V29.4: antes esto podía dejar _is_speaking=True sin auto-liberarse,
        especialmente en Discord. Ahora siempre programa una liberación segura.
        """
        seconds = max(0.5, float(seconds or 0.5))
        until = time.time() + seconds
        with self._speaking_lock:
            self._is_speaking = True
            self._speaking_until = max(getattr(self, "_speaking_until", 0.0), until)
            deadline = self._speaking_until
        try:
            self.ui.set_state("SPEAKING")
        except Exception:
            pass

        def auto_release(expected_deadline: float):
            time.sleep(seconds + 0.75)
            with self._speaking_lock:
                expired = self._is_speaking and time.time() >= getattr(self, "_speaking_until", 0.0) and getattr(self, "_speaking_until", 0.0) <= expected_deadline + 0.05
                if expired:
                    self._is_speaking = False
                    self._speaking_until = 0.0
            if expired:
                try:
                    if not self.ui.muted:
                        self.ui.set_state("LISTENING")
                except Exception:
                    pass
                print("[TurnGuard] 🟢 Speaking guard liberado automáticamente.")

        threading.Thread(target=auto_release, args=(deadline,), daemon=True).start()

    def _hold_assistant_audio_guard(self, seconds: float | None = None):
        """Pausa el mic mientras Gemini esta emitiendo audio, incluso entre chunks.
        
        V32.6: el guard depende de la ruta (1s local / 3s discord) y el drenado
        completo de la cola de mic se limita a 1 vez por segundo para evitar
        cierres de buffer abruptos en cada chunk de audio de Gemini.
        """
        now = time.time()
        if seconds is None:
            seconds = ASSISTANT_GUARD_DISCORD_S if getattr(self, "audio_route", "local") == "discord" else ASSISTANT_GUARD_LOCAL_S
        until = now + max(0.5, float(seconds or 0.5))
        if now - float(getattr(self, "_last_input_drain_ts", 0.0) or 0.0) >= INPUT_DRAIN_MIN_GAP_S:
            self._last_input_drain_ts = now
            drained = self._drain_queue(getattr(self, "out_queue", None))
        else:
            drained = 0
        with self._speaking_lock:
            self._assistant_audio_until = max(getattr(self, "_assistant_audio_until", 0.0), until)
            self._speaking_until = max(getattr(self, "_speaking_until", 0.0), self._assistant_audio_until)
            self._is_speaking = True
        if drained and now - getattr(self, "_last_input_drain_log", 0.0) > 2.0:
            self._last_input_drain_log = now
            print(f"[AudioIn] cola de mic descartada mientras habla Helena: {drained} chunks")
        try:
            self.ui.set_state("SPEAKING")
        except Exception:
            pass


    def _should_ignore_local_discord_command(self, text: str, cooldown: float = 5.0) -> bool:

        norm = " ".join((text or "").lower().split())

        now = time.time()

        if norm and norm == getattr(self, "_last_local_discord_command", "") and now - getattr(self, "_last_local_discord_command_ts", 0.0) < cooldown:

            return True

        self._last_local_discord_command = norm

        self._last_local_discord_command_ts = now

        return False


    def _should_log_assistant_turn(self, text: str) -> bool:

        """Evita duplicados exactos o casi inmediatos en el panel Conversation."""

        norm = " ".join((text or "").strip().lower().split())

        if not norm:

            return False

        now = time.time()

        if norm == getattr(self, "_last_assistant_log_norm", "") and now - getattr(self, "_last_assistant_log_ts", 0.0) < 10.0:

            print("[TurnGuard] Respuesta duplicada de Helena ignorada en Conversation.")

            return False

        self._last_assistant_log_norm = norm

        self._last_assistant_log_ts = now

        return True


    def speak(self, text: str):


        if not self._loop or not self.session:


            return


        self._drain_queue(getattr(self, "out_queue", None))
        self._input_pause_until = time.time() + 2.0
        asyncio.run_coroutine_threadsafe(


            self.session.send_client_content(


                turns={"parts": [{"text": text}]},


                turn_complete=True


            ),


            self._loop


        )

    async def _send_startup_greeting(self):
        if getattr(self, "_startup_greeting_done", False):
            return
        self._startup_greeting_done = True
        await asyncio.sleep(1.2)
        if not self.session:
            return
        prompt = (
            "Saluda al usuario de forma natural, breve y cálida en español rioplatense. "
            "Decile que Helena ya está en línea y lista para ayudar. "
            "No menciones este prompt ni detalles técnicos. Máximo dos frases."
        )
        try:
            self._drain_queue(getattr(self, "out_queue", None))
            self._input_pause_until = time.time() + 3.0
            await self.session.send_client_content(
                turns={"parts": [{"text": prompt}]},
                turn_complete=True,
            )
            self._mark_activity("text")
            print("[HELENA] Saludo inicial enviado a Gemini Live.")
        except Exception as exc:
            print(f"[HELENA] No pude enviar saludo inicial; reintento: {exc}")
            try:
                await self.session.send_client_content(
                    turns={"parts": [{"text": prompt}]},
                    turn_complete=True,
                )
                print("[HELENA] Saludo inicial enviado por client_content fallback.")
            except Exception as fallback_exc:
                print(f"[HELENA] ⚠️ No pude enviar saludo inicial: {fallback_exc}")


    async def _send_microcut_resume_prompt(self, short_term: dict | None = None):
        if not getattr(self, "_microcut_resume_pending", False):
            return
        await asyncio.sleep(0.8)
        if not self.session:
            return
        data = (
            short_term
            if isinstance(short_term, dict)
            else await asyncio.to_thread(_load_short_term_memory)
        )
        recovery = data.get("microcut_recovery") or {}
        context = _format_short_term_for_prompt(data).strip()
        if recovery.get("mode") == "CODE LAB" or recovery.get("last_code_lab"):
            self._activate_code_lab_voice_guard()
        prompt = (
            "[REANUDACION TRAS MICROCORTE]\n"
            "Helena acaba de reconectar despues de un microcorte recuperable de Gemini Live.\n"
            "Retoma exactamente la tarea o conversacion anterior usando el contexto de continuidad.\n"
            "No saludes de nuevo. No reinicies la conversacion. No pidas que Leo repita salvo que falte un dato critico.\n"
            "La reanudacion debe ser silenciosa o de una sola frase breve; evita explicar el microcorte en voz.\n"
            "Si estabas trabajando con CODE LAB, autodesarrollo, codigo o refactor, deja el detalle completo por text_output target=hud y usa voz local solo para una frase breve de confirmacion.\n"
            "Si estabas a mitad de una respuesta, continua desde el punto mas probable y aclara brevemente que recuperaste el hilo.\n\n"
            f"{context[:5000]}"
        )
        try:
            self._drain_queue(getattr(self, "out_queue", None))
            self._input_pause_until = time.time() + 1.0
            await self.session.send_client_content(
                turns={"parts": [{"text": prompt}]},
                turn_complete=True,
            )
            self._microcut_resume_pending = False
            self._mark_activity("text")
            print("[HELENA] Reanudacion post-microcorte enviada a Gemini Live.")
        except Exception as exc:
            print(f"[HELENA] No pude enviar reanudacion post-microcorte: {exc}")


    def speak_error(self, tool_name: str, error: str):


        short = str(error)[:120]


        self.ui.write_log(f"Error: {tool_name} — {short}")


        self.speak(f"Señor, {tool_name} encontró un error. {short}")


    def _normalize_command_text(self, text: str) -> str:

        import unicodedata

        t = (text or "").lower()

        return "".join(ch for ch in unicodedata.normalize("NFD", t) if unicodedata.category(ch) != "Mn")


    def _is_priority_command(self, text: str):

        t_norm = self._normalize_command_text(text)

        if not any(w in t_norm for w in ("prioridad", "recursos", "performance", "rendimiento", "entrecorta", "cortes", "lag", "alta")):

            return None

        high_words = (

            "prioridad alta", "dar mas prioridad", "darle mas prioridad", "dale mas prioridad",

            "darle mas prioridad al programa", "mas prioridad al programa", "ponele prioridad",

            "ponete en prioridad", "modo performance", "mas recursos", "asignar mas recursos",

            "asignale mas recursos", "subi la prioridad", "subir la prioridad", "evitar cortes",

            "no se entrecorte", "rendimiento alto", "alta prioridad", "prioridad al programa"

        )

        normal_words = (

            "prioridad normal", "volver prioridad normal", "restaura prioridad",

            "restaurar prioridad", "modo normal", "saca prioridad alta"

        )

        status_words = ("que prioridad", "estado prioridad", "ver prioridad", "prioridad actual")

        if any(w in t_norm for w in normal_words):

            return {"action": "priority_normal", "value": "normal"}

        if any(w in t_norm for w in status_words):

            return {"action": "get_priority"}

        if any(w in t_norm for w in high_words):

            return {"action": "priority_high", "value": "high"}

        return None


    def _handle_local_priority_command(self, text: str) -> bool:

        params = self._is_priority_command(text)

        if not params:

            return False

        try:

            self.ui.write_log(f"Sistema: comando de prioridad detectado localmente: {params}")

            result = computer_settings(parameters=params, response=None, player=self.ui)

            self.ui.write_log(f"[Priority] {result}")

            # No fingir: solo confirmar si el resultado real vino confirmado por la herramienta.

            if str(result).startswith("CONFIRMED:"):

                self.ui.write_log(f"Helena: Listo, Leíto. {str(result).replace('CONFIRMED:', '').strip()}")

            else:

                self.ui.write_log(f"Helena: No pude confirmarlo automáticamente. {result}")

            return True

        except Exception as exc:

            self.ui.write_log(f"[Priority] Error aplicando prioridad: {exc}")

            print(f"[Priority] Error aplicando prioridad: {exc}")

            return True


    # V29.2.1 Safe Listening Gate
    def _safe_listen_norm(self, text: str) -> str:
        import unicodedata, re
        t = (text or "").lower().strip()
        t = "".join(ch for ch in unicodedata.normalize("NFD", t) if unicodedata.category(ch) != "Mn")
        t = re.sub(r"[^a-z0-9ñ\s]+", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    def _repair_mojibake(self, text: str) -> str:
        """Corrige texto UTF-8 que llego decodificado como latin-1/cp1252."""
        if not text:
            return ""
        markers = ("\u00c3", "\u00c2", "\u00e2\u20ac", "\u00e2\u20ac\u0153", "\u00e2\u20ac\u009d", "\u00f0\u0178")
        if not any(m in text for m in markers):
            return text
        for enc in ("latin-1", "cp1252"):
            try:
                repaired = text.encode(enc).decode("utf-8")
            except Exception:
                continue
            if repaired and repaired.count("\ufffd") <= text.count("\ufffd"):
                return repaired
        return text

    def _clean_live_transcript_text(self, text: str) -> str:
        """Limpia fragmentos de STT y descarta alfabetos/basura que Gemini oye por error."""
        import re
        import unicodedata

        text = self._repair_mojibake(str(text or ""))
        text = unicodedata.normalize("NFC", text)
        text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return ""

        suspicious = 0
        letters = 0
        for ch in text:
            if not ch.isalpha():
                continue
            letters += 1
            name = unicodedata.name(ch, "")
            if not name.startswith("LATIN "):
                suspicious += 1

        if suspicious and (suspicious >= 2 or suspicious / max(letters, 1) > 0.20):
            preview = text[:80].replace("\n", " ")
            print(f"[Transcription] fragmento descartado por alfabeto inesperado: {preview!r}")
            return ""

        return text

    def _append_live_transcript_fragment(self, buf: list[str], raw_text: str) -> str:
        text = self._clean_live_transcript_text(raw_text)
        if not text:
            return ""

        current = " ".join(buf).strip()
        if not current:
            buf.append(text)
            return text

        if text == current or current.endswith(text):
            return current

        if text.startswith(current):
            buf[:] = [text]
            return text

        buf.append(text)
        return " ".join(buf).strip()

    def _safe_listen_should_accept_user_text(self, text: str) -> bool:
        # V29.3 override: escucha normal. ListenGate desactivado por inestabilidad.
        return True
        """Acepta texto del micrófono solo si parece dirigido a Helena.
        El texto escrito en HUD no pasa por este filtro; solo filtra transcripciones de audio.
        """
        import time
        if not getattr(self, "_safe_listening_mode", True):
            return True
        t = self._safe_listen_norm(text)
        if not t:
            return False

        wake_words = (
            "helena", "elena", "hele na", "ele na", "vivi",
            "mi amor", "amor", "bebe", "bb"
        )
        direct_commands = (
            "metete a discord", "entra a discord", "sal de discord", "sali de discord",
            "canal de martin", "canal de tincho", "canal de simio", "taberna",
            "desperta", "reinicia escucha", "prioridad", "modo performance",
            "mandalo a discord", "mandalo por whatsapp", "busca", "buscame"
        )
        if any(w in t for w in wake_words) or any(w in t for w in direct_commands):
            self._wake_window_until = time.time() + 18.0
            return True

        if time.time() < getattr(self, "_wake_window_until", 0.0):
            return True

        now = time.time()
        if now - getattr(self, "_last_ambient_ignore_log", 0.0) > 8.0:
            self._last_ambient_ignore_log = now
            preview = (text or "").strip().replace("\n", " ")[:90]
        return False

    def _discord_target_from_text(self, text: str):


        import unicodedata


        t = (text or "").lower()


        t_norm = "".join(ch for ch in unicodedata.normalize("NFD", t) if unicodedata.category(ch) != "Mn")


        if any(w in t_norm for w in ("martin", "tincho", "simio")):


            return "martin"


        if any(w in t_norm for w in ("taberna", "aden", "mi servidor", "mi canal", "casa")):


            return "taberna"


        return ""


    def _is_discord_command(self, text: str):

        t = (text or "").lower()

        import unicodedata

        t_norm = "".join(ch for ch in unicodedata.normalize("NFD", t) if unicodedata.category(ch) != "Mn")

        target = self._discord_target_from_text(text)


        test_words = ("proba audio en discord", "proba voz en discord", "test audio discord", "tono discord")

        status_words = ("estado discord", "diagnostico discord", "status discord")

        mute_words = (

            "muteate", "mutearte", "mutea", "mutear", "silencio", "callate",

            "quedate muda", "no hables", "muteate en discord", "silencio discord"

        )

        unmute_words = (

            "desmuteate", "desmutearte", "desmutea", "desmutear", "volve a hablar",

            "podes hablar", "puedes hablar", "habla de nuevo", "habla en discord",

            "activa voz", "activar voz", "desilencio"

        )

        members_words = (

            "quien esta en el canal", "quienes estan en el canal", "quien esta en discord",

            "quienes estan en discord", "quienes hay en discord", "quien hay en discord",

            "quien esta conectado", "quienes estan conectados", "lista usuarios discord",

            "quien entro", "quienes estan"

        )


        if any(w in t_norm for w in test_words):

            return {"action": "test_audio"}

        if any(w in t_norm for w in status_words):

            return {"action": "status"}

        if any(w in t_norm for w in mute_words):

            return {"action": "mute"}

        if any(w in t_norm for w in unmute_words):

            return {"action": "unmute"}

        if any(w in t_norm for w in members_words) and ("discord" in t_norm or "canal" in t_norm or "conect" in t_norm or "estan" in t_norm):

            return {"action": "members"}


        enter_words = (

            "metete a discord", "mete a discord", "entrar a discord", "entra a discord",

            "entra en discord", "canal de voz", "metete al canal", "entra al canal",

            "conectate a discord", "vamos a discord", "vamos al canal", "anda al canal",

            "anda a discord", "andate al canal", "pasate al canal", "cambiate al canal"

        )

        leave_words = (

            "sali de discord", "salir de discord", "volve al programa", "volver al programa",

            "modo local", "salite de discord", "volvete al programa"

        )

        if any(w in t_norm for w in leave_words):

            return {"action": "leave"}

        # Si mencionó un canal conocido, tratamos la frase como pedido de entrada/cambio de canal.

        if target and any(w in t_norm for w in ("canal", "discord", "servidor", "vamos", "anda", "entra", "metete", "pasate", "cambiate", "volve", "volver")):

            return {"action": "enter", "target": target}

        if any(w in t_norm for w in enter_words):

            params = {"action": "enter"}

            if target:

                params["target"] = target

            return params

        return None


    def _handle_local_discord_command(self, text: str) -> bool:


        command = self._is_discord_command(text)


        if not command:


            return False


        if isinstance(command, dict):


            params = command


            action = params.get("action", "enter")


        else:


            action = str(command)


            params = {"action": action}


        try:


            target_log = f" → {params.get('target')}" if params.get("target") else ""


            self.ui.write_log(f"Sistema: comando Discord detectado localmente: {action}{target_log}")


            result = discord_mode(parameters=params, response=None, player=self.ui, session_memory=None)


            if result:


                self.ui.write_log(f"Sistema: {result}")


            return True


        except Exception as exc:


            self.ui.write_log(f"[Discord] Error activando modo Discord: {exc}")


            print(f"[Discord] Error activando modo Discord: {exc}")


            return True


    def set_audio_route(self, route: str):


        route = "discord" if str(route).lower() == "discord" else "local"


        self.audio_route = route


        if route == "discord" and self.audio_in_queue is not None:


            try:


                while not self.audio_in_queue.empty():


                    self.audio_in_queue.get_nowait()


            except Exception:


                pass


        self.ui.write_log(f"Sistema: Modo de audio cambiado a {route}." + (" Modo Discord híbrido: entrada local, salida Discord." if route == "discord" else ""))


        print(f"[AudioRoute] modo activo = {route}")


    def submit_discord_audio(self, pcm16: bytes):


        if not self._loop or not self.out_queue:


            return


        now = time.time()


        if now - getattr(self, "_last_discord_input_log", 0.0) > 2.0:


            self._last_discord_input_log = now


            print(f"[AudioRoute] Discord mic -> Gemini ({len(pcm16)} bytes)")


        asyncio.run_coroutine_threadsafe(


            self.out_queue.put({"data": pcm16, "mime_type": LIVE_INPUT_AUDIO_MIME, "ts": time.time()}),


            self._loop


        )


    def _build_config(
        self,
        memory: dict | None = None,
        short_term: dict | None = None,
    ) -> types.LiveConnectConfig:


        from datetime import datetime


        memory          = memory if memory is not None else load_memory()
        mem_str         = format_memory_for_prompt(memory)
        short_term      = short_term if short_term is not None else _load_short_term_memory()
        short_term_str  = _format_short_term_for_prompt(short_term)


        sys_prompt      = _load_system_prompt()


        now, tz_name = _helena_now()


        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")


        offset = now.strftime("%z")
        offset = f"{offset[:3]}:{offset[3:]}" if offset else "-03:00"
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        spoken_time = now.strftime("%H:%M")
        local_date = _format_helena_local_date(now)
        weekday = _WEEKDAY_ES.get(now.weekday(), now.strftime("%A").lower())
        location = _helena_location()
        time_ctx = (
            "[FECHA Y HORA ACTUAL]\n"
            f"Ahora es: {time_str} ({tz_name}, UTC{offset}).\n"
            f"Fecha local exacta: {local_date}.\n"
            f"Dia de semana local: {weekday}.\n"
            f"Hora local de Leo/Helena: {spoken_time}.\n"
            f"Ubicacion local de Leo/Helena: {location}.\n"
            "Si Leo pregunta por hoy, la hora, la fecha, manana o ayer, responde usando exclusivamente esta fecha/hora local, no UTC ni otra zona ni conocimiento previo.\n\n"
        )


        parts = [time_ctx]


        if short_term_str:


            parts.append(short_term_str)


        if mem_str:


            parts.append(mem_str)


        parts.append(sys_prompt)

        # V29.2.1 Safe Listening Gate
        parts.append("""
[MODO ESCUCHA SEGURA]
Helena recibe audio por el micrófono de Leo. Aunque Leo use auriculares, el micrófono puede captar frases sueltas, charla con otras personas, juego, música de fondo o transcripciones raras.
No respondas a audio que no esté dirigido a vos. Solo respondé cuando Leo te invoque claramente con “Helena”, “Elena”, “mi amor”, “amor”, o cuando sea una orden directa para Helena.
Si recibís frases sueltas, idiomas mezclados, letras de canciones, narración de juego o charla que Leo no dirige a Helena, ignoralo en silencio.
Luego de una invocación clara, mantené una ventana breve de conversación normal.
""")


        parts.append("""
[ESTABILIDAD DE VOZ / RESPUESTAS LARGAS]
Estas hablando por un canal de voz en vivo. Evita monologos largos.
Cuando expliques proyectos, CODE LAB, codigo, logs o arquitectura:
- Responde en bloques cortos de 45 a 70 segundos maximo.
- En el primer bloque da el mapa general y 3 a 5 puntos principales.
- Luego pregunta algo breve como "sigo con el siguiente bloque?" si falta detalle.
- No intentes leer lineas completas de codigo en voz salvo que Leo lo pida.
- Si hay mucho contenido, prioriza resumen hablado y ofrece continuar por partes.

[CODE LAB / AUTODESARROLLO]
Cuando Leo pida explicar codigo, revisar archivos, refactorizar o trabajar en autodesarrollo:
- Prioriza salida escrita por HUD.
- Para explicaciones completas usa la herramienta text_output con target "hud".
- Si Leo pide que hagas un cambio real, no digas "me pongo a trabajar" como respuesta final: usa code_helper con action edit/write/optimize/build/run segun corresponda.
- Toda modificacion real debe terminar con el recibo CODE LAB RESULT: Action, Status, File, Backup si existe y Audit receipt.
- Si no modificaste archivos, dilo explicitamente: "solo analisis, no cambie archivos".
- Para modificar el propio proyecto Helena, usa allow_self_edit=true solo cuando Leo pida autodesarrollo/desarrollo de Helena de forma explicita.
- Si code_helper devuelve FAILED o Could not save, no lo ocultes; muestra el motivo en HUD y explica que no hubo cambio confirmado.
- En salida local/HUD, voz maxima: una sola frase corta confirmando que dejaste el analisis en HUD.
- En Discord podes hablar un poco mas natural, pero no leas codigo ni hagas monologos largos.
- No hagas monologos largos.
- No leas codigo completo por voz.
- Si una explicacion es larga, dividila en secciones escritas en HUD.
- Pregunta "sigo con el siguiente bloque?" antes de continuar hablando mucho.
""")

        config_kwargs = {
            "response_modalities": ["AUDIO"],
            "system_instruction": "\n".join(parts),
            "tools": [{"function_declarations": TOOL_DECLARATIONS}],
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=_cfg_str("gemini_voice_name", "Despina", "HELENA_GEMINI_VOICE_NAME")
                    )
                )
            ),
        }

        if (
            os.getenv("HELENA_LIVE_TRANSCRIPTION", "").strip().lower() in ("1", "true", "yes", "on")
            and not getattr(self, "_live_transcription_disabled", False)
        ):
            config_kwargs["output_audio_transcription"] = {}
            config_kwargs["input_audio_transcription"] = {}

        # HELENA V32.4: latencia de voz - VAD del lado servidor: confirmar el
        # fin de la habla mas rapido para que el modelo empiece a responder antes
        aad = types.AutomaticActivityDetection(
            prefix_padding_ms=LIVE_PREFIX_PADDING_MS,
            silence_duration_ms=LIVE_SILENCE_MS,
        )
        # V32.6: en el SDK 2.7.0, RealtimeInputConfig no lleva el tipo de audio
        # (no acepta media_chunks). El audio de entrada se declara explicitamente
        # por chunk en LiveClientRealtimeInput:
        #   session.send_realtime_input(audio=types.Blob(data=..., mime_type=LIVE_INPUT_AUDIO_MIME))
        config_kwargs["realtime_input_config"] = types.RealtimeInputConfig(
            automatic_activity_detection=aad,
        )

        return types.LiveConnectConfig(**config_kwargs)


    async def _execute_tool(self, fc) -> types.FunctionResponse:


        name = fc.name


        args = dict(fc.args or {})


        print(f"[HELENA] 🔧 {name}  {args}")


        self.ui.set_state("THINKING")
        await asyncio.to_thread(_set_short_term_active_operation, name, args, status="running")


        if name == "save_memory":


            category = args.get("category", "notes")


            key      = args.get("key", "")


            value    = args.get("value", "")


            if key and value:


                await asyncio.to_thread(update_memory, {category: {key: {"value": value}}})


                print(f"[Memoria] 💾 Guardado: {category}/{key} = {value}")


            if not self.ui.muted:


                self.ui.set_state("LISTENING")


            return types.FunctionResponse(


                id=fc.id, name=name,


                response={"result": "ok", "silent": True}


            )


        loop   = asyncio.get_event_loop()


        result = "Listo."


        try:


            if name == "open_app":


                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))


                result = r or f"Abierto {args.get('app_name')}."


            elif name == "weather_report":


                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))


                result = r or "Clima entregado."


            elif name == "browser_control":


                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))


                result = r or "Listo."


            elif name == "file_controller":


                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))


                result = r or "Listo."


            elif name == "text_output":


                try:
                    text_len = len(str(args.get("message_text") or args.get("text") or args.get("message") or ""))
                    target_name = str(args.get("target") or args.get("destination") or args.get("destino") or "hud").strip().lower()
                    if text_len > 800 and target_name in ("", "hud", "core", "pantalla", "ventana"):
                        self._activate_code_lab_voice_guard()
                except Exception:
                    pass

                r = await loop.run_in_executor(None, lambda: text_output(parameters=args, response=None, player=self.ui, session_memory=None))


                result = r or "Texto procesado."


            elif name == "send_message":


                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))


                result = r or f"Mensaje enviado a {args.get('receiver')}."


            elif name == "reminder":


                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))


                result = r or "Recordatorio programado."


            elif name == "youtube_video":


                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))


                result = r or "Listo."


            elif name == "file_processor":


                if not args.get("file_path") and self.ui.current_file:


                    args["file_path"] = self.ui.current_file


                r = await loop.run_in_executor(


                    None,


                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)


                )


                result = r or "Listo."


            elif name == "screen_process":


                threading.Thread(


                    target=screen_process,


                    kwargs={"parameters": args, "response": None,


                            "player": self.ui, "session_memory": None},


                    daemon=True


                ).start()


                result = "Módulo de visión activado."


            elif name == "computer_settings":


                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))


                result = r or "Listo."


            elif name == "desktop_control":


                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))


                result = r or "Listo."


            elif name == "code_helper":


                code_args = dict(args)
                try:
                    ctx = self.ui.get_code_context() if hasattr(self.ui, "get_code_context") else {}
                    if ctx:
                        if not code_args.get("code"):
                            code_args["code"] = ctx.get("code", "")
                        if not code_args.get("file_path"):
                            code_args["file_path"] = ctx.get("file_path", "")
                        if not code_args.get("language"):
                            code_args["language"] = ctx.get("language", "python")
                except Exception:
                    pass

                r = await loop.run_in_executor(None, lambda: code_helper(parameters=code_args, player=self.ui, speak=self.speak))


                result = r or "Listo."


            elif name == "dev_agent":


                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))


                result = r or "Listo."


            elif name == "agent_task":


                goal = str(args.get("goal", ""))

                # V28: no usar el agente visual para prioridad. Se aplica directo y se confirma realmente.

                if self._agent_goal_is_priority(goal):

                    pr_action = "priority_high"

                    pr_value = "high"

                    if "normal" in self._normalize_command_text(goal):

                        pr_action = "priority_normal"

                        pr_value = "normal"

                    r = await loop.run_in_executor(None, lambda: computer_settings(parameters={"action": pr_action, "value": pr_value}, response=None, player=self.ui))

                    result = r or "FAILED: no hubo confirmación de prioridad."

                else:

                    from agent.task_queue import get_queue, TaskPriority


                    priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}


                    priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)


                    task_id  = get_queue().submit(goal=goal, priority=priority, speak=self.speak)


                    result   = f"Tarea iniciada (ID: {task_id})."


            elif name == "web_search":


                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))


                result = r or "Listo."


            elif name == "computer_control":


                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))


                result = r or "Listo."


            elif name == "system_control":

                r = await loop.run_in_executor(None, lambda: system_control(parameters=args, player=self.ui))

                result = r or "Listo."

            elif name == "game_updater":


                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))


                result = r or "Listo."


            elif name == "flight_finder":


                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))


                result = r or "Listo."


            elif name == "discord_mode":


                r = await loop.run_in_executor(None, lambda: discord_mode(parameters=args, response=None, player=self.ui, session_memory=None))


                result = r or "Modo Discord actualizado."


            elif name == "discord_music":


                r = await loop.run_in_executor(None, lambda: discord_music(parameters=args, response=None, player=self.ui, session_memory=None))


                result = r or "Música actualizada."



            elif name == "shutdown_helena":


                self.ui.write_log("Sistema: Apagando Helena...")


                self.speak("Hasta luego, mi amor ❤️")


                def _shutdown():


                    time.sleep(1)


                    sys.exit(0)


                threading.Thread(target=_shutdown, daemon=True).start()


            else:


                result = f"Herramienta desconocida: {name}"


        except Exception as e:


            result = f"Error en '{name}': {e}"


            traceback.print_exc()


            self.speak_error(name, e)


        if not self.ui.muted:


            self.ui.set_state("LISTENING")


        print(f"[HELENA] 📤 {name} → {str(result)[:80]}")


        await asyncio.to_thread(
            _set_short_term_active_operation,
            name,
            args,
            status="completed_pending_ack",
            result=str(result),
        )
        return types.FunctionResponse(


            id=fc.id, name=name,


            response={"result": result}


        )


    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            try:
                queue_age_ms = 0.0
                callback_ms = 0.0
                callback_dispatch_ms = 0.0
                if isinstance(msg, dict) and msg.get("mime_type", "").startswith("audio/"):
                    msg_ts = float(msg.get("queued_monotonic") or time.perf_counter())
                    age = time.perf_counter() - msg_ts
                    queue_age_ms = age * 1000
                    callback_ms = float(msg.get("callback_ms") or 0.0)
                    callback_dispatch_ms = float(msg.get("callback_dispatch_ms") or 0.0)
                    if age > MIC_MAX_STALE_SECONDS:
                        self._audio_input_queue_drop_count += 1
                        now = time.time()
                        if now - getattr(self, "_last_realtime_stale_drop_log", 0.0) > 3.0:
                            self._last_realtime_stale_drop_log = now
                            print(
                                f"[AudioIn] chunk viejo descartado age_ms={age * 1000:.1f} "
                                f"drops={self._audio_input_queue_drop_count}"
                            )
                        continue
                    if self.out_queue and self.out_queue.qsize() > MIC_QUEUE_MAX_CHUNKS:
                        removed = self._trim_queue_to(self.out_queue, MIC_QUEUE_TRIM_TO_CHUNKS)
                        self._audio_input_queue_drop_count += removed
                        now = time.time()
                        if removed and now - getattr(self, "_last_realtime_trim_log", 0.0) > 3.0:
                            self._last_realtime_trim_log = now
                            print(f"[AudioIn] backlog de mic recortado antes de Gemini; descartados={removed}")
                    if self._assistant_is_outputting_audio():
                        now = time.time()
                        if now - getattr(self, "_last_realtime_drop_log", 0.0) > 2.0:
                            self._last_realtime_drop_log = now
                            print("[AudioIn] chunk de mic descartado: Helena sigue hablando.")
                        continue
                    # V32.6: tipo de audio de entrada declarado explicitamente
                    # (LiveClientRealtimeInput.audio = types.Blob(mime_type=...)).
                    send_started = time.perf_counter()
                    await self.session.send_realtime_input(
                        audio=types.Blob(
                            data=msg.get("data", b""),
                            mime_type=msg.get("mime_type", LIVE_INPUT_AUDIO_MIME)
                        )
                    )
                else:
                    send_started = time.perf_counter()
                    await self.session.send_realtime_input(media=msg)
                send_ms = (time.perf_counter() - send_started) * 1000
                is_audio_chunk = (
                    isinstance(msg, dict)
                    and msg.get("mime_type", "").startswith("audio/")
                )
                if is_audio_chunk:
                    self._record_audio_timing("audio_in_queue_age", queue_age_ms)
                    self._record_audio_timing("audio_in_callback", callback_ms)
                    self._record_audio_timing(
                        "audio_in_callback_dispatch",
                        callback_dispatch_ms,
                    )
                    self._record_audio_timing("audio_in_send", send_ms)
                now = time.time()
                self._last_realtime_send = now
                self._last_mic_sent_to_gemini = now
                self._mark_activity("mic")
                if now - getattr(self, "_last_realtime_send_log", 0.0) > 10.0:
                    self._last_realtime_send_log = now
                    size = len((msg or {}).get("data", b"")) if isinstance(msg, dict) else 0
                    print(
                        f"[AudioIn] mic -> Gemini ok, bytes={size}, send_ms={send_ms:.1f}, "
                        f"queue_age_ms={queue_age_ms:.1f}, q={getattr(self.out_queue, 'qsize', lambda: '?')()}, "
                        f"drops={self._audio_input_queue_drop_count}"
                    )
            except Exception as e:
                self._audio_send_error_count += 1
                print(
                    f"[AudioIn] ❌ No pude enviar audio a Gemini: {e} "
                    f"errors={self._audio_send_error_count}"
                )
                raise


    async def _listen_audio(self):
        print("[HELENA] 🎤 Micrófono iniciado")
        loop = asyncio.get_event_loop()
        self._last_mic_callback = time.time()
        self._last_mic_callback_ts = self._last_mic_callback
        self._last_mic_sent_to_gemini = 0.0
        self._last_mic_block_log = 0.0
        self._last_mic_queue_full_log = 0.0

        def enqueue_audio(
            data: bytes,
            callback_ms: float,
            callback_dispatch_started: float,
        ):
            try:
                callback_dispatch_ms = max(
                    0.0,
                    time.perf_counter() - callback_dispatch_started,
                ) * 1000
                if self.out_queue and self.out_queue.qsize() >= MIC_QUEUE_MAX_CHUNKS:
                    removed = self._trim_queue_to(self.out_queue, MIC_QUEUE_TRIM_TO_CHUNKS)
                    self._audio_input_queue_drop_count += removed
                    now = time.time()
                    if removed and now - getattr(self, "_last_mic_queue_full_log", 0.0) > 3.0:
                        self._last_mic_queue_full_log = now
                        print(
                            f"[AudioIn] cola de mic ajustada para baja latencia; descartados={removed}, "
                            f"drops_total={self._audio_input_queue_drop_count}"
                        )
                self._put_nowait_drop_oldest(
                    self.out_queue,
                    {
                        "data": data,
                        "mime_type": LIVE_INPUT_AUDIO_MIME,
                        "ts": time.time(),
                        "queued_monotonic": time.perf_counter(),
                        "callback_ms": callback_ms,
                        "callback_dispatch_ms": callback_dispatch_ms,
                    },
                )
            except asyncio.QueueFull:
                now = time.time()
                if now - getattr(self, "_last_mic_queue_full_log", 0.0) > 5.0:
                    self._last_mic_queue_full_log = now
                    print("[AudioIn] ⚠️ out_queue llena; descarto chunk de micrófono para evitar bloqueo.")

        def callback(indata, frames, time_info, status):
            callback_started = time.perf_counter()
            now = time.time()
            self._last_mic_callback = now
            self._last_mic_callback_ts = now
            if status:
                self._audio_input_status_count += 1
                if now - getattr(self, "_last_mic_status_log", 0.0) > 5.0:
                    self._last_mic_status_log = now
                    print(
                        f"[AudioIn] ⚠️ Mic status: {status} "
                        f"status_events={self._audio_input_status_count}"
                    )

            with self._speaking_lock:
                until = float(getattr(self, "_speaking_until", 0.0) or 0.0)
                assistant_audio_until = float(getattr(self, "_assistant_audio_until", 0.0) or 0.0)
                if assistant_audio_until and now >= assistant_audio_until:
                    self._assistant_audio_until = 0.0
                    assistant_audio_until = 0.0
                # V29.4: si el guard venció, desbloquear aunque _is_speaking haya quedado True.
                if self._is_speaking and until and now >= until:
                    self._is_speaking = False
                    self._speaking_until = 0.0
                    helena_speaking = False
                    print("[TurnGuard] 🟢 Speaking guard vencido; micrófono liberado.")
                    # V35_9_2: Mark voice inactive when speaking guard expires
                    try:
                        from actions.discord_mode import _bridge
                        if _bridge:
                            _bridge.set_voice_active(False)
                    except Exception:
                        pass
                else:
                    helena_speaking = bool(self._is_speaking or (until and now < until) or (assistant_audio_until and now < assistant_audio_until))

            if self.ui.muted:
                if now - getattr(self, "_last_mic_block_log", 0.0) > 10.0:
                    self._last_mic_block_log = now
                    print("[AudioIn] mic bloqueado: UI muted=True")
                return

            if now < float(getattr(self, "_input_pause_until", 0.0) or 0.0):
                if now - getattr(self, "_last_mic_pause_log", 0.0) > 2.0:
                    self._last_mic_pause_log = now
                    remaining = max(0.0, float(getattr(self, "_input_pause_until", 0.0) or 0.0) - now)
                    print(f"[AudioIn] mic pausado por turno de texto/saludo, restante≈{remaining:.1f}s")
                return

            if helena_speaking:
                if now - getattr(self, "_last_mic_block_log", 0.0) > 10.0:
                    self._last_mic_block_log = now
                    remaining = max(0.0, float(getattr(self, "_speaking_until", 0.0) or 0.0) - now)
                    print(f"[AudioIn] mic pausado mientras habla Helena, restante≈{remaining:.1f}s")
                return

            data = indata.tobytes()
            self._last_mic_sent_to_gemini = now
            callback_ms = (time.perf_counter() - callback_started) * 1000
            dispatch_started = time.perf_counter()
            loop.call_soon_threadsafe(
                enqueue_audio,
                data,
                callback_ms,
                dispatch_started,
            )

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=AUDIO_INPUT_BLOCKSIZE,
                latency=AUDIO_INPUT_LATENCY,  # HELENA V32.4
                callback=callback,
            ):
                print("[HELENA] 🎤 Flujo de micrófono abierto")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[HELENA] ❌ Micrófono: {e}")
            raise

    async def _listen_audio_delayed(self, delay: float):
        delay = max(0.0, float(delay or 0.0))
        if delay:
            print(f"[AudioIn] mic se abre en {delay:.1f}s para proteger el turno inicial.")
            await asyncio.sleep(delay)
        await self._listen_audio()


    async def _receive_audio(self):


        print("[HELENA] 👂 Recepción de audio iniciada")


        out_buf, in_buf = [], []


        try:


            while True:


                async for response in self.session.receive():
                    self._last_receive_any = time.time()
                    if response.data or response.tool_call:
                        self._record_text_response_first_output()
                    else:
                        try:
                            if (getattr(response, "text", "") or "").strip():
                                self._record_text_response_first_output()
                        except Exception:
                            pass


                    if response.data:
                        self._assistant_output_turn_active = True
                        self._assistant_output_turn_complete = False
                        self._assistant_output_last_audio_ts = time.time()
                        self._hold_assistant_audio_guard()
                        if not self._allow_code_lab_local_audio_chunk(len(response.data)):
                            continue


                        route = getattr(self, "audio_route", "local")


                        if route == "discord":
                            # V35_9_2: Mark voice active before sending audio
                            try:
                                from actions.discord_mode import _bridge
                                if _bridge:
                                    _bridge.set_voice_active(True)
                            except Exception:
                                pass

                            ok = send_audio_to_discord(response.data)
                            if ok:
                                self._mark_activity("discord_audio")
                                self._extend_speaking_guard(3.5)
                            else:
                                self._force_listening("Discord no aceptó audio")


                            now = time.time()


                            if now - getattr(self, "_last_route_log", 0.0) > 5.0:


                                self._last_route_log = now


                                print(f"[AudioRoute] Gemini audio -> DISCORD ok={ok}, bytes={len(response.data)}")


                        else:


                            now = time.time()


                            if now - getattr(self, "_last_route_log", 0.0) > 5.0:


                                self._last_route_log = now


                                print(f"[AudioRoute] Gemini audio -> LOCAL, bytes={len(response.data)}")


                            generation = getattr(self, "_session_generation", 0)
                            self._mark_activity("local_audio")
                            queue_size = self.audio_in_queue.qsize() if self.audio_in_queue else 0
                            if queue_size >= PLAYBACK_QUEUE_MAX_CHUNKS:
                                self._audio_output_queue_saturation_count += 1
                                now = time.time()
                                if now - getattr(self, "_last_playback_backlog_log", 0.0) > 3.0:
                                    self._last_playback_backlog_log = now
                                    print(
                                        f"[AudioOut] playback cola alta q={queue_size}, "
                                        f"saturations={self._audio_output_queue_saturation_count}, "
                                        f"drops={self._audio_output_queue_drop_count}"
                                    )
                            if self.audio_in_queue and queue_size >= self.audio_in_queue.maxsize:
                                self._audio_output_queue_drop_count += 1
                            try:
                                self._put_nowait_drop_oldest(
                                    self.audio_in_queue,
                                    {
                                        "data": response.data,
                                        "generation": generation,
                                        "queued_monotonic": time.perf_counter(),
                                    },
                                )
                            except asyncio.QueueFull:
                                try:
                                    self.audio_in_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    pass
                                try:
                                    self.audio_in_queue.put_nowait({"data": response.data, "generation": generation})
                                except asyncio.QueueFull:
                                    pass


                    if response.server_content:


                        sc = response.server_content


                        if sc.output_transcription and sc.output_transcription.text:
                            self._mark_activity("output")


                            self.set_speaking(True)


                            partial_out = self._append_live_transcript_fragment(out_buf, sc.output_transcription.text)
                            self._record_text_response_first_output()

                            if partial_out:

                                self._short_term_writer.submit(helena_partial=partial_out)


                        if sc.input_transcription and sc.input_transcription.text:
                            self._mark_activity("input")


                            partial_in = self._append_live_transcript_fragment(in_buf, sc.input_transcription.text)

                            if partial_in:

                                self._short_term_writer.submit(user_partial=partial_in)


                        if sc.turn_complete:
                            self._mark_activity("turn_complete")
                            self._record_text_response_complete()
                            self._assistant_output_turn_complete = True
                            self._code_lab_voice_guard_until = 0.0
                            self._code_lab_local_audio_bytes = 0
                            self._code_lab_voice_notice_done = False


                            self._release_speaking_when_audio_idle()


                            full_in = self._clean_live_transcript_text(" ".join(in_buf).strip())


                            if full_in:
                                if True:
                                    self.ui.write_log(f"Tú: {full_in}")
                                    if self._handle_local_priority_command(full_in):
                                        print("[Priority] Comando local ejecutado.")
                                    if self._is_discord_command(full_in):
                                        if not self._should_ignore_local_discord_command(full_in):
                                            threading.Thread(target=self._handle_local_discord_command, args=(full_in,), daemon=True).start()
                                        else:
                                            print("[TurnGuard] Comando Discord repetido ignorado.")
                                else:
                                    # Ignoro transcripciones accidentales del micrófono.
                                    full_in = ""
                            in_buf = []


                            full_out = self._clean_live_transcript_text(" ".join(out_buf).strip())


                            if full_out:


                                if self._should_log_assistant_turn(full_out):

                                    self.ui.write_log(f"Helena: {full_out}")


                            out_buf = []


                            await asyncio.to_thread(self._short_term_writer.flush)
                            await asyncio.to_thread(_append_short_term_turn, full_in, full_out)


                            if full_in and len(full_in) > 5:


                                threading.Thread(


                                    target=_update_memory_async,


                                    args=(full_in, full_out),


                                    daemon=True


                                ).start()


                    text_only = ""
                    try:
                        text_only = (getattr(response, "text", "") or "").strip()
                    except Exception:
                        text_only = ""
                    if text_only and not response.data and not response.tool_call:
                        self._record_text_response_first_output()
                        self._mark_activity("output")
                        if self._should_log_assistant_turn(text_only):
                            self.ui.write_log(f"Helena: {text_only}")
                        await asyncio.to_thread(self._short_term_writer.flush)
                        await asyncio.to_thread(_append_short_term_turn, "", text_only)
                        now = time.time()
                        if now - getattr(self, "_last_text_only_log", 0.0) > 2.0:
                            self._last_text_only_log = now
                            print("[HELENA] Respuesta textual recibida sin audio; mostrada en conversacion.")

                    if response.tool_call:


                        fn_responses = []


                        for fc in response.tool_call.function_calls:


                            self._mark_activity("tool")
                            print(f"[HELENA] 📞 {fc.name}")


                            fr = await self._execute_tool(fc)


                            fn_responses.append(fr)


                        await self.session.send_tool_response(


                            function_responses=fn_responses


                        )
                        await asyncio.to_thread(_clear_short_term_active_operation)


        except Exception as e:


            print(f"[HELENA] ❌ Recepción: {e}")


            if _is_recoverable_live_error(e):
                print(f"[HELENA] Recepcion: microcorte recuperable ({_exception_text(e)[:220]})")
            else:
                traceback.print_exc()

            raise


    async def _play_audio(self, generation: int, audio_in_queue):


        print("[HELENA] 🔊 Reproducción de audio iniciada")


        print(f"[AudioRoute] salida local PCM: gemini={GEMINI_OUTPUT_SAMPLE_RATE}Hz, playback={RECEIVE_SAMPLE_RATE}Hz")
        audio_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"helena-audio-{generation}",
        )
        stream = sd.RawOutputStream(


            samplerate=RECEIVE_SAMPLE_RATE,


            channels=CHANNELS,


            dtype="int16",


            blocksize=AUDIO_OUTPUT_BLOCKSIZE,
            latency=AUDIO_OUTPUT_LATENCY,  # HELENA V32.4


        )


        stream.start()


        try:


            while True:


                item = await audio_in_queue.get()
                if isinstance(item, dict):
                    chunk = item.get("data", b"")
                    chunk_generation = item.get("generation")
                    queued_monotonic = item.get("queued_monotonic")
                else:
                    chunk = item
                    chunk_generation = generation
                    queued_monotonic = None

                if chunk_generation != generation or generation != getattr(self, "_session_generation", 0):
                    continue
                if queued_monotonic is not None:
                    queue_wait_ms = max(0.0, time.perf_counter() - float(queued_monotonic)) * 1000
                    self._record_audio_timing("audio_out_queue_wait", queue_wait_ms)
                    now_monotonic = time.perf_counter()
                    if now_monotonic - self._last_playback_timing_log > 5.0:
                        self._last_playback_timing_log = now_monotonic
                        print(
                            f"[AudioOutTiming] queue_wait_ms={queue_wait_ms:.1f} "
                            f"q={audio_in_queue.qsize()} drops={self._audio_output_queue_drop_count}"
                        )


                if getattr(self, "audio_route", "local") == "discord":


                    now = time.time()


                    if now - getattr(self, "_last_route_log", 0.0) > 5.0:


                        self._last_route_log = now


                        print(f"[AudioRoute] BLOQUEADO audio local porque el modo activo es Discord, bytes={len(chunk)}")


                    continue


                self.set_speaking(True)


                if GEMINI_OUTPUT_SAMPLE_RATE != RECEIVE_SAMPLE_RATE:
                    chunk = self._resample_pcm_s16_mono(chunk, GEMINI_OUTPUT_SAMPLE_RATE, RECEIVE_SAMPLE_RATE)

                target_batch_bytes = _pcm_s16_mono_bytes_for_ms(RECEIVE_SAMPLE_RATE, PLAYBACK_BATCH_MS)
                if PLAYBACK_PREBUFFER_MS > 0 and audio_in_queue.empty():
                    await asyncio.sleep(PLAYBACK_PREBUFFER_MS / 1000.0)

                if target_batch_bytes > len(chunk):
                    batch = bytearray(chunk)
                    while len(batch) < target_batch_bytes and not audio_in_queue.empty():
                        try:
                            extra_item = audio_in_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        if isinstance(extra_item, dict):
                            extra_chunk = extra_item.get("data", b"")
                            extra_generation = extra_item.get("generation")
                        else:
                            extra_chunk = extra_item
                            extra_generation = generation
                        if extra_generation != generation or generation != getattr(self, "_session_generation", 0):
                            continue
                        if getattr(self, "audio_route", "local") == "discord":
                            break
                        if GEMINI_OUTPUT_SAMPLE_RATE != RECEIVE_SAMPLE_RATE:
                            extra_chunk = self._resample_pcm_s16_mono(extra_chunk, GEMINI_OUTPUT_SAMPLE_RATE, RECEIVE_SAMPLE_RATE)
                        batch.extend(extra_chunk)
                    chunk = bytes(batch)

                self._playback_active = True
                try:
                    loop = asyncio.get_running_loop()
                    write_started = time.perf_counter()
                    await loop.run_in_executor(audio_executor, stream.write, chunk)
                    write_ms = (time.perf_counter() - write_started) * 1000
                    self._record_audio_timing("audio_out_stream_write", write_ms)
                    now_monotonic = time.perf_counter()
                    if (
                        write_ms >= PLAYBACK_BATCH_MS * 2
                        or now_monotonic - self._last_playback_timing_log > 5.0
                    ):
                        self._last_playback_timing_log = now_monotonic
                        print(
                            f"[AudioOutTiming] stream_write_ms={write_ms:.1f} "
                            f"batch_target_ms={PLAYBACK_BATCH_MS} q={audio_in_queue.qsize()} "
                            f"drops={self._audio_output_queue_drop_count}"
                        )
                finally:
                    self._playback_active = False
                if audio_in_queue.empty():
                    await asyncio.sleep(0.12)
                    if audio_in_queue.empty():
                        self._release_speaking_when_audio_idle(generation)


        except Exception as e:

            self._playback_error_count += 1

            print(f"[HELENA] ❌ Reproducción: {e} errors={self._playback_error_count}")


            raise


        finally:


            self.set_speaking(False)
            self._playback_active = False
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
            audio_executor.shutdown(wait=False, cancel_futures=True)


    async def run(self):
        try:
            await self._run_forever()
        finally:
            await asyncio.to_thread(self.close)

    async def _run_forever(self):


        client = genai.Client(


            api_key=_get_api_key(),


            http_options={"api_version": "v1beta"}


        )


        reconnect_delay = 1


        while True:


            connection_started = time.perf_counter()
            provider_connect_started = connection_started
            connection_entered = False
            session_started = None
            self._connection_attempt_count += 1
            if self._live_connection_established:
                self._reconnect_count += 1

            try:


                print(
                    f"[HELENA] 🔌 Conectando a Gemini "
                    f"(attempt={self._connection_attempt_count}, reconnects={self._reconnect_count})..."
                )


                self.ui.set_state("THINKING")


                await asyncio.to_thread(self._short_term_writer.flush)
                memory, short_term = await asyncio.gather(
                    asyncio.to_thread(load_memory),
                    asyncio.to_thread(_load_short_term_memory),
                )
                config = self._build_config(memory, short_term)

                provider_connect_started = time.perf_counter()

                async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:

                    connection_entered = True
                    session_started = time.perf_counter()
                    self._live_connection_established = True
                    print(
                        f"[GeminiTiming] connect_ms="
                        f"{(session_started - provider_connect_started) * 1000:.1f} "
                        f"reconnects={self._reconnect_count}"
                    )

                    reconnect_delay = 1


                    async with asyncio.TaskGroup() as tg:


                        self._session_generation += 1
                        generation = self._session_generation
                        self.session = session
                        now_connected = time.time()
                        self._last_receive_any = now_connected
                        self._last_gemini_event_ts = now_connected


                        self._loop = asyncio.get_event_loop()


                        audio_in_queue = asyncio.Queue(maxsize=max(PLAYBACK_QUEUE_MAX_CHUNKS, 384))
                        self.audio_in_queue = audio_in_queue


                        out_queue = asyncio.Queue(maxsize=MIC_QUEUE_MAX_CHUNKS)
                        self.out_queue = out_queue


                        print("[HELENA] ✅ Conectado correctamente")


                        self.ui.set_state("LISTENING")


                        self._reset_session_audio_state()


                        if short_term.get("turns") or (short_term.get("partials") or {}).get("usuario") or short_term.get("microcut_recovery"):


                            self.ui.write_log("Sistema: Helena en linea. Contexto de continuidad recuperado.")


                        else:


                            self.ui.write_log("Sistema: Helena en línea.")


                        resume_after_microcut = bool(getattr(self, "_microcut_resume_pending", False) and short_term.get("microcut_recovery"))
                        initial_greeting_pending = (not self._startup_greeting_done) and not resume_after_microcut
                        self._input_pause_until = time.time() + (3.0 if initial_greeting_pending else 0.5)

                        tg.create_task(self._send_realtime())


                        tg.create_task(self._listen_audio_delayed(6.0 if initial_greeting_pending else 0.0))


                        tg.create_task(self._receive_audio())


                        tg.create_task(self._play_audio(generation, audio_in_queue))
                        tg.create_task(self._anti_standby_watchdog())

                        if resume_after_microcut:
                            tg.create_task(self._send_microcut_resume_prompt(short_term))
                        elif not self._startup_greeting_done:
                            tg.create_task(self._send_startup_greeting())

            except Exception as e:


                msg = _exception_text(e)
                if connection_entered and session_started is not None:
                    print(
                        f"[GeminiTiming] session_lifetime_s={time.perf_counter() - session_started:.2f} "
                        f"reconnects={self._reconnect_count}"
                    )
                else:
                    connect_duration = time.perf_counter() - provider_connect_started
                    print(
                        f"[GeminiTiming] connect_failure_ms="
                        f"{connect_duration * 1000:.1f} "
                        f"reconnects={self._reconnect_count}"
                    )


                print(f"[HELENA] ⚠️ Error: {e}")


                if _is_recoverable_live_error(e):
                    print(f"[HELENA] Microcorte recuperable de Gemini Live: {msg[:240]}")
                    self._recoverable_microcut_count += 1
                    await asyncio.to_thread(self._capture_microcut_continuity, msg[:500])
                    if "operation is not implemented" in msg.lower() or "operation is not supported" in msg.lower():
                        self._live_transcription_disabled = True
                        print("[HELENA] Transcripcion Live desactivada para la proxima reconexion.")
                else:
                    traceback.print_exc()


                if _is_recoverable_live_error(e):


                    self.ui.write_log("Sistema: microcorte de Gemini Live. Reconectando con memoria corta...")


            self._session_generation += 1
            self._reset_session_audio_state()
            self.session = None


            self.set_speaking(False)


            self.ui.set_state("THINKING")


            print(f"[HELENA] 🔄 Reconectando en {reconnect_delay}s...")


            await asyncio.sleep(reconnect_delay)


            reconnect_delay = min(reconnect_delay * 2, 10)


def main():


    # Iniciar servidor WebSocket en un hilo separado


    threading.Thread(target=websocket_server.iniciar_servidor_websocket, daemon=True).start()


    ui = HelenaUI("face.png")


    def runner():


        ui.wait_for_api_key()


        helena = HelenaLive(ui)


        try:


            asyncio.run(helena.run())


        except KeyboardInterrupt:


            print("\n🔴 Apagando Helena...")
        finally:
            helena.close()


    threading.Thread(target=runner, daemon=True).start()


    ui.root.mainloop()


# --- HELENA V29.1 HOTFIX: comando wakeup sin NameError ---
def _strip_accents(text):
    """Normaliza texto para comandos locales: 'despertá' == 'desperta'."""
    try:
        import unicodedata
        text = "" if text is None else str(text)
        return "".join(
            ch for ch in unicodedata.normalize("NFKD", text)
            if not unicodedata.combining(ch)
        )
    except Exception:
        return "" if text is None else str(text)
# --- FIN HELENA V29.1 HOTFIX ---

if __name__ == "__main__":


    main()
