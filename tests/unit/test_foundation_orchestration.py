from __future__ import annotations

from dataclasses import dataclass

from iam_agent.application.action_planner import ActionPlanner
from iam_agent.application.input_guard import InputGuard
from iam_agent.application.orchestrator import Orchestrator
from iam_agent.application.response_summarizer import ResponseSummarizer
from iam_agent.application.retry_controller import RetryController
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.domain.models import ActionPlan, ActionPlanStep, ResponseDraft, SemanticValidationResult, SkillExecutionResult
from iam_agent.infra.logging.audit_logger import AuditLogger


class DummyPlanner:
    def __init__(self, step: ActionPlanStep) -> None:
        self.step = step

    def create_plan(self, turn_id: str, user_input: str) -> ActionPlan:
        return ActionPlan(plan_id="p1", turn_id=turn_id, steps=[self.step])


class DummySummarizer:
    def summarize(self, *, turn_id: str, user_input: str, attempt: int, results: list[SkillExecutionResult]) -> ResponseDraft:
        return ResponseDraft(
            turn_id=turn_id,
            attempt=attempt,
            facts=["f1"],
            interpretation=["i1"],
            proposal=["p1"],
            referenced_requests=[r.request_id for r in results],
        )

    def to_normalized_response(self, draft: ResponseDraft, results: list[SkillExecutionResult]) -> NormalizedResponse:
        return NormalizedResponse.success(
            facts=draft.facts,
            interpretation=draft.interpretation,
            proposal=draft.proposal,
            data={"count": len(results)},
            audit=AuditPayload(result="success"),
        )


class DummySemanticValidator:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.index = 0

    def validate(self, *, turn_id: str, attempt: int, user_input: str, draft: ResponseDraft) -> SemanticValidationResult:
        status = self.statuses[min(self.index, len(self.statuses) - 1)]
        self.index += 1
        return SemanticValidationResult(turn_id=turn_id, attempt=attempt, status=status, reason=["test"]) 


def test_input_guard_missing_inputs_detected() -> None:
    guard = InputGuard()
    step = ActionPlanStep(
        step_id="s1",
        tool_name="get_user",
        required_inputs=["user_id"],
        provided_inputs={"user_id": ""},
    )

    missing = guard.find_missing_inputs(step)
    assert missing == ["user_id"]


def test_input_guard_defers_create_user_missing_check() -> None:
    guard = InputGuard()
    step = ActionPlanStep(
        step_id="s1",
        tool_name="create_user",
        required_inputs=["family_name", "given_name", "email"],
        provided_inputs={},
    )
    assert guard.find_missing_inputs(step) == []


def test_input_guard_accepts_legacy_group_membership_alias_inputs() -> None:
    guard = InputGuard()
    step = ActionPlanStep(
        step_id="s1",
        tool_name="add_user_to_group",
        required_inputs=["user_selector", "group_selector"],
        provided_inputs={"user_id": "u1", "group_id": "g1"},
    )
    assert guard.find_missing_inputs(step) == []


def test_retry_controller_abort_after_three_failures() -> None:
    controller = RetryController(max_attempts=3)
    assert controller.register("not_aligned") == "replan"
    assert controller.register("not_aligned") == "replan"
    assert controller.register("not_aligned") == "abort"


def test_skill_executor_unknown_tool() -> None:
    executor = SkillExecutor(handlers={})
    result = executor.execute("unknown_tool", {})
    assert result.status == "error"
    assert result.error_code == "unknown_tool"


def test_skill_executor_propagates_error_code_from_normalized_response() -> None:
    executor = SkillExecutor(
        handlers={
            "list_users": lambda payload: NormalizedResponse.error(
                message="権限不足です",
                code="permission_denied",
                retryable=False,
                proposal=["権限を確認してください。"],
                audit=AuditPayload(result="error"),
            )
        }
    )
    result = executor.execute("list_users", {})
    assert result.status == "error"
    assert result.error_code == "permission_denied"
    assert result.error_message == "権限不足です"


