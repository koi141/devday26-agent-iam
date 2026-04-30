from __future__ import annotations

from iam_agent.domain.models import AuditLogEvent
from iam_agent.infra.logging.audit_logger import AuditLogger
from iam_agent.infra.logging.redaction import redact_a2a_payload


def test_redact_a2a_payload_masks_sensitive_fields() -> None:
    payload = {
        "source_agent_id": "peer-1",
        "peer_auth_token": "secret-token",
        "nested": {"id_token": "abc", "normal": "ok"},
    }
    redacted = redact_a2a_payload(payload)
    assert redacted["peer_auth_token"] == "***REDACTED***"
    assert redacted["nested"]["id_token"] == "***REDACTED***"
    assert redacted["nested"]["normal"] == "ok"


def test_audit_logger_fills_a2a_required_fields() -> None:
    logger = AuditLogger()
    payload = logger.build_event(
        AuditLogEvent(
            request_id="req-1",
            turn_id="turn-1",
            tool_name="a2a_execute",
            target={"service": "a2a"},
            input_summary={},
            decision_reason=["test"],
            result="success",
            retryable=False,
        )
    )
    for key in ("correlation_id", "peer_agent", "delegation_outcome"):
        assert key in payload
