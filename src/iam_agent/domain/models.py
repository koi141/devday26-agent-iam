from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class UserInputTurn:
    turn_id: str
    user_input: str
    received_at: datetime = field(default_factory=utc_now)
    language: str = "ja"


@dataclass(slots=True)
class ActionPlanStep:
    step_id: str
    tool_name: str
    required_inputs: list[str] = field(default_factory=list)
    provided_inputs: dict[str, Any] = field(default_factory=dict)
    execution_order: int = 1
    reason: str = ""


@dataclass(slots=True)
class ActionPlan:
    plan_id: str
    turn_id: str
    steps: list[ActionPlanStep]
    skill_name: str = ""
    request_type: Literal[
        "permission_investigation",
        "access_denial_troubleshooting",
        "single_tool_passthrough",
    ] = "single_tool_passthrough"
    planned_by_model: str = ""
    plan_reasoning_summary: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)

    def ordered_steps(self) -> list[ActionPlanStep]:
        return sorted(self.steps, key=lambda item: item.execution_order)


@dataclass(slots=True)
class MissingInputRequest:
    turn_id: str
    step_id: str
    tool_name: str
    missing_fields: list[str]
    why_needed: list[str]
    prompt_to_user: str


@dataclass(slots=True)
class ToolInvocation:
    request_id: str
    turn_id: str
    plan_id: str
    tool_name: str
    input: dict[str, Any]
    requested_at: datetime = field(default_factory=utc_now)
    auth_route: str = ""
    caller: str = "chainlit"


@dataclass(slots=True)
class SkillExecutionResult:
    request_id: str
    tool_name: str
    status: str
    raw_response: dict[str, Any] | None = None
    normalized_data: dict[str, Any] | None = None
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False
    auth_route: str = ""
    duration_ms: int = 0
    oci_request_id: str = ""
    executed_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class ExecutionTraceEvent:
    turn_id: str
    request_id: str
    layer: Literal["skill", "tool"]
    skill_name: str = ""
    tool_name: str = ""
    status: str = ""
    decision_reason: list[str] = field(default_factory=list)
    recorded_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class ResponseDraft:
    turn_id: str
    attempt: int
    facts: list[str]
    interpretation: list[str]
    proposal: list[str]
    referenced_requests: list[str]
    generated_by_model: str = ""
    generated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class SemanticValidationResult:
    turn_id: str
    attempt: int
    status: str
    reason: list[str]
    missing_points: list[str] = field(default_factory=list)
    checked_by_model: str = ""
    checked_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class RetryState:
    turn_id: str
    attempt_count: int = 0
    max_attempts: int = 3
    last_status: str = ""
    next_action: str = "replan"
    terminated_reason: str = ""


@dataclass(slots=True)
class AuditLogEvent:
    request_id: str
    turn_id: str
    tool_name: str
    target: dict[str, Any]
    input_summary: dict[str, Any]
    decision_reason: list[str]
    result: str
    retryable: bool
    skill_name: str = ""
    execution_order: int = 1
    actor: str = "iam-agent"
    error_class: str = ""
    oci_request_id: str = ""
    evidence_links: list[str] = field(default_factory=list)
    compatibility_status: str = ""
    trace_id: str = ""
    telemetry_delivery_status: str = ""
    telemetry_delivery_reason: str = ""
    correlation_id: str = ""
    peer_agent: str = ""
    delegation_outcome: str = ""
    recorded_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class InvestigationRequest:
    request_id: str
    request_type: Literal[
        "permission_investigation",
        "access_denial_troubleshooting",
        "single_tool_passthrough",
    ]
    raw_prompt: str
    intent_confidence: float = 0.0
    received_at: datetime = field(default_factory=utc_now)
    language: str = "ja"


@dataclass(slots=True)
class UserResolutionCandidate:
    candidate_id: str
    source: Literal["oci", "hr"]
    oci_user_id: str = ""
    username: str = ""
    email: str = ""
    display_name: str = ""
    match_reason: list[str] = field(default_factory=list)
    score: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UserResolutionResult:
    request_id: str
    status: Literal["resolved", "ambiguous", "insufficient", "not_found"]
    selected_user: UserResolutionCandidate | None = None
    candidates: list[UserResolutionCandidate] = field(default_factory=list)
    required_confirmation_fields: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Evidence:
    evidence_id: str
    evidence_type: Literal["group_membership", "policy", "constraint", "other"]
    source: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    source_trace: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CompatibilityCheck:
    check_id: str
    baseline_tool: str
    input_contract_unchanged: bool
    output_contract_unchanged: bool
    regression_test_refs: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class AccessDenialCase:
    case_id: str
    request_id: str
    target_user_id: str = ""
    target_resource: str = ""
    requested_action: str = ""
    reported_symptom: str = ""


