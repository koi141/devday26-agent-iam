from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from typing import Any

from iam_agent.domain.models import AuditLogEvent
from iam_agent.infra.logging.redaction import redact_mapping


class AuditLogger:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("iam_agent.audit")

    def build_event(self, event: AuditLogEvent) -> dict[str, Any]:
        payload = redact_mapping(asdict(event))
        return self._ensure_required_fields(payload)

    def record(self, event: AuditLogEvent) -> dict[str, Any]:
        payload = self.build_event(event)
        self.logger.info("audit_event=%s", json.dumps(payload, ensure_ascii=False, default=str))
        return payload

    def record_workflow(
        self,
        *,
        request_id: str,
        turn_id: str,
        workflow_name: str,
        execution_order: int,
        skill_name: str = "",
        target: dict[str, Any],
        input_summary: dict[str, Any],
        decision_reason: list[str],
        result: str,
        retryable: bool = False,
        error_class: str = "",
        evidence_links: list[str] | None = None,
        compatibility_status: str = "",
        trace_id: str = "",
        telemetry_delivery_status: str = "",
        telemetry_delivery_reason: str = "",
        correlation_id: str = "",
        peer_agent: str = "",
        delegation_outcome: str = "",
        context_name: str = "",
        namespace: str = "",
        ingress_host: str = "",
    ) -> dict[str, Any]:
        event = AuditLogEvent(
            request_id=request_id,
            turn_id=turn_id,
            tool_name=workflow_name,
            skill_name=skill_name,
            target=target,
            input_summary=input_summary,
            decision_reason=decision_reason,
            execution_order=execution_order,
            result=result,
            retryable=retryable,
            error_class=error_class,
            evidence_links=evidence_links or [],
            compatibility_status=compatibility_status,
            trace_id=trace_id,
            telemetry_delivery_status=telemetry_delivery_status,
            telemetry_delivery_reason=telemetry_delivery_reason,
            correlation_id=correlation_id,
            peer_agent=peer_agent,
            delegation_outcome=delegation_outcome,
        )
        payload = self.build_event(event)
        payload["context_name"] = context_name
        payload["namespace"] = namespace
        payload["ingress_host"] = ingress_host
        self.logger.info("audit_event=%s", json.dumps(payload, ensure_ascii=False, default=str))
        return payload

    @staticmethod
    def _ensure_required_fields(payload: dict[str, Any]) -> dict[str, Any]:
        payload.setdefault("actor", "iam-agent")
        payload.setdefault("target", {})
        payload.setdefault("input_summary", {})
        payload.setdefault("decision_reason", [])
        payload.setdefault("result", "unknown")
        payload.setdefault("correlation_id", "")
        payload.setdefault("peer_agent", "")
        payload.setdefault("delegation_outcome", "")
        payload.setdefault("request_id", "")
        payload.setdefault("turn_id", "")
        payload.setdefault("tool_name", "unknown")
        payload.setdefault("skill_name", "")
        payload.setdefault("oci_request_id", "")
        payload.setdefault("context_name", "")
        payload.setdefault("namespace", "")
        payload.setdefault("ingress_host", "")
        payload.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        return payload
