from __future__ import annotations

from iam_agent.config.settings import Settings


def test_settings_reads_uppercase_langfuse_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.devday26.sogawa-yk.com")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_ORG_ID", "cmoij0zsj00002b073226lkr3")
    monkeypatch.setenv("LANGFUSE_PROJECT_ID", "cmoe9rrfd000bxu06xlivnbba")
    monkeypatch.setenv("LANGFUSE_ORG_NAME", "devday")
    monkeypatch.setenv("LANGFUSE_PROJECT_NAME", "iam-agent")
    monkeypatch.setenv("LANGFUSE_EXPECTED_HOST", "https://langfuse.devday26.sogawa-yk.com")
    monkeypatch.setenv("LANGFUSE_EXPECTED_ORG_ID", "cmoij0zsj00002b073226lkr3")
    monkeypatch.setenv("LANGFUSE_EXPECTED_PROJECT_ID", "cmoe9rrfd000bxu06xlivnbba")
    monkeypatch.setenv("LANGFUSE_EXPECTED_ORG_NAME", "devday")
    monkeypatch.setenv("LANGFUSE_EXPECTED_PROJECT_NAME", "iam-agent")
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")

    settings = Settings.from_env()

    assert settings.langfuse_host == "https://langfuse.devday26.sogawa-yk.com"
    assert settings.langfuse_public_key == "pk-lf-test"
    assert settings.langfuse_secret_key == "sk-lf-test"
    assert settings.langfuse_org_id == "cmoij0zsj00002b073226lkr3"
    assert settings.langfuse_project_id == "cmoe9rrfd000bxu06xlivnbba"
    assert settings.langfuse_org_name == "devday"
    assert settings.langfuse_project_name == "iam-agent"
    assert settings.langfuse_expected_host == "https://langfuse.devday26.sogawa-yk.com"
    assert settings.langfuse_expected_org_id == "cmoij0zsj00002b073226lkr3"
    assert settings.langfuse_expected_project_id == "cmoe9rrfd000bxu06xlivnbba"
    assert settings.langfuse_expected_org_name == "devday"
    assert settings.langfuse_expected_project_name == "iam-agent"
    assert settings.langfuse_enabled is True


def test_settings_prefers_lowercase_langfuse_vars_over_uppercase(monkeypatch) -> None:
    monkeypatch.setenv("langfuse_public_key", "pk-lower")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-upper")
    monkeypatch.setenv("langfuse_secret_key", "sk-lower")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-upper")
    monkeypatch.setenv("langfuse_enabled", "false")
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")

    settings = Settings.from_env()

    assert settings.langfuse_public_key == "pk-lower"
    assert settings.langfuse_secret_key == "sk-lower"
    assert settings.langfuse_enabled is False
