from __future__ import annotations

from iam_agent.application.action_planner import ActionPlanner
from iam_agent.application.input_guard import InputGuard
from iam_agent.application.orchestrator import Orchestrator
from iam_agent.application.response_summarizer import ResponseSummarizer
from iam_agent.application.retry_controller import RetryController
from iam_agent.application.semantic_validator import SemanticValidator
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.domain.models import ActionPlan, ActionPlanStep
from iam_agent.infra.logging.audit_logger import AuditLogger
from iam_agent.observability.quality_evaluator import QualityEvaluator
from iam_agent.observability.snapshot_store import SnapshotStore
from iam_agent.observability.telemetry_bridge import TelemetryBridge


class FakeGenAIClient:
    def __init__(self):
        self.semantic_calls = 0

    def plan_action(self, user_input, available_tools):
        return {
            "steps": [
                {
                    "step_id": "s1",
                    "tool_name": "list_users",
                    "required_inputs": [],
                    "provided_inputs": {},
                    "execution_order": 1,
                }
            ]
        }

    def summarize_response(self, user_input, payload):
        return {
            "facts": ["ユーザー一覧を取得しました。"],
            "interpretation": ["0件でした。"],
            "proposal": ["検索条件を変更してください。"],
        }

    def validate_semantic_alignment(self, user_input, answer_text):
        self.semantic_calls += 1
        if self.semantic_calls < 3:
            return {"status": "not_aligned", "reason": ["不足"], "missing_points": ["条件"]}
        return {"status": "aligned", "reason": ["十分"], "missing_points": []}


class AlwaysNotAlignedGenAI(FakeGenAIClient):
    def validate_semantic_alignment(self, user_input, answer_text):
        self.semantic_calls += 1
        return {"status": "not_aligned", "reason": ["不足"], "missing_points": ["条件"]}


def build_orchestrator(genai_client) -> Orchestrator:
    planner = ActionPlanner(genai_client=genai_client)
    summarizer = ResponseSummarizer(genai_client=genai_client)
    semantic = SemanticValidator(genai_client=genai_client)

    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"users": []},
            audit=AuditPayload(result="success"),
        )
    }

    return Orchestrator(
        action_planner=planner,
        input_guard=InputGuard(),
        skill_executor=SkillExecutor(handlers=handlers),
        response_summarizer=summarizer,
        semantic_validator=semantic,
        retry_controller=RetryController(max_attempts=3),
        audit_logger=AuditLogger(),
    )


class FailingLangfuseClient:
    def send_trace(self, payload):  # noqa: ARG002
        return "failed", "simulated failure"


def test_orchestration_retries_then_success() -> None:
    genai = FakeGenAIClient()
    orchestrator = build_orchestrator(genai)

    response = orchestrator.handle_user_input(turn_id="turn1", user_input="ユーザーを確認したい")
    assert response.status == "success"
    assert genai.semantic_calls == 3


def test_orchestration_stops_after_max_retry() -> None:
    genai = AlwaysNotAlignedGenAI()
    orchestrator = build_orchestrator(genai)

    response = orchestrator.handle_user_input(turn_id="turn2", user_input="ユーザーを確認したい")
    assert response.status == "error"
    assert response.errors is not None
    assert response.errors[0].code == "MAX_RETRY_EXCEEDED"
    assert genai.semantic_calls == 3


def test_orchestration_fail_open_when_telemetry_delivery_fails() -> None:
    genai = FakeGenAIClient()
    planner = ActionPlanner(genai_client=genai)
    summarizer = ResponseSummarizer(genai_client=genai)
    semantic = SemanticValidator(genai_client=genai)
    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"users": []},
            audit=AuditPayload(result="success"),
        )
    }
    orchestrator = Orchestrator(
        action_planner=planner,
        input_guard=InputGuard(),
        skill_executor=SkillExecutor(handlers=handlers),
        response_summarizer=summarizer,
        semantic_validator=semantic,
        retry_controller=RetryController(max_attempts=3),
        audit_logger=AuditLogger(),
        telemetry_bridge=TelemetryBridge(langfuse_client=FailingLangfuseClient()),  # type: ignore[arg-type]
        quality_evaluator=QualityEvaluator(),
        snapshot_store=SnapshotStore(),
    )

    response = orchestrator.handle_user_input(turn_id="turn3", user_input="ユーザーを確認したい")
    assert response.status == "success"
    assert response.meta is not None
    assert response.meta["telemetry_delivery_status"] == "failed"
