from __future__ import annotations

from iam_agent.application.input_guard import InputGuard
from iam_agent.domain.models import A2AExecutionRequest


def _base_payload() -> dict[str, object]:
    return {
        "request_id": "req-1",
        "correlation_id": "corr-1",
        "source_agent_id": "peer-1",
        "target_agent_id": "iam-agent",
        "requested_operation": "list_users",
        "objective": "ユーザー一覧を取得する",
        "input_payload": {},
        "hop_count": 0,
        "visited_agents": [],
    }


def test_a2a_request_missing_fields_detected() -> None:
    payload = _base_payload()
    payload.pop("correlation_id")
    payload.pop("input_payload")
    missing = A2AExecutionRequest.missing_fields(payload)  # type: ignore[arg-type]
    assert "correlation_id" in missing
    assert "input_payload" in missing


def test_a2a_validate_hop_limit_exceeded() -> None:
    payload = _base_payload()
    payload["hop_count"] = 4
    guard = InputGuard()
    violations = guard.validate_a2a_request(payload, max_hops=3, self_agent_id="iam-agent", high_risk_operations=set())
    assert "hop_count_exceeded" in violations


def test_a2a_validate_loop_detected() -> None:
    payload = _base_payload()
    payload["visited_agents"] = ["peer-1", "iam-agent"]
    guard = InputGuard()
    violations = guard.validate_a2a_request(payload, max_hops=3, self_agent_id="iam-agent", high_risk_operations=set())
    assert "loop_detected" in violations


def test_a2a_validate_high_risk_requires_idempotency_key() -> None:
    payload = _base_payload()
    payload["requested_operation"] = "create_user"
    guard = InputGuard()
    violations = guard.validate_a2a_request(
        payload,
        max_hops=3,
        self_agent_id="iam-agent",
        high_risk_operations={"create_user", "add_user_to_group", "remove_user_from_group"},
    )
    assert "idempotency_key" in violations
