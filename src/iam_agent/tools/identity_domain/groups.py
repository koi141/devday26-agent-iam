from __future__ import annotations

from typing import Any

from iam_agent.application.errors import classify_exception
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.infra.clients.identity_domain_client import IdentityDomainClient
from iam_agent.tools.target_resolution import extract_resources


class IdentityDomainGroupTools:
    def __init__(self, client: IdentityDomainClient) -> None:
        self.client = client

    def list_groups(self, payload: dict[str, Any]) -> NormalizedResponse:
        try:
            response = self.list_groups_raw(
                filter_expr=payload.get("filter"),
                start_index=payload.get("start_index"),
                count=payload.get("count"),
                sort_by=payload.get("sort_by"),
                sort_order=payload.get("sort_order"),
                attributes=payload.get("attributes"),
            )
            groups = extract_resources(response)
            return NormalizedResponse.success(
                facts=[f"グループ {len(groups)} 件を取得しました。"],
                interpretation=["検索条件に一致するグループ一覧です。"],
                proposal=["メンバー確認時は attributes に members を指定してください。"],
                data={"groups": groups, "total_results": response.get("totalResults", len(groups))},
                audit=AuditPayload(
                    target={"resource": "Groups"},
                    input_summary={
                        k: payload.get(k)
                        for k in ("filter", "start_index", "count", "sort_by", "sort_order", "attributes")
                    },
                    decision_reason=["list_groups 実行"],
                    result="success",
                ),
            )
        except Exception as exc:
            app_error = classify_exception(exc)
            return NormalizedResponse.error(
                message=app_error.message,
                code=app_error.code,
                retryable=app_error.retryable,
                proposal=["入力条件・権限・認証情報を確認して再実行してください。"],
                audit=AuditPayload(
                    target={"resource": "Groups"},
                    input_summary={"keys": sorted(payload.keys())},
                    decision_reason=["list_groups 失敗"],
                    result="error",
                ),
            )

    def get_group(self, payload: dict[str, Any]) -> NormalizedResponse:
        group_id = str(payload.get("group_id") or "").strip()
        if not group_id:
            return NormalizedResponse.error(
                message="group_id が必要です。",
                code="missing_input",
                retryable=False,
                proposal=["group_id を指定して再実行してください。"],
                audit=AuditPayload(
                    target={"resource": "Groups"},
                    input_summary={"missing": "group_id"},
                    decision_reason=["必須入力不足"],
                    result="error",
                ),
            )

        attributes = payload.get("attributes")
        if payload.get("include_members") and not attributes:
            attributes = ["members"]

        try:
            group = self.get_group_raw(group_id=group_id, attributes=attributes)
            return NormalizedResponse.success(
                facts=["グループ詳細を取得しました。"],
                interpretation=["対象グループの現在状態です。"],
                proposal=["メンバーを確認する場合は attributes=members を指定してください。"],
                data={"group": group},
                audit=AuditPayload(
                    target={"resource": "Groups", "group_id": group_id},
                    input_summary={"group_id": group_id, "attributes": attributes},
                    decision_reason=["get_group 実行"],
                    result="success",
                ),
            )
        except Exception as exc:
            app_error = classify_exception(exc)
            return NormalizedResponse.error(
                message=app_error.message,
                code=app_error.code,
                retryable=app_error.retryable,
                proposal=["入力条件・権限・認証情報を確認して再実行してください。"],
                audit=AuditPayload(
                    target={"resource": "Groups"},
                    input_summary={"keys": sorted(payload.keys())},
                    decision_reason=["get_group 失敗"],
                    result="error",
                ),
            )

    def list_groups_raw(
        self,
        *,
        filter_expr: str | None = None,
        start_index: int | None = None,
        count: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.client.list_groups(
            filter_expr=filter_expr,
            start_index=start_index,
            count=count,
            sort_by=sort_by,
            sort_order=sort_order,
            attributes=attributes,
        )

    def get_group_raw(self, *, group_id: str, attributes: list[str] | None = None) -> dict[str, Any]:
        return self.client.get_group(group_id, attributes=attributes)

    def patch_group_membership(self, *, group_id: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        return self.client.patch_group_membership(group_id=group_id, operations=operations)
