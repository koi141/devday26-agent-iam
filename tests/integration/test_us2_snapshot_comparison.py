from __future__ import annotations

from iam_agent.observability.snapshot_store import SnapshotStore


def test_us2_snapshot_comparison_metrics() -> None:
    store = SnapshotStore()
    for _ in range(3):
        store.add_metric(scope="permission_investigation", status="success", latency_ms=120, retry_count=0)
    store.add_metric(scope="permission_investigation", status="error", latency_ms=350, retry_count=1, error_class="execution_error")

    snapshot = store.build_snapshot(scope="permission_investigation", window_start="2026-04-01", window_end="2026-04-25")

    assert snapshot["scope"] == "permission_investigation"
    assert snapshot["success_rate"] == 0.75
    assert snapshot["retry_rate"] == 0.25
    assert snapshot["p95_latency_ms"] >= 120
    assert "execution_error" in snapshot["error_breakdown"]
