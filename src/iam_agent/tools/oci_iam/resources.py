from __future__ import annotations

from typing import Any

from iam_agent.application.errors import classify_exception
from iam_agent.config.settings import Settings
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.infra.clients.oci_identity_client import OciIdentityClient
from iam_agent.infra.clients.oci_resource_search_client import OciResourceSearchClient
from iam_agent.infra.logging.redaction import redact_mapping, redact_resource_summaries


class OciResourceTools:
    def __init__(
        self,
        *,
        client: OciIdentityClient | None,
        resource_search_client: OciResourceSearchClient | None,
        settings: Settings,
        init_error: str = "",
    ) -> None:
        self.client = client
        self.resource_search_client = resource_search_client
        self.settings = settings
        self.init_error = init_error

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

    def list_resources(self, payload: dict[str, Any]) -> NormalizedResponse:
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
                normalized = self._normalize_resource_summary(item=item, fallback_compartment_ocid=cid)
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
