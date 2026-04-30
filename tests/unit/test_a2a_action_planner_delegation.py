from __future__ import annotations

from iam_agent.application.action_planner import ActionPlanner


class DummyGenAI:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {"steps": []}


def test_action_planner_generates_delegate_step_for_delegation_intent() -> None:
    planner = ActionPlanner(genai_client=DummyGenAI())  # type: ignore[arg-type]
    plan = planner.create_plan(turn_id="t1", user_input="この問い合わせは他エージェントへ委譲して")
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "delegate_to_peer"
    assert plan.steps[0].provided_inputs.get("objective")