def test_orchestrator_retries_and_aborts_on_semantic_mismatch() -> None:
    planner = DummyPlanner(
        ActionPlanStep(
            step_id="s1",
            tool_name="list_users",
            required_inputs=[],
            provided_inputs={},
            execution_order=1,
        )
    )

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

    orchestrator = Orchestrator(
        action_planner=planner,
        input_guard=InputGuard(),
        skill_executor=executor,
        response_summarizer=DummySummarizer(),
        semantic_validator=DummySemanticValidator(["not_aligned", "not_aligned", "not_aligned"]),
        retry_controller=RetryController(max_attempts=3),
        audit_logger=AuditLogger(),
    )

    response = orchestrator.handle_user_input(turn_id="t1", user_input="一覧を見せて")
    assert response.status == "error"
    assert response.errors is not None
    assert response.errors[0].code == "MAX_RETRY_EXCEEDED"


class DummyGenAIStringSummary:
    def summarize_response(self, user_input, payload):
        return {
            "facts": "ユーザー一覧を取得しました。",
            "interpretation": "結果を確認してください。",
            "proposal": "必要なら条件を追加してください。",
        }


def test_response_summarizer_accepts_string_sections() -> None:
    summarizer = ResponseSummarizer(genai_client=DummyGenAIStringSummary())  # type: ignore[arg-type]
    result = summarizer.summarize(
        turn_id="t1",
        user_input="test",
        attempt=1,
        results=[
            SkillExecutionResult(
                request_id="r1",
                tool_name="list_users",
                status="success",
                normalized_data={"users": []},
            )
        ],
    )
    assert result.facts == ["ユーザー一覧を取得しました。"]
    assert result.interpretation == ["結果を確認してください。"]
    assert result.proposal == ["必要なら条件を追加してください。"]


class DummyGenAIStructuredStringSummary:
    def summarize_response(self, user_input, payload):  # noqa: ARG002
        return {
            "facts": "{'総ユーザー数': 2, 'ユーザー一覧': [{'displayName': 'A', 'userName': 'a'}]}",
            "interpretation": "['全件取得', 'ロックなし']",
            "proposal": "{'次の操作': '詳細確認'}",
        }


def test_response_summarizer_formats_structured_string_sections() -> None:
    summarizer = ResponseSummarizer(genai_client=DummyGenAIStructuredStringSummary())  # type: ignore[arg-type]
    result = summarizer.summarize(
        turn_id="t1",
        user_input="ユーザー一覧を出して",
        attempt=1,
        results=[
            SkillExecutionResult(
                request_id="r1",
                tool_name="list_users",
                status="success",
                normalized_data={"users": []},
            )
        ],
    )
    assert "総ユーザー数: 2" in result.facts
    assert "ユーザー一覧:" in result.facts
    assert "1. 全件取得" in result.interpretation
    assert "次の操作: 詳細確認" in result.proposal


class DummyGenAIPlanner:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_name": "create_user",
                    "required_inputs": ["family_name", "given_name", "email"],
                    "provided_inputs": {},
                    "execution_order": 1,
                }
            ]
        }


def test_action_planner_infers_create_user_hint_from_kanji_name() -> None:
    planner = ActionPlanner(genai_client=DummyGenAIPlanner())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t1", user_input="田中さんのためにOCIユーザーを作成してください")
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "create_user"
    assert plan.steps[0].provided_inputs.get("family_name_kanji") == "田中"


class DummyGenAIPlannerWithRefs:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_name": "create_user",
                    "required_inputs": ["family_name", "given_name", "email"],
                    "provided_inputs": {
                        "user_name": "ken.tanaka@example.com",
                        "email": "${step1.result.email}",
                    },
                    "execution_order": 1,
                }
            ]
        }


def test_action_planner_normalizes_create_user_inputs_and_drops_unresolved_refs() -> None:
    planner = ActionPlanner(genai_client=DummyGenAIPlannerWithRefs())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t1", user_input="田中さんのためにOCIユーザーを作成してください")
    inputs = plan.steps[0].provided_inputs

    assert "user_name" not in inputs
    assert inputs.get("username") == "ken.tanaka@example.com"
    assert "email" not in inputs
    assert inputs.get("family_name_kanji") == "田中"


def test_action_planner_detects_permission_investigation_for_allowed_operations_phrase() -> None:
    class DummyGenAI:
        def plan_action(self, user_input, available_tools):  # noqa: ARG002
            return {"steps": []}

    planner = ActionPlanner(genai_client=DummyGenAI())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t1", user_input="加藤さんはどの操作が許可されていますか？")
    assert plan.request_type == "permission_investigation"


