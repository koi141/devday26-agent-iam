from __future__ import annotations

from iam_agent.observability.snapshot_store import SnapshotStore


def test_snapshot_contract_required_fields() -> None:
    store = SnapshotStore()
    store.add_metric(scope="single_tool_passthrough", status="success", latency_ms=120, retry_count=0)
    store.add_metric(scope="single_tool_passthrough", status="error", latency_ms=220, retry_count=1, error_class="execution_error")

    snapshot = store.build_snapshot(scope="single_tool_passthrough", window_start="2026-04-01", window_end="2026-04-30")
    for key in (
        "snapshot_id",
        "window_start",
        "window_end",
        "scope",
        "success_rate",
        "p95_latency_ms",
        "retry_rate",
        "error_breakdown",
    ):
        assert key in snapshot
