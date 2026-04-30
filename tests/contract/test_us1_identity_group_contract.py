from __future__ import annotations

from iam_agent.tools.identity_domain_tools import IdentityDomainTools


class FakeIdentityClientUS1:
    def __init__(self) -> None:
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


class FakeHrTools:
    def query_hr_database(self, payload):
        raise AssertionError("US1では呼ばれない想定")


def test_us1_list_users_contract() -> None:
    tools = IdentityDomainTools(client=FakeIdentityClientUS1(), hr_tools=FakeHrTools())
    response = tools.list_users({"count": 10})

    assert response.status == "success"
    assert response.data is not None
    assert "users" in response.data


def test_us1_add_user_to_group_contract_success() -> None:
    client = FakeIdentityClientUS1()
    tools = IdentityDomainTools(client=client, hr_tools=FakeHrTools())

    response = tools.add_user_to_group(
        {
            "user_selector": {"id": "u1"},
            "group_selector": {"id": "g1"},
        }
    )

    assert response.status == "success"
    assert client.last_patch is not None
    assert client.last_patch[0] == "g1"


def test_us1_remove_user_to_group_needs_confirmation_when_ambiguous() -> None:
    client = FakeIdentityClientUS1()
    client.users = [
        {"id": "u1", "userName": "alice@example.com"},
        {"id": "u2", "userName": "alice@example.com"},
    ]
    tools = IdentityDomainTools(client=client, hr_tools=FakeHrTools())

    response = tools.remove_user_from_group({"user_selector": {}, "group_selector": {"id": "g1"}})
    assert response.status == "needs_confirmation"
