from __future__ import annotations

from iam_agent.config.settings import Settings
from iam_agent.infra.logging.redaction import redact_mapping
from iam_agent.tools.oci_tools import OciTools


class _FakeCompartmentClient:
    def list_compartments(
        self,
        *,
        compartment_id: str,  # noqa: ARG002
        include_subtree: bool = True,  # noqa: ARG002
        access_level: str = "ANY",  # noqa: ARG002
        include_inactive: bool = False,  # noqa: ARG002
        max_depth: int | None = None,  # noqa: ARG002
    ):
        return [
            {
                "id": "ocid1.compartment.oc1..root",
                "name": "devday26",
                "compartment_id": "ocid1.tenancy.oc1..example",
                "lifecycle_state": "ACTIVE",
                "_depth": 0,
            }
        ]


class _FakeResourceSearchClient:
    def list_resources(self, *, compartment_id: str, resource_type: str = "", limit: int = 200):  # noqa: ARG002
        return [
            {
                "identifier": "ocid1.instance.oc1..aaaa",
                "display_name": "vm-redaction-test",
                "resource_type": "Instance",
                "compartment_id": "ocid1.compartment.oc1..root",
                "lifecycle_state": "RUNNING",
                "api_key": "very-secret",
                "client_secret": "never-expose",
            }
        ][:limit]


def test_list_resources_does_not_expose_sensitive_fields() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..root")
    tools = OciTools(
        client=_FakeCompartmentClient(),
        settings=settings,
        resource_search_client=_FakeResourceSearchClient(),
    )

    response = tools.list_resources({})

    assert response.status == "success"
    assert response.data is not None
    first = response.data["resources"][0]
    assert "api_key" not in first
    assert "client_secret" not in first


def test_redact_mapping_masks_sensitive_keys_in_nested_payload() -> None:
    payload = {
        "resources": [{"display_name": "safe", "token": "abc"}],
        "audit": {"authorization": "Bearer XYZ", "normal": "ok"},
    }

    redacted = redact_mapping(payload)

    assert redacted["resources"][0]["token"] == "***REDACTED***"
    assert redacted["audit"]["authorization"] == "***REDACTED***"
    assert redacted["audit"]["normal"] == "ok"
