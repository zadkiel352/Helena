# -*- coding: utf-8 -*-
"""Test V32.4: verifica que el servidor Gemini Live acepta el nuevo
realtime_input_config (VAD) con los valores de latencia de main.py.

Uso:  python tools\\test_vad_latency_config.py
Salida: 'OK SERVIDOR' si la conexion Live se establece con el config.
"""
import asyncio
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"


def _load_key() -> str:
    data = json.loads((BASE_DIR / "config" / "api_keys.json").read_text(encoding="utf-8-sig"))
    return data.get("gemini_api_key", "")


def _cfg_int(name, default):
    try:
        data = json.loads((BASE_DIR / "config" / "api_keys.json").read_text(encoding="utf-8-sig"))
        return int(data.get(name, default))
    except Exception:
        return default


async def main() -> int:
    from google import genai
    from google.genai import types

    api_key = _load_key()
    if not api_key:
        print("FALTA: gemini_api_key en config/api_keys.json")
        return 2

    silence_ms = max(120, _cfg_int("live_silence_duration_ms", 350))
    prefix_ms = max(60, _cfg_int("live_prefix_padding_ms", 120))
    print(f"[test] silence_duration_ms={silence_ms} prefix_padding_ms={prefix_ms}")

    aad = types.AutomaticActivityDetection(
        prefix_padding_ms=prefix_ms,
        silence_duration_ms=silence_ms,
    )
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction="Test de config de latencia V32.4.",
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=aad,
        ),
    )

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            print("OK SERVIDOR: sesion Live conectada con realtime_input_config activo")
            await asyncio.sleep(0.3)
            _ = getattr(session, "session_id", None)
        return 0
    except Exception as exc:
        print(f"FALLO SERVIDOR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
