from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
import uuid

from iam_agent.config.settings import Settings

HEX32_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")

try:
    from langfuse import Langfuse
except Exception:  # pragma: no cover - optional dependency
    Langfuse = None


@dataclass(slots=True)
class BindingValidationResult:
    status: str
    reason: str = ""


class LangfuseClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any = None
        if self.settings.langfuse_enabled and Langfuse is not None:
            self._client = Langfuse(
                host=self.settings.langfuse_host,
                public_key=self.settings.langfuse_public_key,
                secret_key=self.settings.langfuse_secret_key,
            )

    def validate_binding(self) -> BindingValidationResult:
        if not self.settings.langfuse_enabled:
            return BindingValidationResult(status="disabled", reason="langfuse_enabled=false")

        missing = self.settings.missing_for_route("langfuse_api_key")
        if missing:
            return BindingValidationResult(status="missing_credentials", reason=", ".join(missing))

        expected_host = (self.settings.langfuse_expected_host or "").rstrip("/")
        if expected_host and self.settings.langfuse_host.rstrip("/") != expected_host:
            return BindingValidationResult(status="invalid", reason="langfuse_host mismatch")

        checks = (
            (self.settings.langfuse_org_id, self.settings.langfuse_expected_org_id, "org_id"),
            (self.settings.langfuse_project_id, self.settings.langfuse_expected_project_id, "project_id"),
            (self.settings.langfuse_org_name, self.settings.langfuse_expected_org_name, "org_name"),
            (self.settings.langfuse_project_name, self.settings.langfuse_expected_project_name, "project_name"),
        )
        for actual, expected, key in checks:
            if expected and actual != expected:
                return BindingValidationResult(status="invalid", reason=f"{key} mismatch")

        if self._client is None:
            return BindingValidationResult(status="unavailable", reason="langfuse sdk unavailable")
        return BindingValidationResult(status="valid")

    def send_trace(self, payload: dict[str, Any]) -> tuple[str, str]:
        validation = self.validate_binding()
        if validation.status in {"disabled", "missing_credentials"}:
            return "skipped", validation.reason
        if validation.status != "valid":
            return "failed", f"binding_invalid: {validation.reason}"

        try:
            trace_id = self._normalize_trace_id(payload.get("trace_id"))
            if not trace_id and hasattr(self._client, "create_trace_id"):
                trace_id = str(self._client.create_trace_id())
            trace_context = {"trace_id": trace_id} if trace_id else None
            self._client.create_event(
                trace_context=trace_context,
                name=payload.get("request_type") or "iam-agent-request",
                input={"user_prompt_summary": payload.get("user_prompt_summary")},
                output={"status": payload.get("status")},
                metadata={
                    "source_trace_id": payload.get("trace_id"),
                    "turn_id": payload.get("turn_id"),
                    "request_id": payload.get("request_id"),
                    "status": payload.get("status"),
                    "compatibility_status": payload.get("compatibility_status", ""),
                    "execution_outcome": payload.get("execution_outcome", ""),
                    "correlation_id": payload.get("correlation_id", ""),
                    "peer_agent": payload.get("peer_agent", ""),
                    "delegation_outcome": payload.get("delegation_outcome", ""),
                },
            )
            for span in payload.get("spans", []):
                self._client.create_event(
                    trace_context=trace_context,
                    name=f"stage:{span.get('stage', 'stage')}",
                    metadata={
                        "span_id": span.get("span_id"),
                        "stage": span.get("stage"),
                        "attempt": span.get("attempt"),
                        "status": span.get("status"),
                        "latency_ms": span.get("latency_ms"),
                        "error_class": span.get("error_class"),
                    },
                )
            score = payload.get("quality_score") or {}
            if score:
                self._client.create_score(
                    name="semantic_alignment",
                    value=float(score.get("semantic_alignment", 0.0)),
                    trace_id=trace_id,
                    comment=f"retry_count={score.get('retry_count', 0)}, response_status={score.get('response_status', '')}",
                )
            self._client.flush()
            return "sent", "ok"
        except Exception as exc:  # pragma: no cover - runtime/network
            return "failed", str(exc)

    def send_snapshot(self, snapshot: dict[str, Any]) -> tuple[str, str]:
        validation = self.validate_binding()
        if validation.status in {"disabled", "missing_credentials"}:
            return "skipped", validation.reason
        if validation.status != "valid":
            return "failed", f"binding_invalid: {validation.reason}"
        try:
            self._client.create_event(
                name="comparison_snapshot",
                metadata=snapshot,
            )
            self._client.flush()
            return "sent", "ok"
        except Exception as exc:  # pragma: no cover - runtime/network
            return "failed", str(exc)

    @staticmethod
    def _normalize_trace_id(raw_trace_id: Any) -> str:
        if raw_trace_id in (None, ""):
            return ""
        text = str(raw_trace_id).strip()
        if text.startswith("trace-"):
            text = text[6:]
        compact = text.replace("-", "").strip()
        if HEX32_PATTERN.fullmatch(compact):
            return compact.lower()
        try:
            return uuid.UUID(text).hex
        except (ValueError, AttributeError, TypeError):
            return uuid.uuid5(uuid.NAMESPACE_URL, str(raw_trace_id)).hex
