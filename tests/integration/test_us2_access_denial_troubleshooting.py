from __future__ import annotations

from iam_agent.application.access_diagnoser import AccessDiagnoser
from iam_agent.application.permission_investigator import PermissionInvestigator
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse


def _build_handlers_with_missing_policy() -> dict:
    return {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"users": [{"id": "u1", "userName": "kato@example.com", "displayName": "加藤 一郎", "groups": [{"display": "DevOps"}]}]},
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
            data={"user": {"id": "u1", "userName": "kato@example.com", "displayName": "加藤 一郎", "groups": [{"display": "DevOps"}]}},
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
            data={"policies": [{"id": "p1", "name": "basic", "statements": ["Allow group DevOps to inspect buckets in tenancy"]}]},
            audit=AuditPayload(result="success"),
        ),
        "get_last_successful_login": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"last_successful_login_at": ""},
            audit=AuditPayload(result="success"),
        ),
    }


def test_us2_returns_confirmed_or_hypothesis_findings() -> None:
    investigator = PermissionInvestigator(skill_executor=SkillExecutor(handlers=_build_handlers_with_missing_policy()))
    diagnoser = AccessDiagnoser(permission_investigator=investigator)
    response = diagnoser.diagnose(
        turn_id="t1",
        user_input="加藤さんが「開発環境のAutonomous Database」にcreate操作できません。原因は？",
    )
    assert response.status == "success"
    assert response.data is not None
    findings = response.data["findings"]
    assert any(item["status"] in {"confirmed", "hypothesis"} for item in findings)


def test_us2_requires_additional_input_when_required_fields_missing() -> None:
    investigator = PermissionInvestigator(skill_executor=SkillExecutor(handlers=_build_handlers_with_missing_policy()))
    diagnoser = AccessDiagnoser(permission_investigator=investigator)
    response = diagnoser.diagnose(turn_id="t2", user_input="山田さんが拒否されました")
    assert response.status == "needs_confirmation"
    assert response.data is not None
    assert "missing_fields" in response.data
