from __future__ import annotations

from iam_agent.config.settings import Settings
from iam_agent.infra.logging.redaction import redact_mapping
from iam_agent.tools.oci_tools import OciTools


class FakeOciClient:
    def list_compartments(self, **kwargs):  # noqa: ARG002
        return [{"id": "c1", "name": "root"}]

    def list_policies(self, **kwargs):  # noqa: ARG002
        return [{"id": "p1", "name": "policy1"}]

    def get_policy(self, **kwargs):  # noqa: ARG002
        return {"id": "p1", "name": "policy1"}


class PermissionErrorOciClient:
    def list_compartments(self, **kwargs):
        raise RuntimeError("permission denied for list_compartments")


def test_us2_permission_denied_is_reported() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..example")
    tools = OciTools(client=PermissionErrorOciClient(), settings=settings)
    response = tools.list_compartments({})

    assert response.status == "error"
    assert response.errors is not None
    assert response.errors[0].code == "permission_denied"


class NotAuthorizedOciClient:
    def list_compartments(self, **kwargs):
        raise RuntimeError("Authorization failed or requested resource not found. NotAuthorizedOrNotFound")


def test_us2_notauthorized_error_is_reported_as_permission_denied() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..example")
    tools = OciTools(client=NotAuthorizedOciClient(), settings=settings)
    response = tools.list_compartments({})

    assert response.status == "error"
    assert response.errors is not None
    assert response.errors[0].code == "permission_denied"


def test_us2_secret_values_are_redacted() -> None:
    payload = {"api_key": "secret", "nested": {"client_secret": "abc", "normal": "ok"}}
    redacted = redact_mapping(payload)
    assert redacted["api_key"] == "***REDACTED***"
    assert redacted["nested"]["client_secret"] == "***REDACTED***"
    assert redacted["nested"]["normal"] == "ok"


class DuplicatePolicyNameClient:
    def list_policies(self, **kwargs):
        return [
            {"id": "p1", "name": "devday-iamagent", "compartment_id": "c1"},
            {"id": "p2", "name": "devday-iamagent", "compartment_id": "c2"},
        ]

    def get_policy(self, **kwargs):
        raise AssertionError("候補が複数のため get_policy は呼ばれない想定")


def test_us2_get_policy_by_name_returns_needs_confirmation_when_ambiguous() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..example")
    tools = OciTools(client=DuplicatePolicyNameClient(), settings=settings)
    response = tools.get_policy({"policy_name": "devday-iamagent"})

    assert response.status == "needs_confirmation"
    assert response.data is not None
    assert len(response.data["candidates"]) == 2


class FakeResourceSearchClient:
    def list_resources(self, *, compartment_id: str, resource_type: str = "", limit: int = 200):  # noqa: ARG002
        items = [
            {
                "identifier": "ocid1.instance.oc1..regression",
                "display_name": "regression-instance",
                "resource_type": "Instance",
                "compartment_id": "ocid1.compartment.oc1..example",
                "lifecycle_state": "RUNNING",
            }
        ]
        if resource_type:
            lowered = resource_type.lower()
            items = [item for item in items if str(item.get("resource_type", "")).lower() == lowered]
        return items[:limit]


def test_us2_reference_reads_regression_after_resource_extension() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..example")
    tools = OciTools(
        client=FakeOciClient(),
        settings=settings,
        resource_search_client=FakeResourceSearchClient(),
    )

    compartments = tools.list_compartments({})
    policies = tools.list_policies({})
    policy = tools.get_policy({"policy_name": "policy1"})
    resources = tools.list_resources({"limit": 1})

    assert compartments.status == "success"
    assert policies.status == "success"
    assert policy.status == "success"
    assert resources.status == "success"
    assert resources.data is not None
    assert resources.data["returned_count"] == 1


def test_us2_reference_reads_are_unchanged_with_a2a_context() -> None:
    settings = Settings(compartment_ocid="ocid1.compartment.oc1..example")
    tools = OciTools(
        client=FakeOciClient(),
        settings=settings,
        resource_search_client=FakeResourceSearchClient(),
    )

    a2a_context = {
        "__a2a_context": {
            "source_agent_id": "peer-1",
            "correlation_id": "corr-1",
            "request_id": "req-1",
            "idempotency_key": "",
        }
    }
    compartments = tools.list_compartments(a2a_context)
    policies = tools.list_policies(a2a_context)
    policy = tools.get_policy({"policy_name": "policy1", **a2a_context})
    resources = tools.list_resources({"limit": 1, **a2a_context})

    assert compartments.status == "success"
    assert policies.status == "success"
    assert policy.status == "success"
    assert resources.status == "success"
