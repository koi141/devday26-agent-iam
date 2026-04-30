from __future__ import annotations

import json
from typing import Any, Callable

from iam_agent.domain.models import ResponseDraft, SemanticValidationResult
from iam_agent.infra.clients.genai_client import GenAIClient


class SemanticValidator:
    def __init__(
        self,
        genai_client: GenAIClient,
        observation_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.genai_client = genai_client
        self.observation_hook = observation_hook

    def validate(self, *, turn_id: str, attempt: int, user_input: str, draft: ResponseDraft) -> SemanticValidationResult:
        answer_lines = [
            "事実: " + " / ".join(draft.facts),
            "解釈: " + " / ".join(draft.interpretation),
            "提案: " + " / ".join(draft.proposal),
        ]
        if draft.generated_by_model == "delegation_passthrough":
            answer_lines.append("委譲結果: 他エージェントの応答を含む")
        answer_text = "\n".join(answer_lines)
        result = self.genai_client.validate_semantic_alignment(user_input=user_input, answer_text=answer_text)
        if self.observation_hook is not None:
            try:
                self.observation_hook(
                    {
                        "operation": "semantic_validator",
                        "model_name": "genai",
                        "input_summary": user_input[:200],
                        "output_summary": json.dumps(result, ensure_ascii=False)[:500],
                    }
                )
            except Exception:
                pass
        return SemanticValidationResult(
            turn_id=turn_id,
            attempt=attempt,
            status=str(result.get("status", "not_aligned")),
            reason=[str(x) for x in result.get("reason", [])],
            missing_points=[str(x) for x in result.get("missing_points", [])],
            checked_by_model="genai",
        )
