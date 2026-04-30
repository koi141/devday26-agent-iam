from __future__ import annotations

from iam_agent.application.action_planner import ActionPlanner
from iam_agent.application.input_guard import InputGuard
from iam_agent.application.orchestrator import Orchestrator
from iam_agent.application.response_summarizer import ResponseSummarizer
from iam_agent.application.retry_controller import RetryController
from iam_agent.application.semantic_validator import SemanticValidator
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.infra.logging.audit_logger import AuditLogger


class GenAIDummy:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {"steps": []}

    def summarize_response(self, user_input, payload):  # noqa: ARG002
        return {
            "facts": ["処理完了"],
            "interpretation": ["単体ツール結果です。"],
            "proposal": ["必要に応じて条件を変更してください。"],
        }

    def validate_semantic_alignment(self, user_input, answer_text):  # noqa: ARG002
        return {"status": "aligned", "reason": ["ok"], "missing_points": []}


def _build_orchestrator() -> Orchestrator:
    genai = GenAIDummy()
    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"users": [{"id": "u1", "userName": "yamada@example.com", "displayName": "山田 太郎", "groups": [{"display": "DevGroup"}]}]},
            audit=AuditPayload(result="success"),
        ),
        "query_hr_database": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"candidates": [], "candidate_count": 0},
            audit=AuditPayload(result="success"),
        ),
        "get_user": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"user": {"id": payload["user_id"], "userName": "yamada@example.com", "displayName": "山田 太郎", "groups": [{"display": "DevGroup"}]}},
            audit=AuditPayload(result="success"),
        ),
        "list_groups": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"groups": []},
            audit=AuditPayload(result="success"),
        ),
        "list_policies": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"policies": [{"id": "p1", "name": "p", "statements": ["Allow group DevGroup to read all-resources in tenancy"]}]},
            audit=AuditPayload(result="success"),
        ),
        "get_last_successful_login": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"last_successful_login_at": "2026-04-01T00:00:00Z"},
            audit=AuditPayload(result="success"),
        ),
    }
    return Orchestrator(
        action_planner=ActionPlanner(genai_client=genai),  # type: ignore[arg-type]
        input_guard=InputGuard(),
        skill_executor=SkillExecutor(handlers=handlers),
        response_summarizer=ResponseSummarizer(genai_client=genai),  # type: ignore[arg-type]
        semantic_validator=SemanticValidator(genai_client=genai),  # type: ignore[arg-type]
        retry_controller=RetryController(max_attempts=3),
        audit_logger=AuditLogger(),
    )


def test_us3_single_tool_path_kept() -> None:
    orchestrator = _build_orchestrator()
    response = orchestrator.handle_user_input(turn_id="t1", user_input="ポリシー一覧を表示して")
    assert response.status == "success"
    assert response.data is not None
    assert "list_policies" in response.data


def test_us3_additive_layer_permission_investigation_path() -> None:
    orchestrator = _build_orchestrator()
    response = orchestrator.handle_user_input(turn_id="t2", user_input="山田さんは何ができますか？")
    assert response.status == "success"
    assert response.data is not None
    assert response.data.get("request_type") == "permission_investigation"
