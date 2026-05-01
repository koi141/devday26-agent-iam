from __future__ import annotations

from iam_agent.application.action_planner import ActionPlanner
from iam_agent.application.errors import TemporaryUpstreamFailure


class DummyGenAI:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {"steps": []}


class DummyGenAIFailing:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        raise TemporaryUpstreamFailure("genai service unavailable")


def test_permission_investigation_routes_to_skill_name() -> None:
    planner = ActionPlanner(genai_client=DummyGenAI())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t1", user_input="加藤さんは何ができますか？")

    assert plan.request_type == "permission_investigation"
    assert plan.skill_name == "user_permission_investigation"


def test_access_denial_routes_to_skill_name() -> None:
    planner = ActionPlanner(genai_client=DummyGenAI())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t2", user_input="加藤さんがDBにアクセスできない理由を調べて")

    assert plan.request_type == "access_denial_troubleshooting"
    assert plan.skill_name == "access_denial_troubleshooting"


def test_single_tool_passthrough_has_default_skill_name() -> None:
    planner = ActionPlanner(genai_client=DummyGenAI())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t3", user_input="ポリシー一覧を表示して")

    assert plan.request_type == "single_tool_passthrough"
    assert plan.skill_name == "single_tool_passthrough"


def test_single_tool_passthrough_falls_back_when_genai_plan_fails() -> None:
    planner = ActionPlanner(genai_client=DummyGenAIFailing())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t4", user_input="ポリシー一覧を表示して")

    assert plan.request_type == "single_tool_passthrough"
    assert plan.steps[0].tool_name == "list_policies"
    assert plan.planned_by_model == "heuristic_fallback"
