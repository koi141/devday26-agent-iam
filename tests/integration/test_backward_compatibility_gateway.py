from __future__ import annotations

import iam_agent.api.orch_routes as routes


def test_gateway_sets_single_tool_compatibility_meta(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "process_message",
        lambda message: {
            "status": "success",
            "facts": [],
            "interpretation": [],
            "proposal": [],
            "meta": {"trace_id": "trace-1", "telemetry_delivery_status": "sent"},
        },
    )
    payload = routes.chat_api(routes.ChatRequest(message="ポリシー一覧を表示して"))
    assert payload["meta"]["route_mode"] == "single_tool_passthrough"
    assert payload["meta"]["compatibility"]["single_tool_contract_preserved"] is True
    assert payload["meta"]["trace_id"] == "trace-1"


def test_gateway_sets_additive_layer_meta(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "process_message",
        lambda message: {
            "status": "success",
            "facts": [],
            "interpretation": [],
            "proposal": [],
            "meta": {"trace_id": "trace-2", "telemetry_delivery_status": "failed"},
        },
    )
    payload = routes.chat_api(routes.ChatRequest(message="鈴木さんは何ができますか"))
    assert payload["meta"]["route_mode"] == "permission_investigation"
    assert payload["meta"]["compatibility"]["additive_layer_active"] is True
    assert payload["meta"]["trace_id"] == "trace-2"


def test_gateway_detects_permission_investigation_for_sato_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "process_message",
        lambda message: {
            "status": "success",
            "facts": [],
            "interpretation": [],
            "proposal": [],
            "meta": {"trace_id": "trace-sato", "telemetry_delivery_status": "sent"},
        },
    )
    payload = routes.chat_api(routes.ChatRequest(message="佐藤さんはどのような操作を許可されている？"))
    assert payload["meta"]["route_mode"] == "permission_investigation"
    assert payload["meta"]["compatibility"]["additive_layer_active"] is True
    assert payload["meta"]["trace_id"] == "trace-sato"


def test_gateway_keeps_single_tool_mode_for_resource_listing(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "process_message",
        lambda message: {
            "status": "success",
            "facts": [],
            "interpretation": [],
            "proposal": [],
            "meta": {"trace_id": "trace-3", "telemetry_delivery_status": "sent"},
        },
    )
    payload = routes.chat_api(routes.ChatRequest(message="devday26 のリソース一覧を表示して"))
    assert payload["meta"]["route_mode"] == "single_tool_passthrough"
    assert payload["meta"]["compatibility"]["single_tool_contract_preserved"] is True
    assert payload["meta"]["trace_id"] == "trace-3"


def test_gateway_chat_entrypoint_is_unchanged_after_a2a_extension() -> None:
    response = routes.chat_ui_redirect()
    assert response.status_code == 307
    assert response.headers.get("location") == "/ui"


def test_gateway_sets_access_denial_route_mode_without_breaking_meta(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "process_message",
        lambda message: {
            "status": "success",
            "facts": [],
            "interpretation": [],
            "proposal": [],
            "meta": {"trace_id": "trace-deny", "telemetry_delivery_status": "sent"},
        },
    )
    payload = routes.chat_api(routes.ChatRequest(message="この操作はアクセス拒否されました。原因を調べて"))
    assert payload["meta"]["route_mode"] == "access_denial_troubleshooting"
    assert payload["meta"]["compatibility"]["additive_layer_active"] is True
    assert payload["meta"]["trace_id"] == "trace-deny"
