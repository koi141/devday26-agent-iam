from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from iam_agent.infra.logging.redaction import redact_for_telemetry
from iam_agent.observability.langfuse_client import LangfuseClient
from iam_agent.observability.trace_context import TraceContext


@dataclass(slots=True)
class TelemetryDeliveryResult:
    trace_id: str
    status: str
    reason: str


class TelemetryBridge:
    def __init__(self, *, langfuse_client: LangfuseClient) -> None:
        self.langfuse_client = langfuse_client

    def start_trace(self, *, turn_id: str, request_type: str, user_prompt_summary: str) -> TraceContext:
        return TraceContext.new(turn_id=turn_id, request_type=request_type, user_prompt_summary=user_prompt_summary)

    def start_stage(self, trace: TraceContext, *, stage: str, attempt: int = 1) -> str:
        return trace.start_span(stage=stage, attempt=attempt)

    def end_stage(self, trace: TraceContext, *, span_id: str, status: str, error_class: str = "") -> None:
        trace.end_span(span_id, status=status, error_class=error_class)

    def finish_trace(
        self,
        trace: TraceContext,
        *,
        status: str,
        quality_score: dict[str, Any] | None = None,
        compatibility_status: str = "",
        correlation_id: str = "",
        peer_agent: str = "",
        delegation_outcome: str = "",
    ) -> TelemetryDeliveryResult:
        trace.finalize(status=status)
        execution_outcome = "failed"
        if status == "success":
            execution_outcome = "success"
        elif status == "partial_success":
            execution_outcome = "partial_success"
        trace_payload = {
            "trace_id": trace.trace_id,
            "turn_id": trace.turn_id,
            "request_id": trace.request_id,
            "request_type": trace.request_type,
            "user_prompt_summary": trace.user_prompt_summary,
            "status": trace.status,
            "started_at": trace.started_at.isoformat(),
            "finished_at": trace.finished_at.isoformat() if trace.finished_at else "",
            "spans": [asdict(item) for item in trace.spans],
            "tool_observations": [asdict(item) for item in trace.tool_observations],
            "prompt_observations": [asdict(item) for item in trace.prompt_observations],
            "notices": trace.notices,
            "quality_score": quality_score or {},
            "compatibility_status": compatibility_status,
            "execution_outcome": execution_outcome,
            "correlation_id": correlation_id,
            "peer_agent": peer_agent,
            "delegation_outcome": delegation_outcome,
        }
        redacted_payload, masked_fields = redact_for_telemetry(trace_payload)
        redacted_payload["masked_fields"] = masked_fields
        delivery_status, reason = self.langfuse_client.send_trace(redacted_payload)
        return TelemetryDeliveryResult(trace_id=trace.trace_id, status=delivery_status, reason=reason)
