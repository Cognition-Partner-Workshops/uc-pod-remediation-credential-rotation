"""Simple in-process metrics collector for observability."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List


@dataclass
class MetricPoint:
    name: str
    value: float
    timestamp: float
    labels: Dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """Thread-safe metrics collector for counters and histograms."""

    def __init__(self) -> None:
        self._counters: Dict[str, float] = defaultdict(float)
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._lock = Lock()

    def increment(self, name: str, value: float = 1.0, labels: Dict[str, str] | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value

    def observe(self, name: str, value: float, labels: Dict[str, str] | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._histograms[key].append(value)

    def get_counter(self, name: str, labels: Dict[str, str] | None = None) -> float:
        key = self._key(name, labels)
        with self._lock:
            return self._counters.get(key, 0.0)

    def get_histogram_stats(self, name: str, labels: Dict[str, str] | None = None) -> Dict[str, float]:
        key = self._key(name, labels)
        with self._lock:
            values = self._histograms.get(key, [])
        if not values:
            return {"count": 0, "min": 0, "max": 0, "avg": 0}
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
        }

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "histograms": {
                    k: {"count": len(v), "avg": sum(v) / len(v) if v else 0}
                    for k, v in self._histograms.items()
                },
            }

    @staticmethod
    def _key(name: str, labels: Dict[str, str] | None) -> str:
        if not labels:
            return name
        sorted_labels = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{sorted_labels}}}"


# Global singleton
metrics = MetricsCollector()
