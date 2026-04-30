from __future__ import annotations

import json

from iam_agent.application.a2a_collaboration_service import A2ACollaborationService
from iam_agent.application.errors import DelegationTimeoutError
from iam_agent.application.input_guard import InputGuard
from iam_agent.application.retry_controller import RetryController
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.config.settings import Settings
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.domain.models import PeerAgent
from iam_agent.infra.clients.a2a_peer_client import A2APeerClient
from iam_agent.infra.logging.audit_logger import AuditLogger


class FakePeerClient(A2APeerClient):
    def __init__(self, settings: Settings, mode: str = "success") -> None:
        super().__init__(settings)
        self.mode = mode

    def select_peer_for_operation(self, *, operation_name: str, exclude_agent_ids=None):  # noqa: ANN001
        peer = PeerAgent(
            agent_id="peer-1",
            display_name="Peer 1",
            trust_state="trusted",
            base_url="https://peer.example.com",
            supported_operations=[operation_name],
            priority=1,
        )
        return peer, [peer]

    def execute_delegation(self, *, peer, request_payload, auth_token="", timeout_seconds=12.0, max_retries=1):  # noqa: ANN001
        if self.mode == "timeout":
            raise DelegationTimeoutError("delegation timeout")
        if self.mode == "partial":
            return {
                "status": "partial_success",
                "facts": ["一部処理が成功しました。"],
                "interpretation": ["追加情報が不足しています。"],
                "proposal": ["不足情報を指定してください。"],
                "data": {"request_id": request_payload.get("request_id")},
            }
        return {
            "status": "success",
            "facts": ["委譲実行に成功しました。"],
            "interpretation": ["委譲先で処理が完了しました。"],
            "proposal": ["必要に応じて追加要求を行ってください。"],
            "data": {"request_id": request_payload.get("request_id")},
        }


def _service(mode: str) -> A2ACollaborationService:
    settings = Settings(
        a2a_enabled=True,
        a2a_agent_id="iam-agent",
        a2a_peer_registry_json=json.dumps([]),
    )
    handlers = {
        "list_users": lambda payload: NormalizedResponse.success(
            facts=["ok"],
            interpretation=["ok"],
            proposal=["ok"],
            data={},
            audit=AuditPayload(result="success"),
        )
    }
    return A2ACollaborationService(
        settings=settings,
        input_guard=InputGuard(),
        skill_executor=SkillExecutor(handlers=handlers),
        audit_logger=AuditLogger(),
        peer_client=FakePeerClient(settings=settings, mode=mode),
        retry_controller=RetryController(),
    )


def test_delegation_flow_success() -> None:
    service = _service("success")
    response = service.delegate_to_peer(
        {
            "objective": "一覧を取得",
            "requested_operation": "list_users",
            "input_payload": {},
        }
    )
    assert response.status == "success"
    assert response.audit.peer_agent == "peer-1"


def test_delegation_flow_timeout() -> None:
    service = _service("timeout")
    response = service.delegate_to_peer(
        {
            "objective": "一覧を取得",
            "requested_operation": "list_users",
            "input_payload": {},
        }
    )
    assert response.status == "error"
    assert response.errors is not None
    assert response.errors[0].code == "delegation_timeout"


def test_delegation_flow_partial_success() -> None:
    service = _service("partial")
    response = service.delegate_to_peer(
        {
            "objective": "一覧を取得",
            "requested_operation": "list_users",
            "input_payload": {},
        }
    )
    assert response.status == "partial_success"
