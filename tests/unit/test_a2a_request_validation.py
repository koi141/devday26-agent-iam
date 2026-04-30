from __future__ import annotations

from iam_agent.application.input_guard import InputGuard


def test_find_missing_a2a_request_fields_detects_required_keys() -> None:
    guard = InputGuard()
    missing = guard.find_missing_a2a_request_fields(
        {
            "request_id": "req-1",
            "source_agent_id": "peer-1",
            "target_agent_id": "iam-agent",
            "requested_operation": "list_users",
            "objective": "一覧を取得",
            "input_payload": {},
            "hop_count": 0,
            "visited_agents": [],
        }
    )
    assert "correlation_id" in missing


def test_delegate_to_peer_requires_operation_and_objective() -> None:
    from iam_agent.domain.models import ActionPlanStep

    guard = InputGuard()
    step = ActionPlanStep(
        step_id="s1",
        tool_name="delegate_to_peer",
        required_inputs=["objective"],
        provided_inputs={"objective": "", "requested_operation": ""},
    )
    missing = guard.find_missing_inputs(step)
    assert missing == ["objective", "requested_operation"]
