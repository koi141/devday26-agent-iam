from __future__ import annotations

from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.tools.identity_domain_tools import IdentityDomainTools


class FakeIdentityClientIntegration:
    def __init__(self):
        self.users = [{"id": "u1", "userName": "alice@example.com"}]
        self.groups = [{"id": "g1", "displayName": "Admins"}]
        self.last_patch: tuple[str, list[dict]] | None = None

    def list_users(self, **kwargs):
        return {"Resources": self.users, "totalResults": len(self.users)}

    def get_user(self, user_id: str, **kwargs):
        return {"id": user_id, "userName": "alice@example.com"}

    def list_groups(self, **kwargs):
        return {"Resources": self.groups, "totalResults": len(self.groups)}

    def get_group(self, group_id: str, **kwargs):
        return {"id": group_id, "displayName": "Admins"}

    def patch_group_membership(self, group_id: str, operations: list[dict]):
        self.last_patch = (group_id, operations)
        return None


class FakeHrTools:
    def query_hr_database(self, payload):
        raise AssertionError("US1 integrationでは呼ばれない")


class FakeHrToolsLookup:
    def __init__(self):
        self.last_payload = None

    def query_hr_database(self, payload):
        self.last_payload = payload
        return NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={
                "candidates": [
                    {
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
        )


def test_us1_execute_add_group_membership_with_executor() -> None:
    tools = IdentityDomainTools(client=FakeIdentityClientIntegration(), hr_tools=FakeHrTools())
    executor = SkillExecutor({"add_user_to_group": tools.add_user_to_group})

    result = executor.execute(
        "add_user_to_group",
        {"user_selector": {"id": "u1"}, "group_selector": {"id": "g1"}},
    )
    assert result.status == "success"


def test_us1_execute_needs_confirmation_with_executor() -> None:
    client = FakeIdentityClientIntegration()
    client.users = [{"id": "u1"}, {"id": "u2"}]
    tools = IdentityDomainTools(client=client, hr_tools=FakeHrTools())
    executor = SkillExecutor({"remove_user_from_group": tools.remove_user_from_group})

    result = executor.execute(
        "remove_user_from_group",
        {"user_selector": {}, "group_selector": {"id": "g1"}},
    )
    assert result.status == "needs_confirmation"


def test_us1_add_user_to_group_resolves_user_selector_via_hr_lookup() -> None:
    client = FakeIdentityClientIntegration()
    client.users = [{"id": "u-hanako", "userName": "hanako.suzuki@example.com"}]
    hr_tools = FakeHrToolsLookup()
    tools = IdentityDomainTools(client=client, hr_tools=hr_tools)

    result = tools.add_user_to_group(
        {
            "user_selector": {"family_name_kanji": "鈴木", "name": "鈴木"},
            "group_selector": {"display_name": "Admins"},
        }
    )

    assert result.status == "success"
    assert hr_tools.last_payload == {"last_name_kanji": "鈴木"}
    assert client.last_patch is not None
    assert client.last_patch[0] == "g1"
    assert client.last_patch[1][0]["value"][0]["value"] == "u-hanako"
