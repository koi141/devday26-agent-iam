from __future__ import annotations

from fastapi.testclient import TestClient

import iam_agent.api.orch_routes as routes
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse


class StubOrchestrator:
    def __init__(self, response: NormalizedResponse) -> None:
        self._response = response

    def handle_a2a_request(self, *, payload, auth_token):  # noqa: ANN001
        return self._response

    def get_a2a_capabilities(self, *, source_agent_id, auth_token):  # noqa: ANN001
        return {"agent_id": "iam-agent", "version": "1.0.0", "operations": []}


def test_a2a_execute_error_contract_for_missing_input(monkeypatch) -> None:
    response = NormalizedResponse.error(
        message="不足項目",
        code="missing_input",
        retryable=False,
        proposal=["不足項目を指定してください。"],
        meta={"missing_inputs": ["request_id"]},
        audit=AuditPayload(result="error"),
    )
    monkeypatch.setattr(routes, "get_orchestrator", lambda: StubOrchestrator(response))
    client = TestClient(routes.app)

    result = client.post("/a2a/execute", json={})
    assert result.status_code == 400
    body = result.json()
    for key in ("error_code", "facts", "interpretation", "proposal"):
        assert key in body
    assert body["error_code"] == "missing_input"


def test_a2a_execute_success_contract(monkeypatch) -> None:
    response = NormalizedResponse.success(
        facts=["A2A 実行成功"],
        interpretation=["ローカルツール実行で完了しました。"],
        proposal=["必要なら追加条件を指定してください。"],
        data={"request_id": "req-1", "correlation_id": "corr-1"},
        audit=AuditPayload(result="success"),
    )
    monkeypatch.setattr(routes, "get_orchestrator", lambda: StubOrchestrator(response))
    client = TestClient(routes.app)

    result = client.post(
        "/a2a/execute",
        json={
            "request_id": "req-1",
            "correlation_id": "corr-1",
            "source_agent_id": "peer-1",
            "target_agent_id": "iam-agent",
            "requested_operation": "list_users",
            "objective": "一覧取得",
            "input_payload": {},
            "hop_count": 0,
            "visited_agents": [],
        },
    )
    assert result.status_code == 200
    body = result.json()
    for key in ("request_id", "correlation_id", "status", "facts", "interpretation", "proposal"):
        assert key in body
    assert body["status"] == "success"
