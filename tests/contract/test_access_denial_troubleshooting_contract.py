from __future__ import annotations

from iam_agent.application.access_diagnoser import AccessDiagnoser
from iam_agent.application.action_planner import ActionPlanner
from iam_agent.application.permission_investigator import PermissionInvestigator
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse


class PlannerGenAIDummy:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {"steps": []}


def test_access_denial_plan_contract() -> None:
    planner = ActionPlanner(genai_client=PlannerGenAIDummy())  # type: ignore[arg-type]
    plan = planner.create_plan(
        turn_id="t1",
        user_input="山田さんが開発環境DBへアクセス拒否されました。原因を調べてください",
    )
    assert plan.request_type == "access_denial_troubleshooting"
    assert [step.tool_name for step in plan.steps[:3]] == ["list_users", "query_hr_database", "get_user"]


def test_access_denial_output_contract_three_sections() -> None:
    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"users": [{"id": "u1", "userName": "yamada.taro@example.com", "displayName": "山田 太郎", "groups": [{"display": "DevGroup"}]}]},
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
            data={
                "user": {
                    "id": payload["user_id"],
                    "displayName": "山田 太郎",
                    "userName": "yamada.taro@example.com",
                    "groups": [{"display": "DevGroup"}],
                }
            },
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
            data={"policies": [{"id": "p1", "name": "db-policy", "statements": ["Allow group DevGroup to read buckets in compartment dev"]}]},
            audit=AuditPayload(result="success"),
        ),
        "get_last_successful_login": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"last_successful_login_at": "2026-04-10T00:00:00Z"},
            audit=AuditPayload(result="success"),
        ),
    }
    investigator = PermissionInvestigator(skill_executor=SkillExecutor(handlers=handlers))
    diagnoser = AccessDiagnoser(permission_investigator=investigator)
    response = diagnoser.diagnose(
        turn_id="t1",
        user_input="山田さんが「開発環境DB」にアクセスできない。read操作で拒否される原因を調べて",
    )

    assert response.status == "success"
    assert response.facts
    assert response.interpretation
    assert response.proposal
