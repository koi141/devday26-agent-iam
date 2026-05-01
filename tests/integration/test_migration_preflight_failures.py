from __future__ import annotations

from iam_agent.application.input_guard import InputGuard
from iam_agent.application.orchestrator import Orchestrator
from iam_agent.application.response_summarizer import ResponseSummarizer
from iam_agent.application.runtime_preflight import run_runtime_preflight
from iam_agent.application.retry_controller import RetryController
from iam_agent.application.semantic_validator import SemanticValidator
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.config.settings import Settings
from iam_agent.infra.logging.audit_logger import AuditLogger


class _PlannerShouldNotRun:
    def create_plan(self, turn_id: str, user_input: str):  # noqa: ARG002
        raise AssertionError("runtime preflight 失敗時は planner を実行しない")


class _GenAIDummy:
    def summarize_response(self, user_input, payload):  # noqa: ANN001,ARG002
        return {"facts": ["ok"], "interpretation": ["ok"], "proposal": ["ok"]}

    def validate_semantic_alignment(self, user_input, answer_text):  # noqa: ANN001,ARG002
        return {"status": "aligned", "reason": ["ok"], "missing_points": []}


def test_runtime_preflight_failure_blocks_orchestration() -> None:
    orchestrator = Orchestrator(
        action_planner=_PlannerShouldNotRun(),  # type: ignore[arg-type]
        input_guard=InputGuard(),
        skill_executor=SkillExecutor(handlers={}),
        response_summarizer=ResponseSummarizer(genai_client=_GenAIDummy()),  # type: ignore[arg-type]
        semantic_validator=SemanticValidator(genai_client=_GenAIDummy()),  # type: ignore[arg-type]
        retry_controller=RetryController(max_attempts=3),
        audit_logger=AuditLogger(),
        runtime_preflight_checker=lambda: run_runtime_preflight(Settings()),
    )

    response = orchestrator.handle_user_input(turn_id="t-preflight", user_input="ユーザー一覧を出して")

    assert response.status == "error"
    assert response.errors is not None
    assert response.errors[0].code == "runtime_config_invalid"
    assert response.meta is not None
    assert response.meta.get("missing_items")
