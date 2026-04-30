from __future__ import annotations

from typing import Any, Callable

import requests

from iam_agent.application.errors import TemporaryUpstreamFailure


USER_STATE_ATTR = (
    "urn:ietf:params:scim:schemas:oracle:idcs:extension:userState:User:lastSuccessfulLoginDate"
)


class IdentityDomainClient:
    def __init__(
        self,
        domain_url: str,
        token_supplier: Callable[[], str],
        *,
        timeout: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.domain_url = domain_url.rstrip("/")
        self.token_supplier = token_supplier
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def base_url(self) -> str:
        return f"{self.domain_url}/admin/v1"

    def _headers(self, has_json: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token_supplier()}",
            "Accept": "application/json",
        }
        if has_json:
            headers["Content-Type"] = "application/json"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[dict[str, Any]] | None = None,
        expected_status: tuple[int, ...] = (200,),
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=self._headers(has_json=json_body is not None),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:  # pragma: no cover - network dependent
            raise TemporaryUpstreamFailure(f"Identity Domains API呼び出しに失敗しました: {exc}") from exc

        if response.status_code not in expected_status:
            raise TemporaryUpstreamFailure(
                f"Identity Domains APIエラー method={method} path={path} "
                f"status={response.status_code} detail={response.text}"
            )

        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    @staticmethod
    def _build_list_params(
        *,
        filter_expr: str | None = None,
        start_index: int | None = None,
        count: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if filter_expr:
            params["filter"] = filter_expr
        if start_index:
            params["startIndex"] = start_index
        if count:
            params["count"] = count
        if sort_by:
            params["sortBy"] = sort_by
        if sort_order:
            params["sortOrder"] = sort_order
        if attributes:
            params["attributes"] = ",".join(attributes)
        return params

    def list_users(
        self,
        *,
        filter_expr: str | None = None,
        start_index: int | None = None,
        count: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        params = self._build_list_params(
            filter_expr=filter_expr,
            start_index=start_index,
            count=count,
            sort_by=sort_by,
            sort_order=sort_order,
            attributes=attributes,
        )
        return self._request("GET", "/Users", params=params)

    def get_user(self, user_id: str, *, attributes: list[str] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if attributes:
            params["attributes"] = ",".join(attributes)
        return self._request("GET", f"/Users/{user_id}", params=params)

    def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/Users", json_body=payload, expected_status=(200, 201))

    def list_groups(
        self,
        *,
        filter_expr: str | None = None,
        start_index: int | None = None,
        count: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        params = self._build_list_params(
            filter_expr=filter_expr,
            start_index=start_index,
            count=count,
            sort_by=sort_by,
            sort_order=sort_order,
            attributes=attributes,
        )
        return self._request("GET", "/Groups", params=params)

    def get_group(self, group_id: str, *, attributes: list[str] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if attributes:
            params["attributes"] = ",".join(attributes)
        return self._request("GET", f"/Groups/{group_id}", params=params)

    def patch_group_membership(self, group_id: str, operations: list[dict[str, Any]]) -> None:
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": operations,
        }
        self._request("PATCH", f"/Groups/{group_id}", json_body=payload, expected_status=(200, 204))

    def list_auth_tokens(
        self,
        *,
        filter_expr: str | None = None,
        start_index: int | None = None,
        count: int | None = None,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        params = self._build_list_params(
            filter_expr=filter_expr,
            start_index=start_index,
            count=count,
            attributes=attributes,
        )
        return self._request("GET", "/AuthTokens", params=params)

    def list_api_keys(
        self,
        *,
        filter_expr: str | None = None,
        start_index: int | None = None,
        count: int | None = None,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        params = self._build_list_params(
            filter_expr=filter_expr,
            start_index=start_index,
            count=count,
            attributes=attributes,
        )
        return self._request("GET", "/ApiKeys", params=params)
