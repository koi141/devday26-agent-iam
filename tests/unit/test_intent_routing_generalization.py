from __future__ import annotations

from iam_agent.application.action_planner import ActionPlanner


class PlannerGenAIDummy:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {"steps": []}


def test_intent_routing_generalization_for_permission_investigation() -> None:
    planner = ActionPlanner(genai_client=PlannerGenAIDummy())  # type: ignore[arg-type]
    for prompt in (
        "鈴木さんは何ができますか？",
        "鈴木さんの権限を教えて",
        "鈴木さんの許可されている操作を確認したい",
        "佐藤さんはどのような操作を許可されている？",
    ):
        plan = planner.create_plan(turn_id="t", user_input=prompt)
        assert plan.request_type == "permission_investigation"


def test_intent_routing_generalization_for_access_denial() -> None:
    planner = ActionPlanner(genai_client=PlannerGenAIDummy())  # type: ignore[arg-type]
    for prompt in (
        "山田さんがアクセス拒否されました。原因を調べて",
        "yamada is denied to access db",
        "権限不足のトラブルシュートをしたい",
    ):
        plan = planner.create_plan(turn_id="t", user_input=prompt)
        assert plan.request_type == "access_denial_troubleshooting"


def test_intent_routing_generalization_for_single_tool_passthrough() -> None:
    planner = ActionPlanner(genai_client=PlannerGenAIDummy())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t", user_input="ユーザー一覧を出して")
    assert plan.request_type == "single_tool_passthrough"


def test_intent_routing_generalization_for_resource_listing() -> None:
    planner = ActionPlanner(genai_client=PlannerGenAIDummy())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t", user_input="devday26 のリソース一覧を表示して")
    assert plan.request_type == "single_tool_passthrough"
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "list_resources"
