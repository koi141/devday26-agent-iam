from __future__ import annotations

from iam_agent.application.permission_investigator import PermissionInvestigator
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse


def test_us1_hr_complement_is_used_when_oci_not_resolved() -> None:
    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"users": [{"id": "u-hanako", "userName": "hanako.suzuki@example.com", "displayName": "Hanako Suzuki"}]},
            audit=AuditPayload(result="success"),
        ),
        "query_hr_database": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={
                "candidates": [
                    {
                        "emp_id": 101,
                        "first_name": "Hanako",
                        "last_name": "Suzuki",
                        "email": "hanako.suzuki@example.com",
                        "first_name_kanji": "花子",
                        "last_name_kanji": "鈴木",
                    }
                ],
                "candidate_count": 1,
            },
            audit=AuditPayload(result="success"),
        ),
        "get_user": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={
                "user": {
                    "id": payload["user_id"],
                    "displayName": "鈴木 花子",
                    "userName": "hanako.suzuki@example.com",
                    "groups": [{"display": "Domain_Administrators"}],
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
            data={"policies": [{"id": "p1", "name": "policy1", "statements": ["Allow group Domain_Administrators to read all-resources in tenancy"]}]},
            audit=AuditPayload(result="success"),
        ),
        "get_last_successful_login": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"last_successful_login_at": "2026-04-19T00:00:00Z"},
            audit=AuditPayload(result="success"),
        ),
    }
    investigator = PermissionInvestigator(skill_executor=SkillExecutor(handlers=handlers))
    response = investigator.investigate(turn_id="t1", user_input="鈴木さんは何ができますか？")

    assert response.status == "success"
    assert response.data is not None
    assert response.data["user_resolution"]["status"] == "resolved"


def test_us1_ambiguous_user_requires_confirmation() -> None:
    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={
                "users": [
                    {"id": "u1", "userName": "yamada1@example.com", "displayName": "山田 太郎"},
                    {"id": "u2", "userName": "yamada2@example.com", "displayName": "山田 次郎"},
                ]
            },
            audit=AuditPayload(result="success"),
        ),
        "query_hr_database": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"candidates": [], "candidate_count": 0},
            audit=AuditPayload(result="success"),
        ),
    }
    investigator = PermissionInvestigator(skill_executor=SkillExecutor(handlers=handlers))
    response = investigator.investigate(turn_id="t2", user_input="山田さんの権限を確認")
    assert response.status == "needs_confirmation"


def test_us1_fallbacks_to_get_user_with_selector_when_hr_candidate_has_no_direct_user_id() -> None:
    captured_payload: dict[str, object] = {}

    def get_user_handler(payload: dict[str, object]) -> NormalizedResponse:
        captured_payload.update(payload)
        return NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={
                "user": {
                    "id": "u-kato",
                    "displayName": "Ichiro Kato",
                    "userName": "ikato",
                    "groups": [{"display": "DevOps"}],
                    "emails": [{"primary": True, "value": "ichiro.kato@example.com"}],
                }
            },
            audit=AuditPayload(result="success"),
        )

    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"users": [{"id": "u-kato", "userName": "ikato", "displayName": "Ichiro Kato"}]},
            audit=AuditPayload(result="success"),
        ),
        "query_hr_database": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={
                "candidates": [
                    {
                        "emp_id": 201,
                        "first_name": "Ichiro",
                        "last_name": "Kato",
                        "email": "ichiro.kato@example.com",
                        "first_name_kanji": "一郎",
                        "last_name_kanji": "加藤",
                    }
                ]
            },
            audit=AuditPayload(result="success"),
        ),
        "get_user": get_user_handler,
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
            data={"policies": [{"id": "p1", "name": "policy1", "statements": ["Allow group DevOps to use all-resources in tenancy"]}]},
            audit=AuditPayload(result="success"),
        ),
        "get_last_successful_login": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"last_successful_login_at": "2026-04-19T00:00:00Z"},
            audit=AuditPayload(result="success"),
        ),
    }

    investigator = PermissionInvestigator(skill_executor=SkillExecutor(handlers=handlers))
    response = investigator.investigate(turn_id="t3", user_input="加藤さんはどの操作が許可されていますか？")

    assert response.status == "success"
    assert captured_payload.get("user_selector")
    assert isinstance(captured_payload.get("user_selector"), dict)
    selector = captured_payload["user_selector"]
    assert isinstance(selector, dict)
    assert selector.get("family_name_kanji") == "加藤"


