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
from iam_agent.observability.quality_evaluator import QualityEvaluator
from iam_agent.observability.snapshot_store import SnapshotStore
from iam_agent.observability.telemetry_bridge import TelemetryBridge


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.payloads = []

    def send_trace(self, payload):
        self.payloads.append(payload)
        return "sent", "ok"


class FakeGenAI:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
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

    def summarize_response(self, user_input, payload):  # noqa: ARG002
        return {"facts": ["一覧を取得"], "interpretation": ["成功"], "proposal": ["次へ"]}

    def validate_semantic_alignment(self, user_input, answer_text):  # noqa: ARG002
        return {"status": "aligned", "reason": ["ok"], "missing_points": []}


def test_us1_trace_visibility_end_to_end() -> None:
    fake_langfuse = FakeLangfuseClient()
    genai = FakeGenAI()
    orchestrator = Orchestrator(
        action_planner=ActionPlanner(genai_client=genai),
        input_guard=InputGuard(),
        skill_executor=SkillExecutor(
            handlers={
                "list_users": lambda payload: NormalizedResponse.success(
                    facts=["ok"],
                    interpretation=["ok"],
                    proposal=["ok"],
                    data={"users": []},
                    audit=AuditPayload(result="success"),
                )
            }
        ),
        response_summarizer=ResponseSummarizer(genai_client=genai),
        semantic_validator=SemanticValidator(genai_client=genai),
        retry_controller=RetryController(max_attempts=3),
        audit_logger=AuditLogger(),
        telemetry_bridge=TelemetryBridge(langfuse_client=fake_langfuse),  # type: ignore[arg-type]
        quality_evaluator=QualityEvaluator(),
        snapshot_store=SnapshotStore(),
    )

    response = orchestrator.handle_user_input(turn_id="turn-us1", user_input="ユーザー一覧を出して")

    assert response.status == "success"
    assert response.meta is not None
    assert response.meta["trace_id"].startswith("trace-")
    assert response.meta["telemetry_delivery_status"] == "sent"
    assert fake_langfuse.payloads
    stages = [span["stage"] for span in fake_langfuse.payloads[0]["spans"]]
    assert "action_planning" in stages
    assert "tool_execution" in stages
    assert "response_summarization" in stages
    assert "semantic_validation" in stages
