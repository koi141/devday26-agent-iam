from __future__ import annotations

import iam_agent.api.orch_routes as routes


def test_single_tool_passthrough_contract_is_preserved_with_observability(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "process_message",
        lambda message: {
            "status": "success",
            "facts": ["ok"],
            "interpretation": ["ok"],
            "proposal": ["ok"],
            "meta": {"trace_id": "trace-123", "telemetry_delivery_status": "sent"},
        },
    )
    payload = routes.chat_api(routes.ChatRequest(message="ポリシー一覧を表示して"))
    assert payload["status"] == "success"
    assert payload["meta"]["compatibility"]["single_tool_contract_preserved"] is True
    assert payload["meta"]["trace_id"] == "trace-123"
