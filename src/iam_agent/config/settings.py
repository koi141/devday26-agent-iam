from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Iterable

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is optional at runtime
    load_dotenv = None


IDENTITY_DOMAIN_REQUIRED = ("domain_url", "domain_client_id", "domain_client_secret")
OCI_REQUIRED = ("compartment_ocid",)
HR_DB_REQUIRED = ("hr_database_user", "hr_database_pass", "hr_database_connectstr")
GENAI_REQUIRED = ("genai_baseurl", "genai_project", "genai_api_key")
LANGFUSE_REQUIRED = ("langfuse_host", "langfuse_public_key", "langfuse_secret_key", "langfuse_org_id", "langfuse_project_id")
A2A_REQUIRED = ("a2a_enabled", "a2a_agent_id", "a2a_peer_registry_json")


_ROUTE_REQUIRED = {
    "identity_domain_oauth": IDENTITY_DOMAIN_REQUIRED,
    "oci_workload_identity": OCI_REQUIRED,
    "hr_db_credentials": HR_DB_REQUIRED,
    "genai_api_key": GENAI_REQUIRED,
    "langfuse_api_key": LANGFUSE_REQUIRED,
    "a2a_peer_auth": A2A_REQUIRED,
}


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "enabled"}


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    return default.strip()


def _env_bool_first(names: tuple[str, ...], default: bool) -> bool:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        raw = value.strip().lower()
        if not raw:
            continue
        return raw in {"1", "true", "yes", "on", "enabled"}
    return default


def _env_int_first(names: tuple[str, ...], default: int) -> int:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        raw = value.strip()
        if not raw:
            continue
        try:
            return int(raw)
        except Exception:
            continue
    return default


def _maybe_load_dotenv() -> None:
    if load_dotenv is None:
        return
    env_file = Path(".env")
    if env_file.exists():
        load_dotenv(env_file, override=False)


