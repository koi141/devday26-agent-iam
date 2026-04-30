from __future__ import annotations

from types import SimpleNamespace

from iam_agent.application.errors import PermissionDeniedError
from iam_agent.infra.auth.workload_identity import OciAuthContext
import iam_agent.infra.clients.oci_resource_search_client as search_module
from iam_agent.infra.clients.oci_resource_search_client import OciResourceSearchClient


class _SearchItem:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _DummySearchClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls: list[dict[str, object]] = []

    def search_resources(self, *, search_details, limit: int, page: str = ""):  # noqa: ANN001
        self.calls.append(
            {
                "query": getattr(search_details, "query", ""),
                "limit": limit,
                "page": page,
            }
        )

        page_key = page or "first"
        pages = {
            "first": (
                [{"identifier": "ocid1.instance.oc1..a", "display_name": "vm-a", "resource_type": "Instance"}],
                "p2",
            ),
            "p2": (
                [
                    {"identifier": "ocid1.vcn.oc1..b", "display_name": "vcn-b", "resource_type": "Vcn"},
                    {"identifier": "ocid1.volume.oc1..c", "display_name": "bv-c", "resource_type": "Volume"},
                ],
                "",
            ),
        }
        payload, next_page = pages[page_key]
        headers = {"opc-next-page": next_page} if next_page else {}
        return SimpleNamespace(
            data=SimpleNamespace(items=[_SearchItem(item) for item in payload]),
            headers=headers,
        )


class _PermissionErrorSearchClient:
    def __init__(self, **kwargs) -> None:  # noqa: D401, ANN003
        self.kwargs = kwargs

    def search_resources(self, **kwargs):  # noqa: ANN003
        raise RuntimeError("permission denied")


class _TransientThenSuccessSearchClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls = 0

    def search_resources(self, *, search_details, limit: int, page: str = ""):  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout while calling resource search")
        return SimpleNamespace(
            data=SimpleNamespace(
                items=[
                    _SearchItem(
                        {
                            "identifier": "ocid1.instance.oc1..retry",
                            "display_name": "vm-retry",
                            "resource_type": "Instance",
                        }
                    )
                ]
            ),
            headers={},
        )


def test_search_client_omits_signer_for_local_profile(monkeypatch) -> None:
    holder: dict[str, _DummySearchClient] = {}

    def _factory(**kwargs):
        client = _DummySearchClient(**kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(search_module.oci.resource_search, "ResourceSearchClient", _factory)

    auth = OciAuthContext(config={"region": "ap-tokyo-1"}, signer=None, profile="devdey-agent")
    OciResourceSearchClient(auth)

    assert "client" in holder
    assert "signer" not in holder["client"].kwargs


def test_search_client_builds_query_and_collects_pages(monkeypatch) -> None:
    holder: dict[str, _DummySearchClient] = {}

    def _factory(**kwargs):
        client = _DummySearchClient(**kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(search_module.oci.resource_search, "ResourceSearchClient", _factory)

    auth = OciAuthContext(config={"region": "ap-tokyo-1"}, signer=object(), profile="workload_identity")
    client = OciResourceSearchClient(auth)

    resources = client.list_resources(compartment_id="ocid1.compartment.oc1..root", resource_type="Instance", limit=3)

    assert len(resources) == 3
    assert resources[0]["identifier"] == "ocid1.instance.oc1..a"
    first_call = holder["client"].calls[0]
    assert "compartmentId = 'ocid1.compartment.oc1..root'" in str(first_call["query"])
    assert "resourceType = 'Instance'" in str(first_call["query"])
    assert holder["client"].calls[1]["page"] == "p2"


def test_search_client_raises_permission_denied(monkeypatch) -> None:
    monkeypatch.setattr(
        search_module.oci.resource_search,
        "ResourceSearchClient",
        lambda **kwargs: _PermissionErrorSearchClient(**kwargs),
    )

    auth = OciAuthContext(config={"region": "ap-tokyo-1"}, signer=object(), profile="workload_identity")
    client = OciResourceSearchClient(auth)

    try:
        client.list_resources(compartment_id="ocid1.compartment.oc1..root")
        assert False, "PermissionDeniedError が発生する想定"
    except PermissionDeniedError as exc:
        assert "list_resources 権限不足" in str(exc)


def test_search_client_retries_on_transient_error(monkeypatch) -> None:
    holder: dict[str, _TransientThenSuccessSearchClient] = {}

    def _factory(**kwargs):
        client = _TransientThenSuccessSearchClient(**kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(search_module.oci.resource_search, "ResourceSearchClient", _factory)

    auth = OciAuthContext(config={"region": "ap-tokyo-1"}, signer=object(), profile="workload_identity")
    client = OciResourceSearchClient(auth)
    resources = client.list_resources(compartment_id="ocid1.compartment.oc1..root", limit=1)

    assert len(resources) == 1
    assert resources[0]["identifier"] == "ocid1.instance.oc1..retry"
    assert holder["client"].calls == 2
