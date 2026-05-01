from __future__ import annotations

from iam_agent.config.runtime_contract import EXPECTED_GENAI_PROJECT_ID, EXPECTED_GENAI_PROJECT_NAME
from iam_agent.config.settings import Settings
from iam_agent.infra.clients.genai_client import GenAIClient


class _FailingResponsesAPI:
    def create(self, *, model: str, input: str):  # noqa: ARG002,A002
        raise RuntimeError("upstream failure")


class _FailingOpenAIClient:
    def __init__(self) -> None:
        self.responses = _FailingResponsesAPI()


def _settings() -> Settings:
    return Settings(
        genai_baseurl="https://example.invalid",
        genai_project=EXPECTED_GENAI_PROJECT_NAME,
        genai_project_id=EXPECTED_GENAI_PROJECT_ID,
        genai_api_key="dummy",
    )


def test_summarize_response_local_fallback_for_list_users() -> None:
    client = GenAIClient(settings=_settings())
    client._client = _FailingOpenAIClient()

    summary = client.summarize_response(
        user_input="ユーザー一覧を出して",
        payload={
            "results": [
                {
                    "tool_name": "list_users",
                    "status": "success",
                    "data": {
                        "users": [
                            {"userName": "IAM_Agent"},
                            {"userName": "RI_Agent"},
                        ],
                        "total_results": 2,
                    },
                }
            ]
        },
    )

    assert summary["facts"][0] == "ユーザー一覧を取得しました（2件）。"
    assert "IAM_Agent" in summary["facts"][1]
    assert any("要約の生成に失敗" in line for line in summary["interpretation"])


def test_summarize_response_local_fallback_for_list_policies() -> None:
    client = GenAIClient(settings=_settings())
    client._client = _FailingOpenAIClient()

    summary = client.summarize_response(
        user_input="ポリシー一覧を出して",
        payload={
            "results": [
                {
                    "tool_name": "list_policies",
                    "status": "success",
                    "data": {
                        "policies": [
                            {"name": "devday-iamagent"},
                            {"name": "genai-use-apikey"},
                        ]
                    },
                }
            ]
        },
    )

    assert summary["facts"][0] == "ポリシー一覧を取得しました（2件）。"
    assert "devday-iamagent" in summary["facts"][1]
    assert any("許可操作の範囲" in line for line in summary["interpretation"])