def test_us1_permission_investigation_resolves_by_username_token() -> None:
    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={
                "users": [
                    {
                        "id": "u-iam-agent",
                        "userName": "IAM_Agent",
                        "displayName": "IAM Agent",
                        "groups": [{"display": "Domain_Administrators"}],
                    }
                ]
            },
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
                    "id": payload.get("user_id", "u-iam-agent"),
                    "displayName": "IAM Agent",
                    "userName": "IAM_Agent",
                    "groups": [{"display": "Domain_Administrators"}],
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
            data={
                "policies": [
                    {
                        "id": "p1",
                        "name": "policy1",
                        "statements": ["Allow group Domain_Administrators to manage all-resources in tenancy"],
                    }
                ]
            },
            audit=AuditPayload(result="success"),
        ),
        "get_last_successful_login": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"last_successful_login_at": "2026-04-19T00:00:00Z"},
            audit=AuditPayload(result="success"),
        ),
    }
    investigator = PermissionInvestigator(skill_executor=SkillExecutor(handlers=handlers))
    response = investigator.investigate(turn_id="t-iam-agent", user_input="IAM_Agentはどのような操作を許可されていますか？")

    assert response.status == "success"
    assert response.data is not None
    resolution = response.data.get("user_resolution", {})
    assert isinstance(resolution, dict)
    selected = resolution.get("selected_user", {})
    assert isinstance(selected, dict)
    assert selected.get("oci_user_id") == "u-iam-agent"


def test_us1_permission_investigation_matches_domain_qualified_group_policy() -> None:
    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={
                "users": [
                    {
                        "id": "u-iam-agent",
                        "userName": "IAM_Agent",
                        "displayName": "IAM Agent",
                        "groups": [{"display": "Agents"}],
                    }
                ]
            },
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
                    "id": payload.get("user_id", "u-iam-agent"),
                    "displayName": "IAM Agent",
                    "userName": "IAM_Agent",
                    "groups": [{"display": "Agents"}],
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
            data={
                "policies": [
                    {
                        "id": "p-devday-iamagent",
                        "name": "devday-iamagent",
                        "statements": [
                            "Allow group 'devday-iddomain'/'agents' to manage instance-family in compartment devday26"
                        ],
                    }
                ]
            },
            audit=AuditPayload(result="success"),
        ),
        "get_last_successful_login": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"last_successful_login_at": "2026-04-19T00:00:00Z"},
            audit=AuditPayload(result="success"),
        ),
    }
    investigator = PermissionInvestigator(skill_executor=SkillExecutor(handlers=handlers))
    response = investigator.investigate(turn_id="t4", user_input="IAM_Agentはどのような操作を許可されていますか？")

    assert response.status == "success"
    assert response.data is not None
    policy_evidence = response.data.get("policy_evidence")
    assert isinstance(policy_evidence, list)
    assert len(policy_evidence) == 1
    first = policy_evidence[0]
    assert isinstance(first, dict)
    assert first.get("policy_name") == "devday-iamagent"
    assert first.get("matched_groups") == ["Agents"]


def test_us1_permission_investigation_outputs_concrete_statement_explanations() -> None:
    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={
                "users": [
                    {
                        "id": "u-iam-agent",
                        "userName": "IAM_Agent",
                        "displayName": "IAM Agent",
                        "groups": [{"display": "Agents"}],
                    }
                ]
            },
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
                    "id": payload.get("user_id", "u-iam-agent"),
                    "displayName": "IAM Agent",
                    "userName": "IAM_Agent",
                    "groups": [{"display": "Agents"}],
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
            data={
                "policies": [
                    {
                        "id": "p-devday-iamagent",
                        "name": "devday-iamagent",
                        "statements": [
                            "Allow group 'devday-iddomain'/'agents' to manage instance-family in compartment devday26",
                            "Allow group 'devday-iddomain'/'agents' to use virtual-network-family in compartment devday26",
                        ],
                    }
                ]
            },
            audit=AuditPayload(result="success"),
        ),
        "get_last_successful_login": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"last_successful_login_at": "2026-04-19T00:00:00Z"},
            audit=AuditPayload(result="success"),
        ),
    }
    investigator = PermissionInvestigator(skill_executor=SkillExecutor(handlers=handlers))
    response = investigator.investigate(turn_id="t5", user_input="IAM_Agentはどのような操作を許可されていますか？")

    assert response.status == "success"
    assert any("一致ステートメント抜粋" in line for line in response.facts)
    assert any("Allow group 'devday-iddomain'/'agents' to manage instance-family in compartment devday26" in line for line in response.facts)
    assert any("`manage` は" in line and "instance-family" in line for line in response.interpretation)
    assert any("`use` は" in line and "virtual-network-family" in line for line in response.interpretation)
