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


def test_a2a_idempotency_prevents_duplicate_high_risk_execution() -> None:
    counter = {"create_user_calls": 0}

    def _create_user(payload):  # noqa: ANN001
        counter["create_user_calls"] += 1
        return NormalizedResponse.success(
            facts=["ユーザーを作成しました。"],
            interpretation=["高リスク操作として監査対象です。"],
            proposal=["必要に応じて権限を設定してください。"],
            data={"user_id": "u1"},
            audit=AuditPayload(result="success"),
        )

    settings = Settings(
        a2a_enabled=True,
        a2a_agent_id="iam-agent",
        a2a_peer_auth_token="peer-token",
        a2a_peer_registry_json=json.dumps(
            [
                {
                    "agent_id": "peer-1",
                    "trust_state": "trusted",
                    "base_url": "https://peer.example.com",
                    "supported_operations": ["create_user"],
                    "priority": 1,
                }
            ]
        ),
    )

    service = A2ACollaborationService(
        settings=settings,
        input_guard=InputGuard(),
        skill_executor=SkillExecutor(handlers={"create_user": _create_user}),
        audit_logger=AuditLogger(),
        peer_client=A2APeerClient(settings=settings),
        retry_controller=RetryController(),
    )

    payload = {
        "request_id": "req-1",
        "correlation_id": "corr-1",
        "source_agent_id": "peer-1",
        "target_agent_id": "iam-agent",
        "requested_operation": "create_user",
        "objective": "ユーザー作成",
        "input_payload": {"family_name": "山田", "given_name": "太郎", "email": "yamada@example.com"},
        "idempotency_key": "idem-1",
        "hop_count": 0,
        "visited_agents": [],
    }

    first = service.execute(payload=payload, auth_token="peer-token")
    second = service.execute(payload=payload, auth_token="peer-token")

    assert first.status == "success"
    assert second.status == "success"
    assert counter["create_user_calls"] == 1
    assert any("idempotency_key" in line for line in second.facts)
    assert second.audit.correlation_id == "corr-1"
