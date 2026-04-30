from __future__ import annotations

from iam_agent.infra.logging.redaction import redact_for_telemetry
from iam_agent.observability.telemetry_bridge import TelemetryBridge
from iam_agent.observability.trace_context import TraceContext


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.payload = None

    def send_trace(self, payload):
        self.payload = payload
        return "sent", "ok"


def test_redact_for_telemetry_masks_sensitive_fields() -> None:
    payload = {
        "client_secret": "SECRET",
        "nested": {"access_token": "TOKEN", "name": "ok"},
        "plain": "value",
    }
    redacted, masked = redact_for_telemetry(payload)

    assert redacted["client_secret"] == "***REDACTED***"
    assert redacted["nested"]["access_token"] == "***REDACTED***"
    assert redacted["plain"] == "value"
    assert "client_secret" in masked


def test_trace_context_span_lifecycle() -> None:
    trace = TraceContext.new(turn_id="turn1", request_type="single_tool_passthrough", user_prompt_summary="一覧")
    span_id = trace.start_span("action_planning", attempt=1)
    trace.end_span(span_id, status="success")

    assert trace.spans
    assert trace.spans[0].stage == "action_planning"
    assert trace.spans[0].status == "success"
    assert trace.spans[0].latency_ms >= 0


def test_telemetry_bridge_finish_trace_records_delivery() -> None:
    fake = FakeLangfuseClient()
    bridge = TelemetryBridge(langfuse_client=fake)  # type: ignore[arg-type]
    trace = bridge.start_trace(turn_id="turn1", request_type="single_tool_passthrough", user_prompt_summary="一覧")
    span = bridge.start_stage(trace, stage="tool_execution", attempt=1)
    bridge.end_stage(trace, span_id=span, status="success")

    delivery = bridge.finish_trace(trace, status="success", quality_score={"semantic_alignment": 1.0}, compatibility_status="single_tool_passthrough")

    assert delivery.status == "sent"
    assert fake.payload is not None
    assert fake.payload["trace_id"] == delivery.trace_id
    assert fake.payload["spans"][0]["stage"] == "tool_execution"
