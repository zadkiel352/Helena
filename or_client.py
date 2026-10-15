# or_client.py - Cliente de OpenRouter compatible con HELENA

from __future__ import annotations

import json
import logging
import os
import re
import time
import warnings
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except Exception:  # python-dotenv es opcional si api_keys.json existe
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
ENV_PATH = BASE_DIR / ".env"

if load_dotenv:
    load_dotenv(ENV_PATH)

warnings.filterwarnings("ignore")
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)

_last_log_time = 0
LOG_COOLDOWN = 120
_OPENROUTER_DISABLED_UNTIL = 0.0
_OPENROUTER_FAILURES = 0
_OPENROUTER_DISABLE_SECONDS = 600
_logger = logging.getLogger(__name__)


def _load_openrouter_key_from_config() -> str | None:
    """Lee la clave desde config/api_keys.json o, si no existe, desde .env."""
    try:
        cfg = BASE_DIR / "config" / "api_keys.json"
        if cfg.exists():
            data = json.loads(cfg.read_text(encoding="utf-8"))
            key = (data.get("openrouter_api_key") or "").strip()
            if key:
                return key
    except Exception:
        pass
    return os.getenv("OPENROUTER_API_KEY")


def _load_openrouter_key() -> str:
    """Carga la clave de OpenRouter desde variables de entorno o config/api_keys.json."""
    env_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_KEY")
    if env_key:
        return env_key.strip()

    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return (data.get("openrouter_api_key") or data.get("OPENROUTER_API_KEY") or "").strip()
    except Exception as exc:
        print(f"[OpenRouter] ⚠️ No se pudo leer config/api_keys.json: {exc}")

    return ""


class OpenRouterClient:
    def __init__(self, api_key: str | None = None, base_url: str = "https://openrouter.ai/api/v1"):
        self.api_key = (api_key or _load_openrouter_key()).strip()
        self.base_url = base_url.rstrip("/")

        print("[OpenRouter] Clave API cargada:", bool(self.api_key))

        self._models = [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nousresearch/hermes-3-llama-3.1-405b:free",
            "minimax/minimax-m2.5:free",
        ]

    def reload_key(self) -> None:
        self.api_key = _load_openrouter_key()

    def _log_rate_limit(self) -> None:
        global _last_log_time
        now = time.time()
        if now - _last_log_time > LOG_COOLDOWN:
            _last_log_time = now
            print("[OpenRouter] ⚠️ Límite de uso alcanzado, probando otro modelo...")

    def _make_request(self, prompt, system=None, max_tokens=500, temperature=0.2):
        # V28.4 circuit breaker: OpenRouter es auxiliar, no debe trabar a Helena.
        global _OPENROUTER_DISABLED_UNTIL, _OPENROUTER_FAILURES
        now = time.time()
        if now < _OPENROUTER_DISABLED_UNTIL:
            remaining = int(_OPENROUTER_DISABLED_UNTIL - now)
            raise RuntimeError(f"OpenRouter pausado temporalmente ({remaining}s restantes).")
        if not self.api_key:
            self.reload_key()
        if not self.api_key:
            raise RuntimeError(
                "No se encontró la clave de OpenRouter. Configurala en la UI o en config/api_keys.json."
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        request_started = time.perf_counter()
        last_error = None
        attempts = 0
        for model in self._models:
            attempts += 1
            attempt_started = time.perf_counter()
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=45,
                )

                if response.status_code == 200:
                    _OPENROUTER_FAILURES = 0
                    elapsed_ms = (time.perf_counter() - attempt_started) * 1000
                    total_ms = (time.perf_counter() - request_started) * 1000
                    _logger.info(
                        "OpenRouter request succeeded model=%s attempt=%d attempt_ms=%.1f total_ms=%.1f",
                        model, attempts, elapsed_ms, total_ms,
                    )
                    return response.json()
                if response.status_code == 429:
                    elapsed_ms = (time.perf_counter() - attempt_started) * 1000
                    _logger.warning(
                        "OpenRouter model fallback model=%s attempt=%d status=429 attempt_ms=%.1f",
                        model, attempts, elapsed_ms,
                    )
                    self._log_rate_limit()
                    continue

                last_error = f"{response.status_code}: {response.text[:500]}"
                elapsed_ms = (time.perf_counter() - attempt_started) * 1000
                _logger.warning(
                    "OpenRouter model fallback model=%s attempt=%d status=%d attempt_ms=%.1f",
                    model, attempts, response.status_code, elapsed_ms,
                )
            except Exception as exc:
                last_error = str(exc)
                elapsed_ms = (time.perf_counter() - attempt_started) * 1000
                _logger.warning(
                    "OpenRouter model fallback model=%s attempt=%d error_type=%s attempt_ms=%.1f",
                    model, attempts, type(exc).__name__, elapsed_ms,
                )

        _OPENROUTER_FAILURES += 1
        if _OPENROUTER_FAILURES >= 1:
            _OPENROUTER_DISABLED_UNTIL = time.time() + _OPENROUTER_DISABLE_SECONDS
        _logger.error(
            "OpenRouter request failed attempts=%d total_ms=%.1f",
            attempts, (time.perf_counter() - request_started) * 1000,
        )
        raise RuntimeError(last_error or "OpenRouter no devolvió respuesta válida.")

    def chat(self, prompt, system=None, max_tokens=500, temperature=0.2) -> str:
        result = self._make_request(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            return result["choices"][0]["message"]["content"] or ""
        except Exception:
            return ""

    def chat_json(self, prompt, system=None, max_tokens=500, temperature=0.1):
        try:
            content = self.chat(
                prompt=prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            array_match = re.search(r"\[.*\]", content, re.DOTALL)
            if array_match:
                return json.loads(array_match.group())
            object_match = re.search(r"\{.*\}", content, re.DOTALL)
            if object_match:
                return json.loads(object_match.group())
            return {"action": "unknown", "value": None}
        except Exception:
            return {"action": "unknown", "value": None}


client = OpenRouterClient()
