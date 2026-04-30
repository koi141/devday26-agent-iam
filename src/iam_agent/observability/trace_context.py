from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class SpanRecord:
    span_id: str
    stage: str
    attempt: int
    started_at: datetime
    finished_at: datetime | None = None
    status: str = "in_progress"
    error_class: str = ""
    latency_ms: int = 0


@dataclass(slots=True)
class ToolObservation:
    tool_name: str
    auth_route: str
    input_summary: dict[str, Any]
    result_status: str
    duration_ms: int
    oci_request_id: str = ""


@dataclass(slots=True)
class PromptObservation:
    operation: str
    model_name: str
    input_summary: str
    output_summary: str
    duration_ms: int
    token_usage: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TraceContext:
    trace_id: str
    turn_id: str
    request_id: str
    request_type: str
    user_prompt_summary: str
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    status: str = "in_progress"
    spans: list[SpanRecord] = field(default_factory=list)
    tool_observations: list[ToolObservation] = field(default_factory=list)
    prompt_observations: list[PromptObservation] = field(default_factory=list)
    notices: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def new(turn_id: str, request_type: str, user_prompt_summary: str) -> "TraceContext":
        request_id = f"req-{uuid.uuid4()}"
        trace_id = f"trace-{uuid.uuid4()}"
        return TraceContext(
            trace_id=trace_id,
            turn_id=turn_id,
            request_id=request_id,
            request_type=request_type,
            user_prompt_summary=user_prompt_summary,
        )

    def start_span(self, stage: str, *, attempt: int = 1) -> str:
        span_id = f"span-{uuid.uuid4()}"
        self.spans.append(
            SpanRecord(
                span_id=span_id,
                stage=stage,
                attempt=attempt,
                started_at=utc_now(),
            )
        )
        return span_id

    def end_span(self, span_id: str, *, status: str, error_class: str = "") -> None:
        for span in self.spans:
            if span.span_id != span_id:
                continue
            finished = utc_now()
            span.finished_at = finished
            span.status = status
            span.error_class = error_class
            span.latency_ms = max(int((finished - span.started_at).total_seconds() * 1000), 0)
            return

    def add_tool_observation(
        self,
        *,
        tool_name: str,
        auth_route: str,
        input_summary: dict[str, Any],
        result_status: str,
        duration_ms: int,
        oci_request_id: str = "",
    ) -> None:
        self.tool_observations.append(
            ToolObservation(
                tool_name=tool_name,
                auth_route=auth_route,
                input_summary=input_summary,
                result_status=result_status,
                duration_ms=duration_ms,
                oci_request_id=oci_request_id,
            )
        )

    def add_prompt_observation(
        self,
        *,
        operation: str,
        model_name: str,
        input_summary: str,
        output_summary: str,
        duration_ms: int,
        token_usage: dict[str, Any] | None = None,
    ) -> None:
        self.prompt_observations.append(
            PromptObservation(
                operation=operation,
                model_name=model_name,
                input_summary=input_summary,
                output_summary=output_summary,
                duration_ms=duration_ms,
                token_usage=token_usage or {},
            )
        )

    def add_notice(self, *, notice_type: str, message: str, next_actions: list[str]) -> None:
        self.notices.append(
            {
                "notice_type": notice_type,
                "message": message,
                "next_actions": next_actions,
                "created_at": utc_now().isoformat(),
            }
        )

    def finalize(self, status: str) -> None:
        self.finished_at = utc_now()
        self.status = status

