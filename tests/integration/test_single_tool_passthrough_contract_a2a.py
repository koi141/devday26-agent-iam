from __future__ import annotations

from iam_agent.application.action_planner import ActionPlanner


class DummyGenAI:
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


def test_single_tool_passthrough_contract_remains_after_a2a_addition() -> None:
    planner = ActionPlanner(genai_client=DummyGenAI())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t1", user_input="ポリシー一覧を表示して")
    assert plan.request_type == "single_tool_passthrough"
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "list_policies"
