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
                }
            ],
            "ocid1.compartment.oc1..child1": [
                {
                    "identifier": "ocid1.volume.oc1..bbbb",
                    "display_name": "bv-child-1",
                    "resource_type": "Volume",
                    "compartment_id": "ocid1.compartment.oc1..child1",
                    "lifecycle_state": "AVAILABLE",
                }
            ],
            "ocid1.compartment.oc1..child2": [
                {
                    "identifier": "ocid1.bucket.oc1..cccc",
                    "display_name": "bucket-child-2",
                    "resource_type": "Bucket",
                    "compartment_id": "ocid1.compartment.oc1..child2",
                    "lifecycle_state": "ACTIVE",
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
            raise RuntimeError("permission denied for child2")
        return super().list_resources(compartment_id=compartment_id, resource_type=resource_type, limit=limit)


def test_list_compartments_tree_flow_default() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..root")
    tools = OciTools(client=_FakeCompartmentClient(), settings=settings)

    response = tools.list_compartments({})

    assert response.status == "success"
    assert response.data is not None
    assert response.data["output_format"] == "tree"
    assert "tree_lines" in response.data
    assert all("INACTIVE" not in line for line in response.data["tree_lines"])


def test_list_compartments_json_flow_with_include_inactive() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..root")
    tools = OciTools(client=_FakeCompartmentClient(), settings=settings)

    response = tools.list_compartments({"include_inactive": True, "output_format": "json"})

    assert response.status == "success"
    assert response.data is not None
    assert response.data["output_format"] == "json"
    assert "tree_lines" not in response.data
    assert len(response.data["compartments"]) == 3


def test_list_resources_include_subtree_changes_target_scope() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..root")
    tools = OciTools(
        client=_FakeCompartmentClient(),
        settings=settings,
        resource_search_client=_FakeResourceSearchClient(),
    )

    direct = tools.list_resources({})
    recursive = tools.list_resources({"include_subtree": True})

    assert direct.status == "success"
    assert recursive.status == "success"
    assert direct.data is not None
    assert recursive.data is not None
    assert direct.data["returned_count"] == 1
    assert recursive.data["returned_count"] == 3


def test_list_resources_partial_flow_when_permission_gap() -> None:
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
    assert len(response.data.get("resources", [])) >= 1
    warnings = response.data.get("visibility_warnings", [])
    assert isinstance(warnings, list) and len(warnings) >= 1
