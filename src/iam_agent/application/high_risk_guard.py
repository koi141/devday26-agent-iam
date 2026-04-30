from __future__ import annotations

from typing import Any, Sequence

from iam_agent.application.errors import AmbiguousTargetError, AppError


HIGH_RISK_TOOLS = {"create_user", "add_user_to_group", "remove_user_from_group"}


def ensure_unique(resources: Sequence[dict[str, Any]], resource_name: str) -> dict[str, Any]:
    if len(resources) == 1:
        return resources[0]
    if not resources:
        raise AppError(code="not_found", message=f"{resource_name} が見つかりません。", retryable=False)
    raise AmbiguousTargetError(f"{resource_name} が複数見つかりました。候補を1件に絞ってください。")


def ensure_membership_change_allowed(user_unique: bool, group_unique: bool) -> None:
    if user_unique and group_unique:
        return
    raise AmbiguousTargetError("ユーザーまたはグループを一意特定できないため所属変更を実行できません。")


def is_high_risk(tool_name: str) -> bool:
    return tool_name in HIGH_RISK_TOOLS


def ensure_read_only_investigation(request_type: str, tool_name: str) -> None:
    if request_type in {"permission_investigation", "access_denial_troubleshooting"} and is_high_risk(tool_name):
        raise AppError(
            code="high_risk_blocked",
            message=f"調査フローでは高リスク操作 `{tool_name}` を自動実行できません。",
            retryable=False,
        )


def constrain_remediation_proposals(proposals: Sequence[str]) -> list[str]:
    constrained: list[str] = []
    for proposal in proposals:
        normalized = proposal.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if any(keyword in lowered for keyword in ("ocid", "policy_id", "group_id", "user_id")):
            # 内部識別子に依存しない利用者向け提案へ寄せる
            continue
        constrained.append(normalized)
    if constrained:
        return constrained
    return ["管理画面で対象ユーザー・対象リソースを指定し、権限設定を見直してください。"]
