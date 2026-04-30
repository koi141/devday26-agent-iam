from __future__ import annotations

from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.tools.identity_domain_tools import IdentityDomainTools


class FakeIdentityClientUS3:
    def create_user(self, payload):
        return {"id": "u-created", "userName": payload["userName"]}


class FakeHrTools:
    def __init__(self, candidates):
        self.candidates = candidates

    def query_hr_database(self, payload):
        return NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={"candidates": self.candidates, "candidate_count": len(self.candidates)},
            audit=AuditPayload(result="success"),
        )


def test_us3_create_user_contract_success() -> None:
    tools = IdentityDomainTools(client=FakeIdentityClientUS3(), hr_tools=FakeHrTools([]))
    response = tools.create_user(
        {
            "family_name": "Yamada",
            "given_name": "Taro",
            "email": "taro@example.com",
            "username": "taro@example.com",
        }
    )
    assert response.status == "success"
    assert response.data is not None
    assert response.data["created_user"]["id"] == "u-created"


def test_us3_create_user_needs_confirmation_on_multiple_hr_candidates() -> None:
    hr_candidates = [{"first_name": "Taro"}, {"first_name": "Jiro"}]
    tools = IdentityDomainTools(client=FakeIdentityClientUS3(), hr_tools=FakeHrTools(hr_candidates))
    response = tools.create_user({"email": "taro@example.com"})
    assert response.status == "needs_confirmation"