def test_input_guard_allows_get_user_with_user_selector() -> None:
    guard = InputGuard()
    step = ActionPlanStep(
        step_id="s1",
        tool_name="get_user",
        required_inputs=["user_id"],
        provided_inputs={"user_selector": {"name": "加藤"}},
    )
    assert guard.find_missing_inputs(step) == []


class DummyGenAIPlannerWrongToolForCreateIntent:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_name": "add_user_to_group",
                    "required_inputs": ["user_id", "group_id"],
                    "provided_inputs": {},
                    "execution_order": 1,
                }
            ]
        }


def test_action_planner_forces_create_user_on_oci_user_add_request() -> None:
    planner = ActionPlanner(genai_client=DummyGenAIPlannerWrongToolForCreateIntent())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t1", user_input="山田さんをOCIユーザーとして追加して")
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "create_user"
    assert plan.steps[0].required_inputs == ["family_name", "given_name", "email"]
    assert plan.steps[0].provided_inputs.get("family_name_kanji") == "山田"


class DummyGenAIPlannerWrongToolForGroupIntent:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_name": "create_user",
                    "required_inputs": ["family_name", "given_name", "email"],
                    "provided_inputs": {},
                    "execution_order": 1,
                }
            ]
        }


def test_action_planner_forces_group_membership_tool_on_group_add_request() -> None:
    planner = ActionPlanner(genai_client=DummyGenAIPlannerWrongToolForGroupIntent())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t1", user_input="鈴木さんユーザーをDomain_Administratorsグループに追加してください")

    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "add_user_to_group"
    assert plan.steps[0].required_inputs == ["user_selector", "group_selector"]
    assert plan.steps[0].provided_inputs.get("group_selector", {}).get("display_name") == "Domain_Administrators"
    assert plan.steps[0].provided_inputs.get("user_selector", {}).get("family_name_kanji") == "鈴木"


class DummyGenAIPlannerWrongRequiredInputs:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_name": "add_user_to_group",
                    "required_inputs": ["user_id", "group_id"],
                    "provided_inputs": {},
                    "execution_order": 1,
                }
            ]
        }


def test_action_planner_uses_canonical_required_inputs() -> None:
    planner = ActionPlanner(genai_client=DummyGenAIPlannerWrongRequiredInputs())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t1", user_input="グループに追加して")
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "add_user_to_group"
    assert plan.steps[0].required_inputs == ["user_selector", "group_selector"]


class DummyGenAIPlannerGetPolicyNoInput:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_name": "get_policy",
                    "required_inputs": ["policy_id"],
                    "provided_inputs": {},
                    "execution_order": 1,
                }
            ]
        }


def test_action_planner_infers_policy_name_for_get_policy() -> None:
    planner = ActionPlanner(genai_client=DummyGenAIPlannerGetPolicyNoInput())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t1", user_input="devday-iamagentポリシーを削除するとどのような影響があるか")

    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "get_policy"
    assert plan.steps[0].provided_inputs.get("policy_name") == "devday-iamagent"


def test_input_guard_accepts_get_policy_with_policy_name() -> None:
    guard = InputGuard()
    step = ActionPlanStep(
        step_id="s1",
        tool_name="get_policy",
        required_inputs=["policy_id"],
        provided_inputs={"policy_name": "devday-iamagent"},
    )
    assert guard.find_missing_inputs(step) == []


def test_input_guard_missing_workflow_inputs_detected() -> None:
    guard = InputGuard()
    missing = guard.find_missing_workflow_inputs(
        "access_denial_troubleshooting",
        {"user_hint": "山田さん"},
    )
    assert missing == ["target_resource", "requested_action"]


def test_response_summarizer_markdown_sections_format() -> None:
    summarizer = ResponseSummarizer(genai_client=DummyGenAIStringSummary())  # type: ignore[arg-type]
    markdown = summarizer.to_markdown_sections(
        facts=["ユーザーを特定しました。"],
        interpretation=["権限を評価しました。"],
        proposal=["次のアクションを確認してください。"],
    )
    assert "### 【事実】" in markdown
    assert "### 【解釈】" in markdown
    assert "### 【提案】" in markdown
