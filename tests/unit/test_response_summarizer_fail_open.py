from __future__ import annotations

from iam_agent.application.errors import TemporaryUpstreamFailure
from iam_agent.application.response_summarizer import ResponseSummarizer
from iam_agent.domain.models import SkillExecutionResult


class _FailingGenAI:
    def summarize_response(self, user_input, payload):  # noqa: ARG002
        raise TemporaryUpstreamFailure("要約上流障害")


def test_response_summarizer_falls_back_when_genai_summarize_fails() -> None:
    summarizer = ResponseSummarizer(genai_client=_FailingGenAI())  # type: ignore[arg-type]
    draft = summarizer.summarize(
        turn_id="t1",
        user_input="ポリシー一覧を出して",
        attempt=1,
        results=[
            SkillExecutionResult(
                request_id="r1",
                tool_name="list_policies",
                status="error",
                error_code="permission_denied",
                error_message="list_policies 権限不足",
                retryable=False,
                normalized_data={},
            )
        ],
    )

    assert draft.generated_by_model == "heuristic"
    assert draft.facts == ["要求を完了できませんでした。"]
    assert "list_policies 権限不足" in draft.interpretation[0]
    assert draft.proposal == ["入力条件または権限設定を確認して再実行してください。"]
