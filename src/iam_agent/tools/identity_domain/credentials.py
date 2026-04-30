from __future__ import annotations

from typing import Any, Callable

from iam_agent.application.errors import classify_exception
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.infra.clients.identity_domain_client import IdentityDomainClient, USER_STATE_ATTR
from iam_agent.tools.target_resolution import extract_resources


class IdentityDomainCredentialTools:
    def __init__(self, client: IdentityDomainClient) -> None:
        self.client = client

    def list_user_credentials(self, payload: dict[str, Any]) -> NormalizedResponse:
        filter_expr = payload.get("filter")
        user_id = payload.get("user_id")
        if user_id and not filter_expr:
            filter_expr = f'user.value eq "{user_id}"'

        try:
            auth_tokens = self.client.list_auth_tokens(
                filter_expr=filter_expr,
                start_index=payload.get("start_index"),
                count=payload.get("count"),
                attributes=payload.get("attributes"),
            )
            api_keys = self.client.list_api_keys(
                filter_expr=filter_expr,
                start_index=payload.get("start_index"),
                count=payload.get("count"),
                attributes=payload.get("attributes"),
            )
            tokens = extract_resources(auth_tokens)
            keys = extract_resources(api_keys)
            data = {
                "user_id": user_id,
                "api_keys": keys,
                "auth_tokens": tokens,
                "credential_count": len(keys) + len(tokens),
            }
            return NormalizedResponse.success(
                facts=[f"資格情報 {data['credential_count']} 件を取得しました。"],
                interpretation=["API Keys と Auth Tokens を統合して表示しています。"],
                proposal=["必要に応じて user_id/filter で絞り込んでください。"],
                data=data,
                audit=AuditPayload(
                    target={"resource": "Credentials"},
                    input_summary={"user_id": user_id, "filter": filter_expr},
                    decision_reason=["list_user_credentials 実行"],
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
                    target={"resource": "Credentials"},
                    input_summary={"keys": sorted(payload.keys())},
                    decision_reason=["list_user_credentials 失敗"],
                    result="error",
                ),
            )

    def get_last_successful_login(
        self,
        *,
        payload: dict[str, Any],
        resolve_user: Callable[[dict[str, Any], list[str] | None], dict[str, Any]],
    ) -> NormalizedResponse:
        selector = payload.get("user_selector") or {}
        try:
            user = resolve_user(selector, [USER_STATE_ATTR, "userName"])
            last_login = user.get(USER_STATE_ATTR)
            return NormalizedResponse.success(
                facts=["最終ログイン情報を取得しました。"],
                interpretation=["未ログインの場合は値が空になることがあります。"],
                proposal=["必要なら対象を絞って再確認してください。"],
                data={"user_id": user.get("id"), "last_successful_login_at": last_login},
                audit=AuditPayload(
                    target={"resource": "Users", "user_id": user.get("id")},
                    input_summary={"user_selector": selector},
                    decision_reason=["get_last_successful_login 実行"],
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
                    decision_reason=["get_last_successful_login 失敗"],
                    result="error",
                ),
            )