@dataclass(slots=True)
class RootCauseFinding:
    case_id: str
    status: Literal["confirmed", "hypothesis", "unresolved"]
    cause_category: Literal["missing_policy", "group_mismatch", "constraint_block", "permission_scope", "other"]
    description: str
    evidence_links: list[str] = field(default_factory=list)
    additional_inputs_required: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RemediationProposal:
    proposal_id: str
    case_id: str
    proposal_type: Literal["agent_executable", "user_next_action"]
    action_description: str
    preconditions: list[str] = field(default_factory=list)
    high_risk_flag: bool = False


@dataclass(slots=True)
class CompatibilityCheckRecord:
    check_id: str
    baseline_tool: str
    input_contract_unchanged: bool
    output_contract_unchanged: bool
    regression_test_refs: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class PeerAgent:
    agent_id: str
    display_name: str
    trust_state: Literal["trusted", "blocked", "pending"] = "pending"
    base_url: str = ""
    supported_operations: list[str] = field(default_factory=list)
    priority: int = 100
    last_verified_at: datetime | None = None


@dataclass(slots=True)
class A2ACapabilityOperation:
    operation_name: str
    required_inputs: list[str] = field(default_factory=list)
    risk_level: Literal["low", "high"] = "low"
    description: str = ""


@dataclass(slots=True)
class A2ACapabilityProfile:
    agent_id: str
    version: str
    operations: list[A2ACapabilityOperation] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class A2AExecutionRequest:
    request_id: str
    correlation_id: str
    source_agent_id: str
    target_agent_id: str
    requested_operation: str
    objective: str
    input_payload: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    hop_count: int = 0
    visited_agents: list[str] = field(default_factory=list)
    requested_at: datetime = field(default_factory=utc_now)

    REQUIRED_FIELDS = (
        "request_id",
        "correlation_id",
        "source_agent_id",
        "target_agent_id",
        "requested_operation",
        "objective",
    )

    @classmethod
    def missing_fields(cls, payload: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for key in cls.REQUIRED_FIELDS:
            raw = payload.get(key)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                missing.append(key)
        if payload.get("input_payload") is None:
            missing.append("input_payload")
        if payload.get("hop_count") is None:
            missing.append("hop_count")
        if payload.get("visited_agents") is None:
            missing.append("visited_agents")
        return missing

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "A2AExecutionRequest":
        requested_at = payload.get("requested_at")
        if isinstance(requested_at, datetime):
            req_at = requested_at
        else:
            req_at = utc_now()
        return cls(
            request_id=str(payload.get("request_id") or "").strip(),
            correlation_id=str(payload.get("correlation_id") or "").strip(),
            source_agent_id=str(payload.get("source_agent_id") or "").strip(),
            target_agent_id=str(payload.get("target_agent_id") or "").strip(),
            requested_operation=str(payload.get("requested_operation") or "").strip(),
            objective=str(payload.get("objective") or "").strip(),
            input_payload=payload.get("input_payload") if isinstance(payload.get("input_payload"), dict) else {},
            constraints=payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {},
            idempotency_key=str(payload.get("idempotency_key") or "").strip(),
            hop_count=int(payload.get("hop_count") or 0),
            visited_agents=[str(x) for x in (payload.get("visited_agents") or []) if str(x).strip()],
            requested_at=req_at,
        )


@dataclass(slots=True)
class A2AExecutionStep:
    step_id: str
    executor_agent_id: str
    operation_name: str
    status: Literal["success", "failed", "partial_success", "skipped"]
    facts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None


@dataclass(slots=True)
class A2AExecutionResult:
    request_id: str
    correlation_id: str
    overall_status: Literal["success", "partial_success", "error", "needs_confirmation"]
    facts: list[str]
    interpretation: list[str]
    proposal: list[str]
    steps: list[A2AExecutionStep] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class A2AIdempotencyRecord:
    idempotency_key: str
    request_fingerprint: str
    first_seen_at: datetime = field(default_factory=utc_now)
    final_status: Literal["success", "error", "partial_success"] = "error"
    response_reference: str = ""


@dataclass(slots=True)
class A2AAuditRecord:
    actor: str
    target: dict[str, Any]
    timestamp: datetime
    request_summary: dict[str, Any]
    decision_reason: list[str]
    result: str
    correlation_id: str
    request_id: str
    oci_request_id: str = ""
