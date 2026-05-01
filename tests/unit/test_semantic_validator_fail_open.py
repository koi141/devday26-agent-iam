from __future__ import annotations

from iam_agent.application.errors import TemporaryUpstreamFailure
from iam_agent.application.semantic_validator import SemanticValidator
from iam_agent.domain.models import ResponseDraft


class FailingGenAI:
    def validate_semantic_alignment(self, user_input, answer_text):  # noqa: ARG002
        raise TemporaryUpstreamFailure("semantic upstream unavailable")


def test_semantic_validator_fail_open_on_upstream_failure() -> None:
    validator = SemanticValidator(genai_client=FailingGenAI())  # type: ignore[arg-type]
    draft = ResponseDraft(
        turn_id="t1",
        attempt=1,
        facts=["f1"],
        interpretation=["i1"],
        proposal=["p1"],
        referenced_requests=["r1"],
        generated_by_model="genai",
    )

    result = validator.validate(turn_id="t1", attempt=1, user_input="ポリシー一覧を表示して", draft=draft)
    assert result.status == "aligned"
    assert result.checked_by_model == "heuristic"
