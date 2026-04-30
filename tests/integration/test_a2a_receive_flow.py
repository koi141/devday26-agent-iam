from __future__ import annotations

import json

from iam_agent.application.a2a_collaboration_service import A2ACollaborationService
from iam_agent.application.input_guard import InputGuard
from iam_agent.application.retry_controller import RetryController
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.config.settings import Settings
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.infra.clients.a2a_peer_client import A2APeerClient
from iam_agent.infra.logging.audit_logger import AuditLogger


def _settings() -> Settings:
    return Settings(
        a2a_enabled=True,
        a2a_agent_id="iam-agent",
        a2a_peer_auth_token="peer-token",
        a2a_max_hops=3,
        a2a_peer_registry_json=json.dumps(
            [
                {
                    "agent_id": "peer-1",
                    "display_name": "Peer 1",
                    "trust_state": "trusted",
                    "base_url": "https://peer.example.com",
                    "supported_operations": ["list_users"],
                    "priority": 10,
                }
            ]
        ),
    )


def _service() -> A2ACollaborationService:
    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ユーザー一覧を取得しました。"],
            interpretation=["一覧取得に成功しました。"],
            proposal=["必要なら絞り込み条件を指定してください。"],
            data={"users": [{"id": "u1"}]},
            audit=AuditPayload(result="success"),
        )
    }
    return A2ACollaborationService(
        settings=_settings(),
        input_guard=InputGuard(),
        skill_executor=SkillExecutor(handlers=handlers),
        audit_logger=AuditLogger(),
        peer_client=A2APeerClient(_settings()),
        retry_controller=RetryController(max_attempts=3),
    )


def test_a2a_receive_trusted_peer_success() -> None:
    service = _service()
    response = service.execute(
        payload={
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
        auth_token="peer-token",
    )
    assert response.status == "success"
    assert response.audit.correlation_id == "corr-1"


def test_a2a_receive_rejects_untrusted_peer() -> None:
    service = _service()
    response = service.execute(
        payload={
            "request_id": "req-2",
            "correlation_id": "corr-2",
            "source_agent_id": "peer-unknown",
            "target_agent_id": "iam-agent",
            "requested_operation": "list_users",
            "objective": "一覧取得",
            "input_payload": {},
            "hop_count": 0,
            "visited_agents": [],
        },
        auth_token="peer-token",
    )
    assert response.status == "error"
    assert response.errors is not None
    assert response.errors[0].code == "peer_untrusted"


def test_a2a_receive_returns_missing_input_error() -> None:
    service = _service()
    response = service.execute(payload={"request_id": "req-3"}, auth_token="peer-token")
    assert response.status == "error"
    assert response.errors is not None
    assert response.errors[0].code == "missing_input"


def test_a2a_capabilities_requires_trusted_source_agent() -> None:
    service = _service()
    denied = service.capabilities(source_agent_id="", auth_token="")
    assert denied["error_code"] == "peer_untrusted"

    allowed = service.capabilities(source_agent_id="peer-1", auth_token="peer-token")
    assert allowed["agent_id"] == "iam-agent"
