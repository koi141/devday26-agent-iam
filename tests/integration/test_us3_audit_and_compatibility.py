from __future__ import annotations

import json
import logging

from iam_agent.infra.logging.audit_logger import AuditLogger


def test_us3_audit_contains_trace_and_compatibility(caplog) -> None:
    logger = logging.getLogger("iam_agent.audit.us3")
    audit = AuditLogger(logger=logger)

    with caplog.at_level(logging.INFO, logger="iam_agent.audit.us3"):
        audit.record_workflow(
            request_id="workflow-t1",
            turn_id="t1",
            workflow_name="single_tool_passthrough",
            execution_order=1,
            target={"tool": "list_users"},
            input_summary={"provided_inputs": {}},
            decision_reason=["contract_check"],
            result="success",
            compatibility_status="single_tool_passthrough",
            trace_id="trace-1",
            telemetry_delivery_status="sent",
            telemetry_delivery_reason="ok",
            context_name="oke-iam",
            namespace="iam",
            ingress_host="iam.devday26.sogawa-yk.com",
        )

    assert caplog.records
    msg = caplog.records[-1].message
    payload = json.loads(msg.split("audit_event=", 1)[1])
    assert payload["trace_id"] == "trace-1"
    assert payload["compatibility_status"] == "single_tool_passthrough"
    assert payload["telemetry_delivery_status"] == "sent"
    assert payload["context_name"] == "oke-iam"
    assert payload["namespace"] == "iam"
    assert payload["ingress_host"] == "iam.devday26.sogawa-yk.com"
