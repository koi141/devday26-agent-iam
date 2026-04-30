from __future__ import annotations

from iam_agent.application.action_planner import ActionPlanner


class DummyGenAI:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {"steps": []}


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
