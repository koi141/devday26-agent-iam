from __future__ import annotations

import pytest

from iam_agent.application.errors import InvalidArgumentError
from iam_agent.config.runtime_contract import EXPECTED_GENAI_PROJECT_ID, EXPECTED_GENAI_PROJECT_NAME
from iam_agent.config.settings import Settings
from iam_agent.infra.clients.genai_client import GenAIClient
import iam_agent.infra.clients.genai_client as genai_client_module


def _base_settings() -> Settings:
    return Settings(
        genai_baseurl="https://inference.generativeai.ap-osaka-1.oci.oraclecloud.com",
        genai_project=EXPECTED_GENAI_PROJECT_NAME,
        genai_project_id=EXPECTED_GENAI_PROJECT_ID,
        genai_api_key="dummy",
    )


def test_genai_project_binding_valid() -> None:
    client = GenAIClient(settings=_base_settings())
    summary = client.summarize_response(user_input="テスト", payload={"ok": True})
    assert "facts" in summary


def test_genai_project_name_mismatch_raises_invalid_argument() -> None:
    settings = _base_settings()
    settings.genai_project = "devday-project"
    client = GenAIClient(settings=settings)
    with pytest.raises(InvalidArgumentError):
        client.summarize_response(user_input="テスト", payload={"ok": True})


def test_genai_project_id_mismatch_raises_invalid_argument() -> None:
    settings = _base_settings()
    settings.genai_project_id = "ocid1.generativeaiproject.oc1.ap-osaka-1.example"
    client = GenAIClient(settings=settings)
    with pytest.raises(InvalidArgumentError):
        client.plan_action(user_input="ユーザー一覧を出して", available_tools=["list_users"])


def test_openai_client_initialized_with_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _DummyOpenAI:
        def __init__(self, **kwargs: str) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(genai_client_module, "OpenAI", _DummyOpenAI)
    GenAIClient(settings=_base_settings())

    assert captured["project"] == EXPECTED_GENAI_PROJECT_ID
