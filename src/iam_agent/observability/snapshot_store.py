from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class SnapshotMetric:
    status: str
    latency_ms: int
    retry_count: int
    error_class: str


class SnapshotStore:
    """In-memory snapshot store for comparison API.

    OKE deployment may replace this with persistent backend in future phases.
    """

    def __init__(self) -> None:
        self._metrics: dict[str, list[SnapshotMetric]] = defaultdict(list)

    def add_metric(self, *, scope: str, status: str, latency_ms: int, retry_count: int, error_class: str = "") -> None:
        self._metrics[scope].append(
            SnapshotMetric(
                status=status,
                latency_ms=max(latency_ms, 0),
                retry_count=max(retry_count, 0),
                error_class=error_class,
            )
        )

    def build_snapshot(self, *, scope: str, window_start: str = "", window_end: str = "") -> dict[str, Any]:
        metrics = self._metrics.get(scope, [])
        total = len(metrics)
        if total == 0:
            return {
                "snapshot_id": f"snapshot-{scope}-empty",
                "window_start": window_start,
                "window_end": window_end,
                "scope": scope,
                "success_rate": 0.0,
                "p95_latency_ms": 0,
                "retry_rate": 0.0,
                "error_breakdown": {},
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        success = sum(1 for item in metrics if item.status == "success")
        retries = sum(1 for item in metrics if item.retry_count > 0)
        latencies = sorted(item.latency_ms for item in metrics)
        p95_idx = max(int(len(latencies) * 0.95) - 1, 0)
        error_breakdown: dict[str, int] = defaultdict(int)
        for item in metrics:
            if item.status == "error":
                key = item.error_class or "execution_error"
                error_breakdown[key] += 1

        return {
            "snapshot_id": f"snapshot-{scope}-{total}",
            "window_start": window_start,
            "window_end": window_end,
            "scope": scope,
            "success_rate": success / total,
            "p95_latency_ms": latencies[p95_idx],
            "retry_rate": retries / total,
            "error_breakdown": dict(error_breakdown),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
