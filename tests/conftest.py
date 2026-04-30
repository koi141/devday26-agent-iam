from __future__ import annotations

import pytest

from iam_agent.domain.contracts import AuditPayload, NormalizedResponse


class DummyGenAI:
    def plan_action(self, user_input, available_tools):  # noqa: ARG002
        return {"steps": []}

    def summarize_response(self, user_input, payload):  # noqa: ARG002
        return {
            "facts": ["処理結果を受領しました。"],
            "interpretation": ["結果を確認してください。"],
            "proposal": ["必要に応じて追加条件を指定してください。"],
        }

    def validate_semantic_alignment(self, user_input, answer_text):  # noqa: ARG002
        return {"status": "aligned", "reason": ["ok"], "missing_points": []}


@pytest.fixture
def dummy_genai() -> DummyGenAI:
    return DummyGenAI()


@pytest.fixture
def success_response_factory():
    def _factory(data: dict | None = None) -> NormalizedResponse:
        return NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data=data or {},
            audit=AuditPayload(result="success"),
        )

    return _factory
