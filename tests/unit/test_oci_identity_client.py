from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from iam_agent.infra.auth.workload_identity import OciAuthContext
import iam_agent.infra.clients.oci_identity_client as oci_client_module
from iam_agent.infra.clients.oci_identity_client import OciIdentityClient


@dataclass
class _DictItem:
    payload: dict[str, str]

    def to_dict(self) -> dict[str, str]:
        return dict(self.payload)


class _DummyIdentityClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls: list[tuple[str, bool]] = []

    def list_compartments(
        self,
        *,
        compartment_id: str,
        compartment_id_in_subtree: bool,
        access_level: str,  # noqa: ARG002 - signature compatibility
    ):
        self.calls.append((compartment_id, compartment_id_in_subtree))
        if compartment_id_in_subtree:
            raise RuntimeError("Invalid parameter 'compartmentId must be tenancy ocid'")

        children = {
            "c-root": [
                {"id": "c-child-1", "name": "child-1", "compartment_id": "c-root", "lifecycle_state": "ACTIVE"},
                {"id": "c-child-2", "name": "child-2", "compartment_id": "c-root", "lifecycle_state": "DELETED"},
            ],
            "c-child-1": [
                {"id": "c-grand-1", "name": "grand-1", "compartment_id": "c-child-1", "lifecycle_state": "INACTIVE"}
            ],
            "c-child-2": [],
            "c-grand-1": [],
        }.get(compartment_id, [])
        return SimpleNamespace(data=[_DictItem(item) for item in children])

    def get_compartment(self, compartment_id: str):
        return SimpleNamespace(data=_DictItem({"id": compartment_id, "name": "root", "lifecycle_state": "ACTIVE"}))


class _PolicyLike:
    attribute_map = {"id": "id", "name": "name"}

    def __init__(self, policy_id: str, name: str) -> None:
        self.id = policy_id
        self.name = name


class _PolicyIdentityClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def list_policies(self, *, compartment_id: str):  # noqa: ARG002 - signature compatibility
        return SimpleNamespace(data=[_PolicyLike("p1", "policy1")])

    def get_policy(self, policy_id: str):
        return SimpleNamespace(data=_PolicyLike(policy_id, "policy1"))


def test_local_profile_constructor_omits_signer_when_none(monkeypatch) -> None:
    holder: dict[str, _DummyIdentityClient] = {}

    def _factory(**kwargs):
        client = _DummyIdentityClient(**kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(oci_client_module.oci.identity, "IdentityClient", _factory)

    auth = OciAuthContext(config={"region": "ap-tokyo-1"}, signer=None, profile="devdey-agent")
    OciIdentityClient(auth)

    assert "client" in holder
    assert "signer" not in holder["client"].kwargs


def test_constructor_passes_signer_when_present(monkeypatch) -> None:
    holder: dict[str, _DummyIdentityClient] = {}

    def _factory(**kwargs):
        client = _DummyIdentityClient(**kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(oci_client_module.oci.identity, "IdentityClient", _factory)

    signer = object()
    auth = OciAuthContext(config={"region": "ap-tokyo-1"}, signer=signer, profile="workload_identity")
    OciIdentityClient(auth)

    assert holder["client"].kwargs["signer"] is signer


def test_list_compartments_fallbacks_to_recursive_when_non_tenancy_subtree(monkeypatch) -> None:
    holder: dict[str, _DummyIdentityClient] = {}

    def _factory(**kwargs):
        client = _DummyIdentityClient(**kwargs)
        holder["client"] = client
        return client

    def _all_results(func, **kwargs):
        return func(**kwargs)

    monkeypatch.setattr(oci_client_module.oci.identity, "IdentityClient", _factory)
    monkeypatch.setattr(oci_client_module.oci.pagination, "list_call_get_all_results", _all_results)

    auth = OciAuthContext(config={"region": "ap-tokyo-1"}, signer=object(), profile="workload_identity")
    client = OciIdentityClient(auth)

    compartments = client.list_compartments(
        compartment_id="c-root",
        include_subtree=True,
        access_level="ANY",
        include_inactive=True,
    )
    ids = [item["id"] for item in compartments]

    assert ids == ["c-root", "c-child-1", "c-child-2", "c-grand-1"]
    assert holder["client"].calls[0] == ("c-root", True)


def test_list_compartments_applies_max_depth_and_inactive_filter(monkeypatch) -> None:
    def _factory(**kwargs):
        return _DummyIdentityClient(**kwargs)

    def _all_results(func, **kwargs):
        return func(**kwargs)

    monkeypatch.setattr(oci_client_module.oci.identity, "IdentityClient", _factory)
    monkeypatch.setattr(oci_client_module.oci.pagination, "list_call_get_all_results", _all_results)

    auth = OciAuthContext(config={"region": "ap-tokyo-1"}, signer=object(), profile="workload_identity")
    client = OciIdentityClient(auth)

    compartments = client.list_compartments(
        compartment_id="c-root",
        include_subtree=True,
        access_level="ANY",
        include_inactive=False,
        max_depth=1,
    )

    ids = [item["id"] for item in compartments]
    assert ids == ["c-root", "c-child-1"]
    assert all(int(item.get("_depth", 0)) <= 1 for item in compartments)


def test_policy_serialization_supports_models_without_to_dict(monkeypatch) -> None:
    monkeypatch.setattr(oci_client_module.oci.identity, "IdentityClient", lambda **kwargs: _PolicyIdentityClient(**kwargs))

    auth = OciAuthContext(config={"region": "ap-tokyo-1"}, signer=object(), profile="workload_identity")
    client = OciIdentityClient(auth)

    policies = client.list_policies(compartment_id="c-root", include_subtree=False)
    policy = client.get_policy(policy_id="p1")

    assert policies[0]["id"] == "p1"
    assert policies[0]["name"] == "policy1"
    assert policy["id"] == "p1"
