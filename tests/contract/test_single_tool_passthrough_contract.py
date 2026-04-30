from __future__ import annotations

from iam_agent.application.action_planner import ActionPlanner


class PlannerGenAIDummyPolicies:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {
            "steps": [
                {
                    "step_id": "step-1",
                    "tool_name": "list_policies",
                    "required_inputs": [],
                    "provided_inputs": {},
                    "execution_order": 1,
                }
            ]
        }


class PlannerGenAIDummyNoStep:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {"steps": []}


def test_single_tool_passthrough_request_type_contract() -> None:
    planner = ActionPlanner(genai_client=PlannerGenAIDummyPolicies())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t1", user_input="ポリシー一覧を表示して")
    assert plan.request_type == "single_tool_passthrough"
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "list_policies"


def test_single_tool_passthrough_resource_listing_contract() -> None:
    planner = ActionPlanner(genai_client=PlannerGenAIDummyNoStep())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t2", user_input="devday26 のリソース一覧を表示して")
    assert plan.request_type == "single_tool_passthrough"
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "list_resources"
