from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class QualityScore:
    semantic_alignment: float
    retry_count: int
    response_status: str
    missing_input_detected: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_alignment": self.semantic_alignment,
            "retry_count": self.retry_count,
            "response_status": self.response_status,
            "missing_input_detected": self.missing_input_detected,
        }


class QualityEvaluator:
    @staticmethod
    def evaluate(
        *,
        validation_status: str,
        retry_count: int,
        response_status: str,
        missing_input_detected: bool,
    ) -> QualityScore:
        if validation_status == "aligned":
            alignment = 1.0
        elif validation_status == "not_aligned":
            alignment = 0.25
        else:
            alignment = 0.5
        return QualityScore(
            semantic_alignment=alignment,
            retry_count=retry_count,
            response_status=response_status,
            missing_input_detected=missing_input_detected,
        )