@dataclass(slots=True)
class Settings:
    domain_url: str = ""
    domain_client_id: str = ""
    domain_client_secret: str = ""
    domain_scope: str = ""
    token_url: str = ""

    compartment_ocid: str = ""
    oci_profile: str = "devdey-agent"

    genai_baseurl: str = ""
    genai_project: str = ""
    genai_api_key: str = ""
    genai_model: str = "openai.gpt-oss-120b"

    langfuse_host: str = "https://langfuse.koin3z.com"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_org_id: str = ""
    langfuse_project_id: str = ""
    langfuse_org_name: str = "devday-agents"
    langfuse_project_name: str = "iam-agent"
    langfuse_enabled: bool = True

    hr_database_user: str = ""
    hr_database_pass: str = ""
    hr_database_connectstr: str = ""
    investigation_layer_enabled: bool = True
    compatibility_check_enabled: bool = True
    single_tool_passthrough_enabled: bool = True
    a2a_enabled: bool = True
    a2a_agent_id: str = "iam-agent"
    a2a_peer_registry_json: str = ""
    a2a_peer_auth_token: str = ""
    a2a_max_hops: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        _maybe_load_dotenv()
        domain_url = _env_first("domain_url", "DOMAIN_URL")
        token_url = _env_first("token_url", "TOKEN_URL")
        if not token_url and domain_url:
            token_url = f"{domain_url.rstrip('/')}/oauth2/v1/token"
        return cls(
            domain_url=domain_url,
            domain_client_id=_env_first("domain_client_id", "DOMAIN_CLIENT_ID"),
            domain_client_secret=_env_first("domain_client_secret", "DOMAIN_CLIENT_SECRET"),
            domain_scope=_env_first("domain_scope", "DOMAIN_SCOPE", default="urn:opc:idm:__myscopes__"),
            token_url=token_url,
            compartment_ocid=_env_first("compartment_ocid", "COMPARTMENT_OCID"),
            oci_profile=_env_first("oci_profile", "OCI_PROFILE", default="devdey-agent"),
            genai_baseurl=_env_first("genai_baseurl", "GENAI_BASEURL"),
            genai_project=_env_first("genai_project", "GENAI_PROJECT"),
            genai_api_key=_env_first("genai_api_key", "GENAI_API_KEY"),
            genai_model=_env_first("genai_model", "GENAI_MODEL", default="openai.gpt-oss-120b"),
            langfuse_host=_env_first("langfuse_host", "LANGFUSE_HOST", default="https://langfuse.koin3z.com"),
            langfuse_public_key=_env_first("langfuse_public_key", "LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key=_env_first("langfuse_secret_key", "LANGFUSE_SECRET_KEY"),
            langfuse_org_id=_env_first("langfuse_org_id", "LANGFUSE_ORG_ID"),
            langfuse_project_id=_env_first("langfuse_project_id", "LANGFUSE_PROJECT_ID"),
            langfuse_org_name=_env_first("langfuse_org_name", "LANGFUSE_ORG_NAME", default="devday-agents"),
            langfuse_project_name=_env_first("langfuse_project_name", "LANGFUSE_PROJECT_NAME", default="iam-agent"),
            langfuse_enabled=_env_bool_first(("langfuse_enabled", "LANGFUSE_ENABLED"), True),
            hr_database_user=_env_first("hr_database_user", "HR_DATABASE_USER"),
            hr_database_pass=_env_first("hr_database_pass", "HR_DATABASE_PASS"),
            hr_database_connectstr=_env_first("hr_database_connectstr", "HR_DATABASE_CONNECTSTR"),
            investigation_layer_enabled=_env_bool_first(("investigation_layer_enabled", "INVESTIGATION_LAYER_ENABLED"), True),
            compatibility_check_enabled=_env_bool_first(("compatibility_check_enabled", "COMPATIBILITY_CHECK_ENABLED"), True),
            single_tool_passthrough_enabled=_env_bool_first(("single_tool_passthrough_enabled", "SINGLE_TOOL_PASSTHROUGH_ENABLED"), True),
            a2a_enabled=_env_bool_first(("a2a_enabled", "A2A_ENABLED"), True),
            a2a_agent_id=_env_first("a2a_agent_id", "A2A_AGENT_ID", default="iam-agent"),
            a2a_peer_registry_json=_env_first("a2a_peer_registry_json", "A2A_PEER_REGISTRY_JSON"),
            a2a_peer_auth_token=_env_first("a2a_peer_auth_token", "A2A_PEER_AUTH_TOKEN"),
            a2a_max_hops=max(1, _env_int_first(("a2a_max_hops", "A2A_MAX_HOPS"), 3)),
        )

    def missing(self, keys: Iterable[str]) -> list[str]:
        missing_keys: list[str] = []
        for key in keys:
            value = getattr(self, key, "")
            if isinstance(value, str) and not value.strip():
                missing_keys.append(key)
            elif value is None:
                missing_keys.append(key)
        return missing_keys

    def missing_for_route(self, auth_route: str) -> list[str]:
        required = _ROUTE_REQUIRED.get(auth_route)
        if not required:
            return []
        return self.missing(required)

    def to_redacted_dict(self) -> dict[str, str]:
        return {
            "domain_url": self.domain_url,
            "domain_client_id": "***" if self.domain_client_id else "",
            "domain_client_secret": "***" if self.domain_client_secret else "",
            "domain_scope": self.domain_scope,
            "token_url": self.token_url,
            "compartment_ocid": self.compartment_ocid,
            "oci_profile": self.oci_profile,
            "genai_baseurl": self.genai_baseurl,
            "genai_project": self.genai_project,
            "genai_api_key": "***" if self.genai_api_key else "",
            "genai_model": self.genai_model,
            "langfuse_host": self.langfuse_host,
            "langfuse_public_key": "***" if self.langfuse_public_key else "",
            "langfuse_secret_key": "***" if self.langfuse_secret_key else "",
            "langfuse_org_id": self.langfuse_org_id,
            "langfuse_project_id": self.langfuse_project_id,
            "langfuse_org_name": self.langfuse_org_name,
            "langfuse_project_name": self.langfuse_project_name,
            "langfuse_enabled": str(self.langfuse_enabled).lower(),
            "hr_database_user": self.hr_database_user,
            "hr_database_pass": "***" if self.hr_database_pass else "",
            "hr_database_connectstr": self.hr_database_connectstr,
            "investigation_layer_enabled": str(self.investigation_layer_enabled).lower(),
            "compatibility_check_enabled": str(self.compatibility_check_enabled).lower(),
            "single_tool_passthrough_enabled": str(self.single_tool_passthrough_enabled).lower(),
            "a2a_enabled": str(self.a2a_enabled).lower(),
            "a2a_agent_id": self.a2a_agent_id,
            "a2a_peer_registry_json": "***" if self.a2a_peer_registry_json else "",
            "a2a_peer_auth_token": "***" if self.a2a_peer_auth_token else "",
            "a2a_max_hops": str(self.a2a_max_hops),
        }


def get_settings() -> Settings:
    return Settings.from_env()
