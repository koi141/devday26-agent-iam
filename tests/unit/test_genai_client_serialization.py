from __future__ import annotations

from datetime import datetime, timezone

from iam_agent.config.runtime_contract import EXPECTED_GENAI_PROJECT_ID, EXPECTED_GENAI_PROJECT_NAME
from iam_agent.config.settings import Settings
from iam_agent.infra.clients.genai_client import GenAIClient


class _DummyGenAIResponse:
    output_text = '{"facts":["処理結果を受領しました。"],"interpretation":["ok"],"proposal":["ok"]}'


class _DummyResponsesAPI:
    def __init__(self) -> None:
        self.last_input = ""

    def create(self, *, model: str, input: str):  # noqa: ARG002,A002
        self.last_input = input
        return _DummyGenAIResponse()


class _DummyOpenAIClient:
    def __init__(self) -> None:
        self.responses = _DummyResponsesAPI()


def test_summarize_response_accepts_datetime_payload() -> None:
    settings = Settings(
        genai_baseurl="https://example.invalid",
        genai_project=EXPECTED_GENAI_PROJECT_NAME,
        genai_project_id=EXPECTED_GENAI_PROJECT_ID,
        genai_api_key="dummy",
    )
    client = GenAIClient(settings=settings)
    dummy_client = _DummyOpenAIClient()
    client._client = dummy_client

    payload = {
        "generated_at": datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc),
        "nested": {"finished_at": datetime(2026, 4, 30, 1, 2, 3, tzinfo=timezone.utc)},
    }
    summary = client.summarize_response(user_input="テスト", payload=payload)

    assert summary["facts"] == ["処理結果を受領しました。"]
    assert "2026-04-30" in dummy_client.responses.last_input
