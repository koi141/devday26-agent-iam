from __future__ import annotations

import re
from typing import Any

from iam_agent.application.errors import classify_exception
from iam_agent.application.high_risk_guard import HIGH_RISK_TOOLS
from iam_agent.config.settings import Settings
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.infra.clients.oci_identity_client import OciIdentityClient
from iam_agent.infra.clients.oci_resource_search_client import OciResourceSearchClient
from iam_agent.infra.logging.redaction import redact_mapping, redact_resource_summaries
from iam_agent.tools.oci_iam.compartments import OciCompartmentTools
from iam_agent.tools.oci_iam.policies import OciPolicyTools
from iam_agent.tools.oci_iam.resources import OciResourceTools


class OciTools:
    def __init__(
        self,
        client: OciIdentityClient | None,
        settings: Settings,
        init_error: str = "",
        resource_search_client: OciResourceSearchClient | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.init_error = init_error
        self.resource_search_client = resource_search_client
        self.compartment_tools = OciCompartmentTools(client=client, settings=settings, init_error=init_error)
        self.resource_tools = OciResourceTools(
            client=client,
            resource_search_client=resource_search_client,
            settings=settings,
            init_error=init_error,
        )
        self.policy_tools = OciPolicyTools(client=client, settings=settings, init_error=init_error)

    def _ensure_client(self) -> OciIdentityClient:
        if self.client is None:
            detail = f" (reason: {self.init_error})" if self.init_error else ""
            raise RuntimeError(f"OCIクライアントが初期化されていません。{detail}")
        return self.client

    def _ensure_resource_search_client(self) -> OciResourceSearchClient:
        if self.resource_search_client is None:
            detail = f" (reason: {self.init_error})" if self.init_error else ""
            raise RuntimeError(f"OCI Resource Search クライアントが初期化されていません。{detail}")
        return self.resource_search_client

    def list_compartments(self, payload: dict[str, Any]) -> NormalizedResponse:
        self._ensure_a2a_high_risk_guard(payload=payload, operation_name="list_compartments")
        return self.compartment_tools.list_compartments(payload)
        compartment_id = payload.get("compartment_ocid") or self.settings.compartment_ocid
        include_subtree = bool(payload.get("include_subtree", True))
        include_inactive = bool(payload.get("include_inactive", False))
        access_level = str(payload.get("access_level") or "ANY")
        output_format = str(payload.get("output_format") or "tree").strip().lower()
        max_depth_raw = payload.get("max_depth")
        max_depth: int | None = None

        if output_format not in {"tree", "json"}:
            return NormalizedResponse.error(
                message="output_format は tree または json を指定してください。",
                code="invalid_argument",
                retryable=False,
                proposal=["output_format に tree または json を指定して再実行してください。"],
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "compartments"},
                    input_summary={"output_format": output_format},
                    decision_reason=["無効な出力形式"],
                    result="error",
                ),
            )

        if max_depth_raw not in (None, ""):
            try:
                max_depth = int(max_depth_raw)
            except Exception:
                return NormalizedResponse.error(
                    message="max_depth は 0 以上の整数で指定してください。",
                    code="invalid_argument",
                    retryable=False,
                    proposal=["max_depth を整数で指定して再実行してください。"],
                    audit=AuditPayload(
                        target={"service": "oci.identity", "resource": "compartments"},
                        input_summary={"max_depth": max_depth_raw},
                        decision_reason=["無効な深度指定"],
                        result="error",
                    ),
                )
            if max_depth < 0:
                return NormalizedResponse.error(
                    message="max_depth は 0 以上で指定してください。",
                    code="invalid_argument",
                    retryable=False,
                    proposal=["max_depth を 0 以上の値で指定して再実行してください。"],
                    audit=AuditPayload(
                        target={"service": "oci.identity", "resource": "compartments"},
                        input_summary={"max_depth": max_depth},
                        decision_reason=["無効な深度指定"],
                        result="error",
                    ),
                )

        if not str(compartment_id or "").strip():
            return NormalizedResponse.error(
                message=(
                    "不足項目: compartment_ocid / 影響: list_resources を実行できません。"
                    " / 次アクション: compartment_ocid を指定して再実行してください。"
                ),
                code="missing_input",
                retryable=False,
                proposal=["compartment_ocid を指定して再実行してください。"],
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "compartments"},
                    input_summary={"compartment_ocid": compartment_id},
                    decision_reason=["必須入力不足"],
                    result="error",
                ),
            )

        try:
            compartments = self._ensure_client().list_compartments(
                compartment_id=compartment_id,
                include_subtree=include_subtree,
                access_level=access_level,
                include_inactive=include_inactive,
                max_depth=max_depth,
            )
            normalized = self._normalize_compartment_nodes(
                compartments=compartments,
                root_compartment_id=str(compartment_id),
            )
            tree_lines = self._build_compartment_tree_lines(normalized) if output_format == "tree" else []
            excluded_states = [] if include_inactive else ["INACTIVE", "DELETED"]
            return NormalizedResponse.success(
                facts=[
                    f"コンパートメント {len(normalized)} 件を取得しました。",
                    f"対象起点: {compartment_id}",
                    *([f"inactive/deleted は除外しました。"] if excluded_states else []),
                ],
                interpretation=[
                    "階層情報は depth と path で確認できます。",
                    *(
                        ["tree_lines を使うとインデント付きで階層を確認できます。"]
                        if output_format == "tree"
                        else ["json 形式で機械処理しやすい構造を返しています。"]
                    ),
                ],
                proposal=[
                    "必要なら max_depth を指定して深度を制限してください。",
                    "inactive を含める場合は include_inactive=true を指定してください。",
                ],
                data={
                    "root_compartment_ocid": str(compartment_id),
                    "output_format": output_format,
                    "total_count": len(normalized),
                    "excluded_states": excluded_states,
                    "compartments": normalized,
                    **({"tree_lines": tree_lines} if tree_lines else {}),
                },
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "compartments"},
                    input_summary={
                        "compartment_ocid": compartment_id,
                        "include_subtree": include_subtree,
                        "include_inactive": include_inactive,
                        "max_depth": max_depth,
                        "output_format": output_format,
                    },
                    decision_reason=["list_compartments 実行"],
                    result="success",
                ),
            )
        except Exception as exc:
            app_error = classify_exception(exc)
            return NormalizedResponse.error(
                message=app_error.message,
                code=app_error.code,
                retryable=app_error.retryable,
                proposal=["権限と compartment_ocid を確認してください。"],
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "compartments"},
                    input_summary={
                        "compartment_ocid": compartment_id,
                        "include_subtree": include_subtree,
                        "include_inactive": include_inactive,
                        "max_depth": max_depth,
                        "output_format": output_format,
                    },
                    decision_reason=["list_compartments 失敗"],
                    result="error",
                ),
            )

    def list_resources(self, payload: dict[str, Any]) -> NormalizedResponse:
        self._ensure_a2a_high_risk_guard(payload=payload, operation_name="list_resources")
        return self.resource_tools.list_resources(payload)
        compartment_id = payload.get("compartment_ocid") or self.settings.compartment_ocid
        include_subtree = bool(payload.get("include_subtree", False))
        resource_type = str(payload.get("resource_type") or "").strip()
        raw_limit = payload.get("limit", 200)

        if not str(compartment_id or "").strip():
            return NormalizedResponse.error(
                message="compartment_ocid が必要です。",
                code="missing_input",
                retryable=False,
                proposal=["compartment_ocid を指定して再実行してください。"],
                audit=AuditPayload(
                    target={"service": "oci.resource_search", "resource": "resources"},
                    input_summary={"compartment_ocid": compartment_id},
                    decision_reason=["必須入力不足"],
                    result="error",
                ),
            )

        try:
            limit = int(raw_limit)
        except Exception:
            return NormalizedResponse.error(
                message=(
                    "不足または不正な入力: limit / 影響: list_resources の取得件数を確定できません。"
                    " / 次アクション: limit を 1 以上の整数で指定してください。"
                ),
                code="invalid_argument",
                retryable=False,
                proposal=["limit を 1 以上の整数で指定して再実行してください。"],
                audit=AuditPayload(
                    target={"service": "oci.resource_search", "resource": "resources"},
                    input_summary={"limit": raw_limit},
                    decision_reason=["無効な limit"],
                    result="error",
                ),
            )
        if limit <= 0:
            return NormalizedResponse.error(
                message=(
                    "不正な入力: limit / 影響: list_resources を実行できません。"
                    " / 次アクション: limit を 1 以上で指定して再実行してください。"
                ),
                code="invalid_argument",
                retryable=False,
                proposal=["limit を 1 以上で指定して再実行してください。"],
                audit=AuditPayload(
                    target={"service": "oci.resource_search", "resource": "resources"},
                    input_summary={"limit": limit},
                    decision_reason=["無効な limit"],
                    result="error",
                ),
            )

        target_compartment_ids = [str(compartment_id)]
        if include_subtree:
            try:
                descendants = self._ensure_client().list_compartments(
                    compartment_id=str(compartment_id),
                    include_subtree=True,
                    access_level="ANY",
                    include_inactive=True,
                    max_depth=None,
                )
            except Exception as exc:
                app_error = classify_exception(exc)
                return NormalizedResponse.error(
                    message=app_error.message,
                    code=app_error.code,
                    retryable=app_error.retryable,
                    proposal=["compartment_ocid と不足権限(inspect compartments)を確認してください。"],
                    audit=AuditPayload(
                        target={"service": "oci.identity", "resource": "compartments"},
                        input_summary={"compartment_ocid": compartment_id, "include_subtree": include_subtree},
                        decision_reason=["list_resources 前提のコンパートメント取得失敗"],
                        result="error",
                    ),
                )

            for item in descendants:
                cid = str(item.get("id") or item.get("compartment_ocid") or "")
                if cid and cid not in target_compartment_ids:
                    target_compartment_ids.append(cid)

        resources: list[dict[str, Any]] = []
        visibility_warnings: list[dict[str, Any]] = []
        not_retrieved_resource_types: set[str] = set()
        seen_resource_ids: set[str] = set()
        remaining = limit

        for cid in target_compartment_ids:
            if remaining <= 0:
                break
            try:
                searched = self._ensure_resource_search_client().list_resources(
                    compartment_id=cid,
                    resource_type=resource_type,
                    limit=remaining,
                )
            except Exception as exc:
                app_error = classify_exception(exc)
                if app_error.code == "permission_denied":
                    visibility_warnings.append(
                        {
                            "warning_type": "permission_gap",
                            "affected_scope": cid,
                            "detail": app_error.message,
                            "next_actions": [
                                "対象コンパートメントへの inspect 権限を確認してください。",
                                "権限を縮小した範囲で再実行してください。",
                            ],
                        }
                    )
                    not_retrieved_resource_types.add(resource_type or "all")
                    continue

                return NormalizedResponse.error(
                    message=app_error.message,
                    code=app_error.code,
                    retryable=app_error.retryable,
                    proposal=["一時障害の可能性がある場合は再試行してください。"],
                    audit=AuditPayload(
                        target={"service": "oci.resource_search", "resource": "resources"},
                        input_summary={
                            "compartment_ocid": compartment_id,
                            "current_compartment_ocid": cid,
                            "include_subtree": include_subtree,
                            "resource_type": resource_type,
                            "limit": limit,
                        },
                        decision_reason=["list_resources 失敗"],
                        result="error",
                    ),
                )

            for item in searched:
                normalized = self._normalize_resource_summary(
                    item=item,
                    fallback_compartment_ocid=cid,
                )
                normalized = redact_mapping(normalized)
                resource_id = str(normalized.get("resource_ocid") or "")
                dedupe_key = resource_id or f"{normalized.get('resource_type')}:{normalized.get('display_name')}"
                if dedupe_key in seen_resource_ids:
                    continue
                seen_resource_ids.add(dedupe_key)
                resources.append(normalized)
                remaining = limit - len(resources)
                if remaining <= 0:
                    break

        partial = len(visibility_warnings) > 0
        facts = [f"リソース {len(resources)} 件を取得しました。"]
        if partial:
            facts.append(f"権限制約により {len(visibility_warnings)} スコープで部分取得となりました。")

        interpretation = (
            ["取得可能な範囲のみ返却し、未取得範囲は visibility_warnings へ記録しました。"]
            if partial
            else ["指定範囲のリソース一覧を取得しました。"]
        )
        proposal = (
            [
                "不足権限(inspect/read)を確認するか、compartment_ocid を絞って再実行してください。",
                "必要に応じて resource_type で絞り込んで再実行してください。",
            ]
            if partial
            else ["必要に応じて include_subtree=true や resource_type 指定で再検索してください。"]
        )

        data: dict[str, Any] = {
            "target_compartment_ocid": str(compartment_id),
            "include_subtree": include_subtree,
            "returned_count": len(resources),
            "resources": resources,
        }
        if visibility_warnings:
            data["visibility_warnings"] = redact_resource_summaries(visibility_warnings)
        if not_retrieved_resource_types:
            data["not_retrieved_resource_types"] = sorted(not_retrieved_resource_types)

        return NormalizedResponse.success(
            facts=facts,
            interpretation=interpretation,
            proposal=proposal,
            data=data,
            meta={"partial_result": partial},
            audit=AuditPayload(
                target={"service": "oci.resource_search", "resource": "resources"},
                input_summary={
                    "compartment_ocid": compartment_id,
                    "include_subtree": include_subtree,
                    "resource_type": resource_type,
                    "limit": limit,
                    "searched_compartments": target_compartment_ids,
                },
                decision_reason=["list_resources 実行"],
                result="success",
            ),
        )

    def list_policies(self, payload: dict[str, Any]) -> NormalizedResponse:
        self._ensure_a2a_high_risk_guard(payload=payload, operation_name="list_policies")
        return self.policy_tools.list_policies(payload)
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
        self._ensure_a2a_high_risk_guard(payload=payload, operation_name="get_policy")
        return self.policy_tools.get_policy(payload)
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
        return self.policy_tools.collect_policy_evidence(payload)
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
            if re.search(rf"\bgroup\s+['\"]?{re.escape(normalized)}['\"]?\b", lowered):
                matched.append(group)
                continue
            # ドメイン付き形式 group 'domain'/'group'
            if f"/{normalized}" in lowered or f"/'{normalized}'" in lowered or f'/\"{normalized}\"' in lowered:
                matched.append(group)
        return matched

    @staticmethod
    def _compartment_item_id(item: dict[str, Any]) -> str:
        return str(item.get("id") or item.get("compartment_ocid") or "")

    @staticmethod
    def _compartment_parent_id(item: dict[str, Any]) -> str:
        return str(
            item.get("compartment_id")
            or item.get("compartmentId")
            or item.get("parent_compartment_ocid")
            or ""
        )

    def _normalize_compartment_nodes(
        self,
        *,
        compartments: list[dict[str, Any]],
        root_compartment_id: str,
    ) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for raw in compartments:
            if not isinstance(raw, dict):
                continue
            cid = self._compartment_item_id(raw)
            if not cid:
                continue
            depth_value = raw.get("_depth")
            depth: int | None
            try:
                depth = int(depth_value) if depth_value is not None else None
            except Exception:
                depth = None

            by_id[cid] = {
                "name": str(raw.get("name") or raw.get("display_name") or cid),
                "compartment_ocid": cid,
                "parent_compartment_ocid": self._compartment_parent_id(raw),
                "lifecycle_state": str(raw.get("lifecycle_state") or raw.get("lifecycleState") or "UNKNOWN"),
                "_depth": depth,
            }

        for cid, node in by_id.items():
            if node["_depth"] is None:
                node["_depth"] = self._resolve_compartment_depth(
                    compartment_id=cid,
                    by_id=by_id,
                    root_compartment_id=root_compartment_id,
                )
            node["depth"] = int(node["_depth"] or 0)
            node["path"] = self._resolve_compartment_path(
                compartment_id=cid,
                by_id=by_id,
                root_compartment_id=root_compartment_id,
            )
            node.pop("_depth", None)

        nodes = list(by_id.values())
        nodes.sort(key=lambda item: (int(item.get("depth") or 0), str(item.get("path") or ""), str(item.get("name") or "")))
        return nodes

    def _resolve_compartment_depth(
        self,
        *,
        compartment_id: str,
        by_id: dict[str, dict[str, Any]],
        root_compartment_id: str,
    ) -> int:
        depth = 0
        current = by_id.get(compartment_id, {})
        seen: set[str] = {compartment_id}
        while True:
            parent_id = str(current.get("parent_compartment_ocid") or "")
            if not parent_id or parent_id in seen:
                break
            seen.add(parent_id)
            depth += 1
            if parent_id == root_compartment_id:
                break
            parent = by_id.get(parent_id)
            if not isinstance(parent, dict):
                break
            current = parent
        return max(depth, 0)

    def _resolve_compartment_path(
        self,
        *,
        compartment_id: str,
        by_id: dict[str, dict[str, Any]],
        root_compartment_id: str,
    ) -> str:
        names: list[str] = []
        current_id = compartment_id
        seen: set[str] = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            node = by_id.get(current_id)
            if not isinstance(node, dict):
                names.insert(0, current_id)
                break
            names.insert(0, str(node.get("name") or current_id))
            parent_id = str(node.get("parent_compartment_ocid") or "")
            if not parent_id:
                break
            if current_id == root_compartment_id:
                break
            current_id = parent_id
        return "/".join(name for name in names if name)

    @staticmethod
    def _build_compartment_tree_lines(compartments: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for item in compartments:
            depth = int(item.get("depth") or 0)
            name = str(item.get("name") or item.get("compartment_ocid") or "")
            cid = str(item.get("compartment_ocid") or "")
            lifecycle = str(item.get("lifecycle_state") or "UNKNOWN")
            indent = "  " * max(depth, 0)
            lines.append(f"{indent}- {name} ({cid}) [{lifecycle}]")
        return lines

    @staticmethod
    def _normalize_resource_summary(*, item: dict[str, Any], fallback_compartment_ocid: str) -> dict[str, Any]:
        display_name = str(
            item.get("display_name")
            or item.get("displayName")
            or item.get("name")
            or item.get("identifier")
            or item.get("id")
            or "UNKNOWN"
        )
        resource_type = str(item.get("resource_type") or item.get("resourceType") or "UNKNOWN")
        resource_ocid = str(item.get("identifier") or item.get("resource_ocid") or item.get("id") or "")
        compartment_ocid = str(item.get("compartment_id") or item.get("compartmentId") or fallback_compartment_ocid)
        lifecycle_state = str(item.get("lifecycle_state") or item.get("lifecycleState") or "UNKNOWN")

        normalized: dict[str, Any] = {
            "display_name": display_name,
            "resource_type": resource_type,
            "resource_ocid": resource_ocid,
            "compartment_ocid": compartment_ocid,
            "lifecycle_state": lifecycle_state,
        }
        availability_domain = str(item.get("availability_domain") or item.get("availabilityDomain") or "")
        region = str(item.get("region") or "")
        if availability_domain:
            normalized["availability_domain"] = availability_domain
        if region:
            normalized["region"] = region
        return normalized

    @staticmethod
    def _ensure_a2a_high_risk_guard(*, payload: dict[str, Any], operation_name: str) -> None:
        context = payload.get("__a2a_context")
        if not isinstance(context, dict):
            return
        if operation_name not in HIGH_RISK_TOOLS:
            return
        idempotency_key = str(context.get("idempotency_key") or "").strip()
        if idempotency_key:
            return
        raise RuntimeError(f"A2A経由の高リスク操作 `{operation_name}` には idempotency_key が必要です。")
