from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class LatencySnapshot:
    samples: int
    p50_ms: float
    p95_ms: float
    max_ms: float


class LatencyWindow:
    """Small rolling window for the catalogue list endpoint.

    This is deliberately in-process and bounded: #58 owns gateway-wide HTTP
    metrics, while the catalog only needs to answer "is the list query healthy?"
    from its own admin stats endpoint without adding a Prometheus dependency.
    """

    def __init__(self, size: int = 512) -> None:
        self._samples: deque[float] = deque(maxlen=max(16, size))

    def observe(self, milliseconds: float) -> None:
        self._samples.append(max(0.0, float(milliseconds)))

    @staticmethod
    def _percentile(ordered: list[float], fraction: float) -> float:
        if not ordered:
            return 0.0
        index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
        return ordered[index]

    def snapshot(self) -> LatencySnapshot:
        values = sorted(self._samples)
        return LatencySnapshot(
            samples=len(values),
            p50_ms=round(self._percentile(values, 0.50), 2),
            p95_ms=round(self._percentile(values, 0.95), 2),
            max_ms=round(values[-1], 2) if values else 0.0,
        )
