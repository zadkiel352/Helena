from __future__ import annotations

from collections import deque


class AudioTimingMetrics:
    """Keep bounded rolling samples for audio-path latency diagnostics."""

    def __init__(self, max_samples: int = 256) -> None:
        self._max_samples = max(1, max_samples)
        self._samples: dict[str, deque[float]] = {}
        self._total_samples: dict[str, int] = {}

    def record(self, name: str, elapsed_ms: float) -> None:
        samples = self._samples.setdefault(name, deque(maxlen=self._max_samples))
        samples.append(max(0.0, float(elapsed_ms)))
        self._total_samples[name] = self._total_samples.get(name, 0) + 1

    def summary(self, name: str) -> dict[str, float | int] | None:
        samples = self._samples.get(name)
        if not samples:
            return None
        ordered = sorted(samples)
        p95_index = max(0, int((len(ordered) - 1) * 0.95 + 0.5))
        return {
            "samples": self._total_samples[name],
            "window": len(ordered),
            "p50_ms": ordered[(len(ordered) - 1) // 2],
            "p95_ms": ordered[p95_index],
            "max_ms": ordered[-1],
        }
