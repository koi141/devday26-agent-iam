from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal


ResponseStatus = Literal["success", "partial_success", "needs_confirmation", "error"]
RequestType = Literal["permission_investigation", "access_denial_troubleshooting", "single_tool_passthrough"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ErrorDetail:
    code: str
    message: str
    retryable: bool = False


@dataclass(slots=True)
class AuditPayload:
    target: dict[str, Any] = field(default_factory=dict)
    input_summary: dict[str, Any] = field(default_factory=dict)
    decision_reason: list[str] = field(default_factory=list)
    result: str = ""
    correlation_id: str = ""
    peer_agent: str = ""
    delegation_outcome: str = ""


@dataclass(slots=True)
class NormalizedResponse:
    status: ResponseStatus
    facts: list[str] = field(default_factory=list)
    interpretation: list[str] = field(default_factory=list)
    proposal: list[str] = field(default_factory=list)
    data: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    errors: list[ErrorDetail] | None = None
    audit: AuditPayload = field(default_factory=AuditPayload)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["errors"] is None:
            payload.pop("errors")
        if payload["data"] is None:
            payload.pop("data")
        if payload["meta"] is None:
            payload.pop("meta")
        return payload

    @classmethod
    def success(
        cls,
        *,
        facts: list[str],
        interpretation: list[str],
        proposal: list[str],
        data: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
        audit: AuditPayload,
    ) -> "NormalizedResponse":
        return cls(
            status="success",
            facts=facts,
            interpretation=interpretation,
            proposal=proposal,
            data=data,
            meta=meta,
            audit=audit,
        )

    @classmethod
    def needs_confirmation(
        cls,
        *,
        facts: list[str],
        interpretation: list[str],
        proposal: list[str],
        data: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
        audit: AuditPayload,
    ) -> "NormalizedResponse":
        return cls(
            status="needs_confirmation",
            facts=facts,
            interpretation=interpretation,
            proposal=proposal,
            data=data,
            meta=meta,
            audit=audit,
        )

    @classmethod
    def partial_success(
        cls,
        *,
        facts: list[str],
        interpretation: list[str],
        proposal: list[str],
        data: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
        audit: AuditPayload,
    ) -> "NormalizedResponse":
        return cls(
            status="partial_success",
            facts=facts,
            interpretation=interpretation,
            proposal=proposal,
            data=data,
            meta=meta,
            audit=audit,
        )

    @classmethod
    def error(
        cls,
        *,
        message: str,
        code: str,
        retryable: bool,
        proposal: list[str],
        meta: dict[str, Any] | None = None,
        audit: AuditPayload,
    ) -> "NormalizedResponse":
        return cls(
            status="error",
            facts=["要求を完了できませんでした。"],
            interpretation=[message],
            proposal=proposal,
            meta=meta,
            errors=[ErrorDetail(code=code, message=message, retryable=retryable)],
            audit=audit,
        )


@dataclass(slots=True)
class InvestigationWorkflowContract:
    request_type: RequestType
    required_inputs: list[str] = field(default_factory=list)
    optional_inputs: list[str] = field(default_factory=list)
    execution_steps: list[str] = field(default_factory=list)
    output_format: str = "markdown"


@dataclass(slots=True)
class CompatibilityCheckRecord:
    check_id: str
    baseline_tool: str
    input_contract_unchanged: bool
    output_contract_unchanged: bool
    regression_test_refs: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=_utc_now)
