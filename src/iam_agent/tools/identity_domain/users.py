from __future__ import annotations

from typing import Any

from iam_agent.application.errors import classify_exception
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.infra.clients.identity_domain_client import IdentityDomainClient
from iam_agent.tools.target_resolution import extract_resources


class IdentityDomainUserTools:
    def __init__(self, client: IdentityDomainClient) -> None:
        self.client = client

    def list_users(self, payload: dict[str, Any]) -> NormalizedResponse:
        try:
            response = self.list_users_raw(
                filter_expr=payload.get("filter"),
                start_index=payload.get("start_index"),
                count=payload.get("count"),
                sort_by=payload.get("sort_by"),
                sort_order=payload.get("sort_order"),
                attributes=payload.get("attributes"),
            )
            users = extract_resources(response)
            return NormalizedResponse.success(
                facts=[f"ユーザー {len(users)} 件を取得しました。"],
                interpretation=["検索条件に一致するユーザー一覧です。"],
                proposal=["必要に応じて filter や attributes を調整してください。"],
                data={
                    "users": users,
                    "total_results": response.get("totalResults", len(users)),
                    "start_index": response.get("startIndex", payload.get("start_index", 1)),
                    "items_per_page": response.get("itemsPerPage", len(users)),
                },
                audit=AuditPayload(
                    target={"resource": "Users"},
                    input_summary={
                        k: payload.get(k)
                        for k in ("filter", "start_index", "count", "sort_by", "sort_order", "attributes")
                    },
                    decision_reason=["list_users 実行"],
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
                    target={"resource": "Users"},
                    input_summary={"keys": sorted(payload.keys())},
                    decision_reason=["list_users 失敗"],
                    result="error",
                ),
            )

    def list_users_raw(
        self,
        *,
        filter_expr: str | None = None,
        start_index: int | None = None,
        count: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.client.list_users(
            filter_expr=filter_expr,
            start_index=start_index,
            count=count,
            sort_by=sort_by,
            sort_order=sort_order,
            attributes=attributes,
        )

    def get_user_raw(self, *, user_id: str, attributes: list[str] | None = None) -> dict[str, Any]:
        return self.client.get_user(user_id, attributes=attributes)

    def create_user_raw(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.client.create_user(body)

    def update_user_raw(self, *, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"update_user_raw is not implemented yet for user_id={user_id}")
