from __future__ import annotations

from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.tools.identity_domain_tools import IdentityDomainTools


class FakeIdentityClient:
    def __init__(self) -> None:
        self.last_list_users_kwargs = {}

    def list_users(self, **kwargs):
        self.last_list_users_kwargs = kwargs
        return {
            "Resources": [
                {
                    "id": "u1",
                    "displayName": "加藤",
                    "userName": "kato@example.com",
                    "emails": [{"value": "kato@example.com", "primary": True}],
                }
            ]
        }

    def get_user(self, user_id, *, attributes=None):  # noqa: ARG002
        raise AssertionError("get_user should not be called when user_id is missing")


class FakeHrTools:
    def __init__(self) -> None:
        self.called = False
        self.last_payload = {}

    def query_hr_database(self, payload):
        self.called = True
        self.last_payload = payload
        return NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={
                "candidates": [
                    {
                        "email": "kato@example.com",
                        "first_name": "Taro",
                        "last_name": "Kato",
                        "first_name_kanji": "太郎",
                        "last_name_kanji": "加藤",
                    }
                ]
            },
            audit=AuditPayload(result="success"),
        )


def test_get_user_resolves_by_list_users_when_user_id_missing() -> None:
    client = FakeIdentityClient()
    tools = IdentityDomainTools(client=client, hr_tools=None)

    response = tools.get_user({"name": "加藤"})

    assert response.status == "success"
    assert response.data is not None
    assert response.data["user"]["id"] == "u1"
    assert 'displayName eq "加藤"' in str(client.last_list_users_kwargs.get("filter_expr") or "")


def test_get_user_uses_hr_and_then_list_users_when_user_id_missing() -> None:
    client = FakeIdentityClient()
    hr_tools = FakeHrTools()
    tools = IdentityDomainTools(client=client, hr_tools=hr_tools)

    response = tools.get_user({"name": "加藤さん"})

    assert response.status == "success"
    assert hr_tools.called is True
    assert hr_tools.last_payload.get("last_name_kanji") == "加藤"
    assert 'userName eq "kato@example.com"' in str(client.last_list_users_kwargs.get("filter_expr") or "")
