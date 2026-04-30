from __future__ import annotations

import re
from typing import Any

from iam_agent.application.errors import classify_exception
from iam_agent.config.settings import Settings
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.infra.clients.oci_identity_client import OciIdentityClient


class OciPolicyTools:
    def __init__(self, *, client: OciIdentityClient | None, settings: Settings, init_error: str = "") -> None:
        self.client = client
        self.settings = settings
        self.init_error = init_error

    def _ensure_client(self) -> OciIdentityClient:
        if self.client is None:
            detail = f" (reason: {self.init_error})" if self.init_error else ""
            raise RuntimeError(f"OCIクライアントが初期化されていません。{detail}")
        return self.client

    def list_policies(self, payload: dict[str, Any]) -> NormalizedResponse:
        compartment_id = payload.get("compartment_ocid") or self.settings.compartment_ocid
        include_subtree = bool(payload.get("include_subtree", False))
        if not str(compartment_id or "").strip():
            return NormalizedResponse.error(
                message="compartment_ocid が必要です。",
                code="missing_input",
                retryable=False,
                proposal=["compartment_ocid を指定して再実行してください。"],
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "policies"},
                    input_summary={"compartment_ocid": compartment_id},
                    decision_reason=["必須入力不足"],
                    result="error",
                ),
            )

        try:
            policies = self._ensure_client().list_policies(
                compartment_id=compartment_id,
                include_subtree=include_subtree,
            )
            return NormalizedResponse.success(
                facts=[f"ポリシー {len(policies)} 件を取得しました。"],
                interpretation=["ステートメントを確認して権限範囲を判断してください。"],
                proposal=["必要なら include_subtree=true で再検索してください。"],
                data={"policies": policies},
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "policies"},
                    input_summary={"compartment_ocid": compartment_id, "include_subtree": include_subtree},
                    decision_reason=["list_policies 実行"],
                    result="success",
                ),
            )
        except Exception as exc:
            app_error = classify_exception(exc)
            return NormalizedResponse.error(
                message=app_error.message,
                code=app_error.code,
                retryable=app_error.retryable,
                proposal=["不足権限(inspect/read policies)を確認してください。"],
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "policies"},
                    input_summary={"compartment_ocid": compartment_id},
                    decision_reason=["list_policies 失敗"],
                    result="error",
                ),
            )

    def get_policy(self, payload: dict[str, Any]) -> NormalizedResponse:
        policy_id = str(payload.get("policy_id") or "").strip()
        policy_name = str(payload.get("policy_name") or payload.get("name") or "").strip()
        resolved_from_name = False
        if not policy_id and policy_name:
            compartment_id = payload.get("compartment_ocid") or self.settings.compartment_ocid
            include_subtree = bool(payload.get("include_subtree", True))
            if not str(compartment_id or "").strip():
                return NormalizedResponse.error(
                    message="policy_name 指定時は compartment_ocid が必要です。",
                    code="missing_input",
                    retryable=False,
                    proposal=["compartment_ocid または policy_id を指定して再実行してください。"],
                    audit=AuditPayload(
                        target={"service": "oci.identity", "resource": "policy"},
                        input_summary={"policy_name": policy_name},
                        decision_reason=["必須入力不足"],
                        result="error",
                    ),
                )
            try:
                resolved = self._resolve_policy_candidates(
                    policy_name=policy_name,
                    compartment_id=str(compartment_id),
                    include_subtree=include_subtree,
                )
            except Exception as exc:
                app_error = classify_exception(exc)
                return NormalizedResponse.error(
                    message=app_error.message,
                    code=app_error.code,
                    retryable=app_error.retryable,
                    proposal=["policy_name と権限(read policies)を確認してください。"],
                    audit=AuditPayload(
                        target={"service": "oci.identity", "resource": "policy"},
                        input_summary={"policy_name": policy_name},
                        decision_reason=["policy_name から policy_id 解決失敗"],
                        result="error",
                    ),
                )

            if len(resolved) == 0:
                return NormalizedResponse.error(
                    message=f"policy_name `{policy_name}` に一致するポリシーが見つかりません。",
                    code="not_found",
                    retryable=False,
                    proposal=["ポリシー名を確認するか list_policies で候補を確認してください。"],
                    audit=AuditPayload(
                        target={"service": "oci.identity", "resource": "policy"},
                        input_summary={"policy_name": policy_name},
                        decision_reason=["policy_name 一致なし"],
                        result="error",
                    ),
                )
            if len(resolved) > 1:
                return NormalizedResponse.needs_confirmation(
                    facts=["指定名に一致するポリシー候補が複数見つかりました。"],
                    interpretation=["自動選択せず、候補の確認が必要です。"],
                    proposal=["policy_id を指定して再実行してください。"],
                    data={
                        "policy_name": policy_name,
                        "candidates": [
                            {
                                "policy_id": item.get("id"),
                                "policy_name": item.get("name"),
                                "compartment_id": item.get("compartment_id"),
                            }
                            for item in resolved
                        ],
                    },
                    audit=AuditPayload(
                        target={"service": "oci.identity", "resource": "policy"},
                        input_summary={"policy_name": policy_name},
                        decision_reason=["policy_name 一致候補複数"],
                        result="needs_confirmation",
                    ),
                )
            policy_id = str(resolved[0].get("id") or "").strip()
            resolved_from_name = True

        if not policy_id:
            return NormalizedResponse.error(
                message="policy_id または policy_name が必要です。",
                code="missing_input",
                retryable=False,
                proposal=["policy_id または policy_name を指定して再実行してください。"],
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "policy"},
                    input_summary={"policy_id": "", "policy_name": policy_name},
                    decision_reason=["必須入力不足"],
                    result="error",
                ),
            )

        try:
            policy = self._ensure_client().get_policy(policy_id=policy_id)
            return NormalizedResponse.success(
                facts=["ポリシー詳細を取得しました。"],
                interpretation=["statement を確認して権限範囲を判断してください。"],
                proposal=["必要なら list_policies と併せて比較してください。"],
                data={
                    "policy": policy,
                    "resolved_from_name": resolved_from_name,
                    "requested_policy_name": policy_name,
                },
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "policy", "policy_id": policy_id},
                    input_summary={
                        "policy_id": policy_id,
                        "policy_name": policy_name,
                        "resolved_from_name": resolved_from_name,
                    },
                    decision_reason=["get_policy 実行"],
                    result="success",
                ),
            )
        except Exception as exc:
            app_error = classify_exception(exc)
            return NormalizedResponse.error(
                message=app_error.message,
                code=app_error.code,
                retryable=app_error.retryable,
                proposal=["policy_id と権限(read policies)を確認してください。"],
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "policy", "policy_id": policy_id},
                    input_summary={"policy_id": policy_id},
                    decision_reason=["get_policy 失敗"],
                    result="error",
                ),
            )

    def _resolve_policy_candidates(
        self,
        *,
        policy_name: str,
        compartment_id: str,
        include_subtree: bool,
    ) -> list[dict[str, Any]]:
        policies = self._ensure_client().list_policies(
            compartment_id=compartment_id,
            include_subtree=include_subtree,
        )
        exact: list[dict[str, Any]] = []
        partial: list[dict[str, Any]] = []
        normalized = policy_name.lower()
        for item in policies:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            lowered = name.lower()
            if lowered == normalized:
                exact.append(item)
                continue
            if normalized in lowered:
                partial.append(item)
        if exact:
            return exact
        return partial

    def collect_policy_evidence(self, payload: dict[str, Any]) -> NormalizedResponse:
        group_names = payload.get("group_names") or []
        if not isinstance(group_names, list):
            group_names = []
        list_result = self.list_policies(payload)
        if list_result.status != "success":
            return list_result

        policies = (list_result.data or {}).get("policies", [])
        matched: list[dict[str, Any]] = []
        constraints: list[dict[str, Any]] = []
        for policy in policies:
            statements = policy.get("statements") or []
            if not isinstance(statements, list):
                continue
            for statement in statements:
                if not isinstance(statement, str):
                    continue
                matched_groups = self._extract_matched_groups(statement=statement, group_names=group_names)
                if not matched_groups:
                    continue
                action = self._extract_action(statement)
                matched.append(
                    {
                        "policy_id": policy.get("id"),
                        "policy_name": policy.get("name"),
                        "statement": statement,
                        "matched_groups": matched_groups,
                        "action": action,
                    }
                )
                if "where " in statement.lower():
                    constraints.append(
                        {
                            "policy_id": policy.get("id"),
                            "constraint_type": "condition",
                            "constraint_value": statement.split("where", 1)[-1].strip(),
                            "applies_to": matched_groups,
                        }
                    )

        return NormalizedResponse.success(
            facts=[f"ポリシー根拠 {len(matched)} 件、制約根拠 {len(constraints)} 件を抽出しました。"],
            interpretation=["グループ名一致を軸にポリシーステートメントを関連付けました。"],
            proposal=["必要なら get_policy で個別ポリシーを確認してください。"],
            data={
                "policy_evidence": matched,
                "constraint_evidence": constraints,
            },
            audit=AuditPayload(
                target={"service": "oci.identity", "resource": "policy_evidence"},
                input_summary={"group_names": group_names},
                decision_reason=["collect_policy_evidence 実行"],
                result="success",
            ),
        )

    @staticmethod
    def _extract_action(statement: str) -> str:
        lowered = statement.lower()
        for action in ("manage", "use", "read", "inspect"):
            if f" {action} " in lowered:
                return action
        return "unknown"

    @staticmethod
    def _extract_matched_groups(*, statement: str, group_names: list[str]) -> list[str]:
        lowered = statement.lower()
        matched: list[str] = []
        for group in group_names:
            if not group:
                continue
            normalized = group.lower()
            if re.search(rf"\\bgroup\\s+['\"]?{re.escape(normalized)}['\"]?\\b", lowered):
                matched.append(group)
                continue
            if f"/{normalized}" in lowered or f"/'{normalized}'" in lowered or f'/\"{normalized}\"' in lowered:
                matched.append(group)
        return matched
