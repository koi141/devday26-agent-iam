from __future__ import annotations

from iam_agent.observability.telemetry_bridge import TelemetryBridge


class CaptureLangfuseClient:
    def __init__(self) -> None:
        self.payload = None

    def send_trace(self, payload):  # noqa: ANN001
        self.payload = payload
        return "sent", "ok"


def test_a2a_observability_payload_contains_required_metadata() -> None:
    capture = CaptureLangfuseClient()
    bridge = TelemetryBridge(langfuse_client=capture)  # type: ignore[arg-type]
    trace = bridge.start_trace(turn_id="t1", request_type="a2a_execute", user_prompt_summary="A2A request")
    span_id = bridge.start_stage(trace, stage="tool_execution", attempt=1)
    bridge.end_stage(trace, span_id=span_id, status="success")

    bridge.finish_trace(
        trace,
        status="partial_success",
        compatibility_status="additive_layer",
        correlation_id="corr-1",
        peer_agent="peer-1",
        delegation_outcome="delegated_success",
    )

    payload = capture.payload
    assert payload is not None
    for key in ("execution_outcome", "correlation_id", "peer_agent", "delegation_outcome"):
        assert key in payload
    assert payload["execution_outcome"] == "partial_success"
