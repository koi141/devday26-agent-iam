from __future__ import annotations

from typing import Any


EXPECTED_NAMESPACE = "iam"
EXPECTED_INGRESS_HOST = "iam.devday26.sogawa-yk.com"
EXPECTED_GENAI_PROJECT_NAME = "iam"
EXPECTED_GENAI_PROJECT_ID = "ocid1.generativeaiproject.oc1.ap-osaka-1.amaaaaaatgpiiviaq3o4mil2etytuquh7qj2qzd2s3tbxjc6kkv34xpwzivq"


REQUIRED_RUNTIME_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "source_name": "iam-agent-config",
        "source_type": "configmap",
        "required_entries": (
            {"config_key": "domain_url", "setting_attr": "domain_url", "used_by": ("identity_domain_oauth",)},
            {"config_key": "genai_baseurl", "setting_attr": "genai_baseurl", "used_by": ("genai_api_key",)},
            {"config_key": "genai_project", "setting_attr": "genai_project", "used_by": ("genai_api_key",)},
            {"config_key": "genai_project_id", "setting_attr": "genai_project_id", "used_by": ("genai_api_key",)},
        ),
    },
    {
        "source_name": "iam-agent-runtime-config",
        "source_type": "secret",
        "required_entries": (
            {"config_key": "compartment_ocid", "setting_attr": "compartment_ocid", "used_by": ("oci_workload_identity",)},
            {"config_key": "hr_database_user", "setting_attr": "hr_database_user", "used_by": ("hr_db_credentials",)},
            {"config_key": "hr_database_pass", "setting_attr": "hr_database_pass", "used_by": ("hr_db_credentials",)},
            {"config_key": "hr_database_connectstr", "setting_attr": "hr_database_connectstr", "used_by": ("hr_db_credentials",)},
        ),
    },
    {
        "source_name": "domain-client-credential",
        "source_type": "secret",
        "required_entries": (
            {"config_key": "client_id", "setting_attr": "domain_client_id", "used_by": ("identity_domain_oauth",)},
            {"config_key": "client_secret", "setting_attr": "domain_client_secret", "used_by": ("identity_domain_oauth",)},
            {"config_key": "scope", "setting_attr": "domain_scope", "used_by": ("identity_domain_oauth",)},
        ),
    },
    {
        "source_name": "oci-genai-key",
        "source_type": "secret",
        "required_entries": (
            {"config_key": "api_keys", "setting_attr": "genai_api_key", "used_by": ("genai_api_key",)},
        ),
    },
    {
        "source_name": "iam-agent-langfuse",
        "source_type": "secret",
        "required_entries": (
            {"config_key": "langfuse_host", "setting_attr": "langfuse_host", "used_by": ("langfuse_api_key",)},
            {"config_key": "langfuse_public_key", "setting_attr": "langfuse_public_key", "used_by": ("langfuse_api_key",)},
            {"config_key": "langfuse_secret_key", "setting_attr": "langfuse_secret_key", "used_by": ("langfuse_api_key",)},
            {"config_key": "langfuse_org_id", "setting_attr": "langfuse_org_id", "used_by": ("langfuse_api_key",)},
            {"config_key": "langfuse_project_id", "setting_attr": "langfuse_project_id", "used_by": ("langfuse_api_key",)},
        ),
    },
)
