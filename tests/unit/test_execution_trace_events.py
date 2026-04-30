from __future__ import annotations

from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.domain.models import ExecutionTraceEvent
from iam_agent.infra.logging.audit_logger import AuditLogger


def test_execution_trace_event_contains_skill_and_tool_layer() -> None:
    event = ExecutionTraceEvent(
        turn_id="t1",
        request_id="r1",
        layer="tool",
        skill_name="user_permission_investigation",
        tool_name="list_users",
        status="success",
        decision_reason=["trace test"],
    )

    assert event.layer == "tool"
    assert event.skill_name == "user_permission_investigation"
    assert event.tool_name == "list_users"


def test_audit_logger_record_workflow_accepts_skill_name() -> None:
    logger = AuditLogger()
    payload = logger.record_workflow(
        request_id="req-1",
        turn_id="turn-1",
        workflow_name="permission_investigation",
        skill_name="user_permission_investigation",
        execution_order=1,
        target={"workflow": "permission_investigation"},
        input_summary={"prompt": "加藤さんは何ができますか"},
        decision_reason=["skill routing"],
        result="success",
    )

    assert payload["tool_name"] == "permission_investigation"
    assert payload["skill_name"] == "user_permission_investigation"


def test_skill_executor_execute_unknown_skill_returns_error() -> None:
    executor = SkillExecutor(handlers={})

    result = executor.execute_skill("unknown_skill", turn_id="t1", user_input="test")

    assert result.status == "error"
    assert result.errors is not None
    assert result.errors[0].code == "unknown_skill"


def test_skill_executor_executes_registered_skill() -> None:
    executor = SkillExecutor(
        handlers={
            "list_users": lambda payload: NormalizedResponse.success(
                facts=["ok"],
                interpretation=["ok"],
                proposal=["ok"],
                data={"users": []},
                audit=AuditPayload(result="success"),
            )
        }
    )

    def dummy_skill(*, turn_id: str, user_input: str, payload=None):  # noqa: ARG001
        return NormalizedResponse.success(
            facts=["skill"],
            interpretation=["skill"],
            proposal=["skill"],
            data={"payload": payload or {}},
            audit=AuditPayload(result="success"),
        )

    executor.register_skill("dummy", dummy_skill)
    result = executor.execute_skill("dummy", turn_id="t1", user_input="input", payload={"a": 1})

    assert result.status == "success"
    assert result.data is not None
    assert result.data["payload"]["a"] == 1
