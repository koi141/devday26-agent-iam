from __future__ import annotations

import pytest

from iam_agent.application.errors import AppError
from iam_agent.application.high_risk_guard import constrain_remediation_proposals, ensure_read_only_investigation, is_high_risk
from iam_agent.infra.clients.identity_domain_client import IdentityDomainClient
from iam_agent.tools.identity_domain_tools import IdentityDomainTools


class DummyIdentityClient(IdentityDomainClient):
    def __init__(self) -> None:
        pass


def test_ensure_read_only_investigation_blocks_high_risk_tool() -> None:
    with pytest.raises(AppError) as exc:
        ensure_read_only_investigation("permission_investigation", "create_user")

    assert exc.value.code == "high_risk_blocked"


def test_is_high_risk_includes_user_write_operations() -> None:
    assert is_high_risk("create_user") is True
    assert is_high_risk("add_user_to_group") is True
    assert is_high_risk("remove_user_from_group") is True


def test_constrain_remediation_proposals_removes_internal_identifiers() -> None:
    proposals = [
        "policy_id を指定して再実行してください。",
        "管理画面で対象ユーザーの権限設定を見直してください。",
    ]
    constrained = constrain_remediation_proposals(proposals)

    assert all("policy_id" not in item for item in constrained)
    assert any("管理画面" in item for item in constrained)


def test_identity_domain_high_risk_requires_idempotency_on_a2a() -> None:
    tools = IdentityDomainTools(client=DummyIdentityClient())

    with pytest.raises(AppError) as exc:
        tools.create_user(
            {
                "family_name": "田中",
                "given_name": "太郎",
                "email": "taro.tanaka@example.com",
                "__a2a_context": {
                    "source_agent_id": "peer-1",
                    "idempotency_key": "",
                },
            }
        )

    assert exc.value.code == "idempotency_conflict"
