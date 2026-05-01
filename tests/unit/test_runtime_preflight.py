from __future__ import annotations

from iam_agent.application.runtime_preflight import run_runtime_preflight
from iam_agent.config.runtime_contract import EXPECTED_GENAI_PROJECT_ID, EXPECTED_INGRESS_HOST, EXPECTED_NAMESPACE
from iam_agent.config.settings import Settings


def _base_settings() -> Settings:
    return Settings(
        domain_url="https://example.identity.oraclecloud.com",
        domain_client_id="client-id",
        domain_client_secret="client-secret",
        domain_scope="urn:opc:idm:__myscopes__",
        token_url="https://example.identity.oraclecloud.com/oauth2/v1/token",
        compartment_ocid="ocid1.compartment.oc1..example",
        genai_baseurl="https://inference.generativeai.ap-osaka-1.oci.oraclecloud.com",
        genai_project="iam",
        genai_project_id=EXPECTED_GENAI_PROJECT_ID,
        genai_api_key="genai-api-key",
        langfuse_host="https://langfuse.devday26.sogawa-yk.com",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        langfuse_org_id="org",
        langfuse_project_id="proj",
        hr_database_user="hr",
        hr_database_pass="pass",
        hr_database_connectstr="dbhost/service",
        runtime_namespace=EXPECTED_NAMESPACE,
        runtime_ingress_host=EXPECTED_INGRESS_HOST,
    )


def test_runtime_preflight_success_when_required_entries_are_present() -> None:
    result = run_runtime_preflight(_base_settings())
    assert result.is_ok() is True
    assert result.snapshot.missing_keys == []
    assert result.binding is not None
    assert result.binding.consistency_status == "matched"


def test_runtime_preflight_distinguishes_missing_resource_and_missing_key() -> None:
    settings = _base_settings()
    settings.domain_client_id = ""
    settings.domain_client_secret = ""
    settings.domain_scope = ""
    settings.token_url = ""
    settings.hr_database_pass = ""

    result = run_runtime_preflight(settings)
    categories = {(issue.category, issue.target) for issue in result.issues}

    assert ("missing_resource", "secret/domain-client-credential") in categories
    assert ("missing_key", "secret/iam-agent-runtime-config:hr_database_pass") in categories


def test_runtime_preflight_detects_invalid_namespace_and_ingress() -> None:
    settings = _base_settings()
    settings.runtime_namespace = "agents"
    settings.runtime_ingress_host = "agent.koin3z.com"

    result = run_runtime_preflight(settings)
    categories = {(issue.category, issue.target) for issue in result.issues}

    assert ("invalid_value", "runtime_namespace") in categories
    assert ("invalid_value", "runtime_ingress_host") in categories


def test_runtime_preflight_detects_inconsistent_genai_pair() -> None:
    settings = _base_settings()
    settings.genai_project_id = ""

    result = run_runtime_preflight(settings)
    categories = {(issue.category, issue.target) for issue in result.issues}

    assert ("missing_key", "configmap/iam-agent-config:genai_project_id") in categories
    assert ("inconsistent_pair", "genai_project+genai_project_id") in categories
