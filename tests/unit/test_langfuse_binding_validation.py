from __future__ import annotations

from iam_agent.config.settings import Settings
from iam_agent.observability.langfuse_client import LangfuseClient


def _base_settings() -> Settings:
    return Settings(
        langfuse_enabled=True,
        langfuse_host="https://langfuse.koin3z.com",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        langfuse_org_id="cmoe9rmed0006xu06afe0d9bg",
        langfuse_project_id="cmoe9rrfd000bxu06xlivnbba",
        langfuse_org_name="devday-agents",
        langfuse_project_name="iam-agent",
    )


def test_langfuse_binding_valid_or_unavailable() -> None:
    result = LangfuseClient(settings=_base_settings()).validate_binding()
    assert result.status in {"valid", "unavailable"}


def test_langfuse_binding_invalid_project_id() -> None:
    settings = _base_settings()
    settings.langfuse_project_id = "wrong"
    result = LangfuseClient(settings=settings).validate_binding()
    assert result.status == "invalid"


def test_langfuse_binding_missing_credentials() -> None:
    settings = _base_settings()
    settings.langfuse_secret_key = ""
    result = LangfuseClient(settings=settings).validate_binding()
    assert result.status == "missing_credentials"
