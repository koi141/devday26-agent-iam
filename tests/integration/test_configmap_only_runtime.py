from __future__ import annotations

from pathlib import Path

from iam_agent.config.settings import Settings


def _clear_env(monkeypatch) -> None:
    for key in (
        "domain_url",
        "DOMAIN_URL",
        "genai_project",
        "GENAI_PROJECT",
        "genai_project_id",
        "GENAI_PROJECT_ID",
        "ALLOW_DOTENV",
        "allow_dotenv",
    ):
        monkeypatch.delenv(key, raising=False)


def test_settings_do_not_use_dotenv_by_default(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("domain_url=https://dotenv.example\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)

    settings = Settings.from_env()

    assert settings.domain_url == ""


def test_settings_can_use_dotenv_only_when_explicitly_enabled(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("domain_url=https://dotenv.example\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    _clear_env(monkeypatch)
    monkeypatch.setenv("ALLOW_DOTENV", "true")

    settings = Settings.from_env()

    assert settings.domain_url == "https://dotenv.example"
