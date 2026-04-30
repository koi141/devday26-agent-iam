from __future__ import annotations

from iam_agent.config.settings import Settings
from iam_agent.tools.oci_tools import OciTools


class _FakeCompartmentClient:
    def list_compartments(
        self,
        *,
        compartment_id: str,  # noqa: ARG002
        include_subtree: bool = True,  # noqa: ARG002
        access_level: str = "ANY",  # noqa: ARG002
        include_inactive: bool = False,
        max_depth: int | None = None,
    ):
        items = [
            {
                "id": "ocid1.compartment.oc1..root",
                "name": "devday26",
                "compartment_id": "ocid1.tenancy.oc1..example",
                "lifecycle_state": "ACTIVE",
                "_depth": 0,
            },
            {
                "id": "ocid1.compartment.oc1..child1",
                "name": "child-1",
                "compartment_id": "ocid1.compartment.oc1..root",
                "lifecycle_state": "ACTIVE",
                "_depth": 1,
            },
            {
                "id": "ocid1.compartment.oc1..child2",
                "name": "child-2",
                "compartment_id": "ocid1.compartment.oc1..root",
                "lifecycle_state": "INACTIVE",
                "_depth": 1,
            },
        ]
        filtered = []
        for item in items:
            if not include_inactive and str(item.get("lifecycle_state")).upper() in {"INACTIVE", "DELETED"}:
                continue
            if max_depth is not None and int(item.get("_depth", 0)) > int(max_depth):
                continue
            filtered.append(item)
        return filtered


class _FakeResourceSearchClient:
    def list_resources(self, *, compartment_id: str, resource_type: str = "", limit: int = 200):
        dataset = {
            "ocid1.compartment.oc1..root": [
                {
                    "identifier": "ocid1.instance.oc1..aaaa",
                    "display_name": "vm-root-1",
                    "resource_type": "Instance",
                    "compartment_id": "ocid1.compartment.oc1..root",
                    "lifecycle_state": "RUNNING",
                    "region": "ap-tokyo-1",
                },
                {
                    "identifier": "ocid1.vcn.oc1..bbbb",
                    "display_name": "vcn-root-1",
                    "resource_type": "Vcn",
                    "compartment_id": "ocid1.compartment.oc1..root",
                    "lifecycle_state": "AVAILABLE",
                    "region": "ap-tokyo-1",
                },
            ],
            "ocid1.compartment.oc1..child1": [
                {
                    "identifier": "ocid1.volume.oc1..cccc",
                    "display_name": "bv-child-1",
                    "resource_type": "Volume",
                    "compartment_id": "ocid1.compartment.oc1..child1",
                    "lifecycle_state": "AVAILABLE",
                    "availability_domain": "kIdk:AP-TOKYO-1-AD-1",
                }
            ],
        }
        items = dataset.get(compartment_id, [])
        if resource_type:
            normalized = resource_type.lower()
            items = [item for item in items if str(item.get("resource_type", "")).lower() == normalized]
        return items[:limit]


class _FakePartialResourceSearchClient(_FakeResourceSearchClient):
    def list_resources(self, *, compartment_id: str, resource_type: str = "", limit: int = 200):
        if compartment_id == "ocid1.compartment.oc1..child2":
            raise RuntimeError("permission denied for resource search")
        return super().list_resources(compartment_id=compartment_id, resource_type=resource_type, limit=limit)


def test_list_compartments_contract_required_fields() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..root")
    tools = OciTools(client=_FakeCompartmentClient(), settings=settings)

    response = tools.list_compartments({})

    assert response.status == "success"
    assert response.data is not None
    assert response.data["output_format"] == "tree"
    assert response.data["root_compartment_ocid"] == "ocid1.compartment.oc1..root"
    assert "tree_lines" in response.data
    assert len(response.data["compartments"]) == 2
    required = {"name", "compartment_ocid", "parent_compartment_ocid", "lifecycle_state", "depth", "path"}
    assert required.issubset(set(response.data["compartments"][0].keys()))


def test_list_resources_contract_required_fields_and_default_scope() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..root")
    tools = OciTools(
        client=_FakeCompartmentClient(),
        settings=settings,
        resource_search_client=_FakeResourceSearchClient(),
    )

    response = tools.list_resources({})

    assert response.status == "success"
    assert response.data is not None
    assert response.data["target_compartment_ocid"] == "ocid1.compartment.oc1..root"
    assert response.data["include_subtree"] is False
    assert response.data["returned_count"] == 2
    first = response.data["resources"][0]
    required = {"display_name", "resource_type", "resource_ocid", "compartment_ocid", "lifecycle_state"}
    assert required.issubset(set(first.keys()))
    assert all(item["compartment_ocid"] == "ocid1.compartment.oc1..root" for item in response.data["resources"])


def test_list_resources_partial_visibility_contract() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..root")
    tools = OciTools(
        client=_FakeCompartmentClient(),
        settings=settings,
        resource_search_client=_FakePartialResourceSearchClient(),
    )

    response = tools.list_resources({"include_subtree": True})

    assert response.status == "success"
    assert response.data is not None
    assert response.meta is not None
    assert response.meta.get("partial_result") is True
    assert "visibility_warnings" in response.data
    assert len(response.data["visibility_warnings"]) >= 1
    assert "not_retrieved_resource_types" in response.data
