from __future__ import annotations

from fastapi.testclient import TestClient

import iam_agent.api.orch_routes as routes


class StubOrchestrator:
    def get_a2a_capabilities(self, *, source_agent_id, auth_token):  # noqa: ANN001
        return {
            "agent_id": "iam-agent",
            "version": "1.0.0",
            "operations": [
                {
                    "operation_name": "list_users",
                    "required_inputs": [],
                    "risk_level": "low",
                }
            ],
            "constraints": ["high-risk requires idempotency_key"],
        }

    def handle_a2a_request(self, *, payload, auth_token):  # noqa: ANN001
        raise AssertionError("not used in this test")


def test_a2a_capabilities_contract(monkeypatch) -> None:
    monkeypatch.setattr(routes, "get_orchestrator", lambda: StubOrchestrator())
    client = TestClient(routes.app)

    result = client.get("/.well-known/agent.json", headers={"X-Source-Agent-ID": "peer-1"})
    assert result.status_code == 200
    body = result.json()
    for key in ("agent_id", "version", "operations"):
        assert key in body
    assert isinstance(body["operations"], list)
    assert body["operations"][0]["operation_name"] == "list_users"


def test_a2a_capabilities_legacy_endpoint_contract(monkeypatch) -> None:
    monkeypatch.setattr(routes, "get_orchestrator", lambda: StubOrchestrator())
    client = TestClient(routes.app)

    result = client.get("/a2a/capabilities", headers={"X-Source-Agent-ID": "peer-1"})
    assert result.status_code == 200
    body = result.json()
    for key in ("agent_id", "version", "operations"):
        assert key in body
