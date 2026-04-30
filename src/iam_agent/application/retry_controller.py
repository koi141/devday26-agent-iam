from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RetryController:
    max_attempts: int = 3
    attempt_count: int = 0
    linked_idempotency_key: str = ""
    linked_correlation_id: str = ""

    def register(self, semantic_status: str) -> str:
        self.attempt_count += 1
        if semantic_status == "aligned":
            return "respond"
        if self.attempt_count >= self.max_attempts:
            return "abort"
        return "replan"

    def bind_a2a_idempotency(self, idempotency_key: str, correlation_id: str = "") -> None:
        self.linked_idempotency_key = idempotency_key.strip()
        self.linked_correlation_id = correlation_id.strip()

    def clear_a2a_idempotency(self) -> None:
        self.linked_idempotency_key = ""
        self.linked_correlation_id = ""

    def reset(self) -> None:
        self.attempt_count = 0
        self.clear_a2a_idempotency()
