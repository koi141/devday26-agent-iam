from __future__ import annotations

from iam_agent.observability.telemetry_bridge import TelemetryBridge


class CaptureLangfuseClient:
    def __init__(self) -> None:
        self.payload = None

    def send_trace(self, payload):
        self.payload = payload
        return "sent", "ok"


def test_trace_contract_required_fields() -> None:
    capture = CaptureLangfuseClient()
    bridge = TelemetryBridge(langfuse_client=capture)  # type: ignore[arg-type]
    trace = bridge.start_trace(turn_id="t1", request_type="single_tool_passthrough", user_prompt_summary="ユーザー一覧")

    s1 = bridge.start_stage(trace, stage="action_planning", attempt=1)
    bridge.end_stage(trace, span_id=s1, status="success")
    s2 = bridge.start_stage(trace, stage="tool_execution", attempt=1)
    bridge.end_stage(trace, span_id=s2, status="success")

    bridge.finish_trace(trace, status="success", quality_score={"semantic_alignment": 1.0}, compatibility_status="single_tool_passthrough")

    payload = capture.payload
    assert payload is not None
    for key in ("trace_id", "turn_id", "request_id", "request_type", "started_at", "status"):
        assert key in payload
    assert any(span["stage"] == "action_planning" for span in payload["spans"])
    assert any(span["stage"] == "tool_execution" for span in payload["spans"])
