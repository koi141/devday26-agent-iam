from __future__ import annotations

from iam_agent.config.settings import Settings
from iam_agent.tools.identity_domain_tools import IdentityDomainTools
from iam_agent.tools.oci_tools import OciTools


class FakeIdentityClientUS2:
    def list_auth_tokens(self, **kwargs):
        return {"Resources": [{"id": "t1"}]}

    def list_api_keys(self, **kwargs):
        return {"Resources": [{"id": "k1"}, {"id": "k2"}]}

    def get_user(self, user_id: str, **kwargs):
        return {
            "id": user_id,
            "urn:ietf:params:scim:schemas:oracle:idcs:extension:userState:User:lastSuccessfulLoginDate": "2026-04-17T10:00:00Z",
        }

    def list_users(self, **kwargs):
        return {"Resources": [{"id": "u1"}], "totalResults": 1}


class FakeOciClient:
    def list_compartments(self, **kwargs):
        return [{"id": "c1", "name": "root"}]

    def list_policies(self, **kwargs):
        return [{"id": "p1", "name": "policy1"}]

    def get_policy(self, **kwargs):
        return {"id": "p1", "name": "policy1"}


def test_us2_list_user_credentials_contract() -> None:
    tools = IdentityDomainTools(client=FakeIdentityClientUS2(), hr_tools=None)
    response = tools.list_user_credentials({"user_id": "u1"})
    assert response.status == "success"
    assert response.data is not None
    assert response.data["credential_count"] == 3


def test_us2_get_last_successful_login_contract() -> None:
    tools = IdentityDomainTools(client=FakeIdentityClientUS2(), hr_tools=None)
    response = tools.get_last_successful_login({"user_selector": {"id": "u1"}})
    assert response.status == "success"
    assert response.data is not None
    assert response.data["user_id"] == "u1"


def test_us2_oci_reference_contract() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..example")
    tools = OciTools(client=FakeOciClient(), settings=settings)
    response = tools.list_compartments({})
    assert response.status == "success"
    assert response.data is not None
    assert len(response.data["compartments"]) == 1


def test_us2_get_policy_resolves_policy_name_to_policy_id() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..example")
    tools = OciTools(client=FakeOciClient(), settings=settings)
    response = tools.get_policy({"policy_name": "policy1"})

    assert response.status == "success"
    assert response.data is not None
    assert response.data["policy"]["id"] == "p1"
    assert response.data["resolved_from_name"] is True
