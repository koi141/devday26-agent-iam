from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import requests


USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
PATCH_OP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
USER_STATE_URN = "urn:ietf:params:scim:schemas:oracle:idcs:extension:userState:User"

# Oracleの公開サンプルに合わせて、attributes指定はこの形式を使う
LAST_SUCCESSFUL_LOGIN_ATTR = (
    "urn:ietf:params:scim:schemas:oracle:idcs:extension:userState:User:lastSuccessfulLoginDate"
)


class IdentityDomainError(RuntimeError):
    pass


@dataclass
class IdentityDomainClient:
    domain_url: str
    token_supplier: Callable[[], str | dict[str, Any]]
    timeout: int = 30
    verify_ssl: bool = True
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self.domain_url = self.domain_url.rstrip("/")

    @property
    def base_url(self) -> str:
        return f"{self.domain_url}/admin/v1"

    def _get_access_token(self) -> str:
        token = self.token_supplier()
        if isinstance(token, dict):
            access_token = token.get("access_token")
            if not access_token:
                raise IdentityDomainError("token_supplier() が access_token を返していません。")
            return access_token
        if not token:
            raise IdentityDomainError("token_supplier() が空のトークンを返しました。")
        return token

    def _headers(self, content_type: Optional[str] = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Accept": "application/json",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        expected_status: tuple[int, ...] = (200,),
    ) -> Any:
        url = f"{self.base_url}{path}"

        response = self.session.request(
            method=method,
            url=url,
            headers=self._headers("application/json" if json_body is not None else None),
            params=params,
            json=json_body,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )

        if response.status_code not in expected_status:
            detail = response.text
            try:
                detail = response.json()
            except Exception:
                pass
            raise IdentityDomainError(
                f"{method} {url} failed: status={response.status_code}, detail={detail}"
            )

        if response.status_code == 204 or not response.content:
            return None

        return response.json()

    @staticmethod
    def _as_csv(attributes: Optional[list[str] | tuple[str, ...] | str]) -> Optional[str]:
        if attributes is None:
            return None
        if isinstance(attributes, str):
            return attributes
        return ",".join(attributes)

    @staticmethod
    def _escape_scim_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _paged_get(
        self,
        path: str,
        *,
        filter_expr: Optional[str] = None,
        attributes: Optional[list[str] | tuple[str, ...] | str] = None,
        count: int = 100,
        start_index: int = 1,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        return_all: bool = True,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "count": count,
            "startIndex": start_index,
        }
        if filter_expr:
            params["filter"] = filter_expr
        if attributes:
            params["attributes"] = self._as_csv(attributes)
        if sort_by:
            params["sortBy"] = sort_by
        if sort_order:
            params["sortOrder"] = sort_order
        if extra_params:
            params.update(extra_params)

        first_page = self._request("GET", path, params=params, expected_status=(200,))
        if not return_all:
            return first_page

        resources = list(first_page.get("Resources", []))
        total_results = int(first_page.get("totalResults", len(resources)))
        items_per_page = int(first_page.get("itemsPerPage", len(resources) or count))
        next_start = int(first_page.get("startIndex", start_index)) + items_per_page

        while len(resources) < total_results and items_per_page > 0:
            params["startIndex"] = next_start
            page = self._request("GET", path, params=params, expected_status=(200,))
            page_resources = page.get("Resources", [])
            if not page_resources:
                break
            resources.extend(page_resources)
            items_per_page = int(page.get("itemsPerPage", len(page_resources)))
            next_start = int(page.get("startIndex", next_start)) + items_per_page

        merged = dict(first_page)
        merged["Resources"] = resources
        merged["itemsPerPage"] = len(resources)
        merged["startIndex"] = 1 if resources else start_index
        merged["totalResults"] = len(resources)
        return merged

    def _resolve_single_resource(
        self,
        resource_name: str,
        fetcher: Callable[..., dict[str, Any]],
        *,
        resource_id: Optional[str] = None,
        filter_expr: Optional[str] = None,
        attributes: Optional[list[str] | tuple[str, ...] | str] = None,
    ) -> dict[str, Any]:
        if resource_id:
            return fetcher(resource_id=resource_id, attributes=attributes)

        if not filter_expr:
            raise ValueError(f"{resource_name}: resource_id または filter_expr のどちらかが必要です。")

        result = fetcher(filter_expr=filter_expr, attributes=attributes, count=2, return_all=False)
        resources = result.get("Resources", [])
        if len(resources) == 0:
            raise IdentityDomainError(f"{resource_name}: filter に一致するリソースが見つかりません。")
        if len(resources) > 1:
            raise IdentityDomainError(f"{resource_name}: filter に複数件一致しました。1件に絞ってください。")
        return resources[0]

    # -------------------------
    # Users
    # -------------------------
    def list_users(
        self,
        *,
        filter_expr: Optional[str] = None,
        attributes: Optional[list[str] | tuple[str, ...] | str] = None,
        count: int = 100,
        start_index: int = 1,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        return_all: bool = True,
    ) -> dict[str, Any]:
        return self._paged_get(
            "/Users",
            filter_expr=filter_expr,
            attributes=attributes,
            count=count,
            start_index=start_index,
            sort_by=sort_by,
            sort_order=sort_order,
            return_all=return_all,
        )

    def get_user(
        self,
        *,
        user_id: Optional[str] = None,
        filter_expr: Optional[str] = None,
        attributes: Optional[list[str] | tuple[str, ...] | str] = None,
    ) -> dict[str, Any]:
        if user_id:
            params = {}
            if attributes:
                params["attributes"] = self._as_csv(attributes)
            return self._request("GET", f"/Users/{user_id}", params=params, expected_status=(200,))

        return self._resolve_single_resource(
            "get_user",
            self.list_users,
            resource_id=None,
            filter_expr=filter_expr,
            attributes=attributes,
        )

    def create_user(
        self,
        *,
        user_name: str,
        display_name: Optional[str] = None,
        given_name: Optional[str] = None,
        family_name: Optional[str] = None,
        emails: Optional[list[str]] = None,
        external_id: Optional[str] = None,
        active: bool = True,
        extra_payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if active is False:
            raise ValueError("deactivate は手動運用とのことなので、create_user(active=False) は禁止しています。")

        payload: dict[str, Any] = {
            "schemas": [USER_SCHEMA],
            "userName": user_name,
            "active": True,
        }

        if display_name:
            payload["displayName"] = display_name

        if given_name or family_name:
            payload["name"] = {}
            if given_name:
                payload["name"]["givenName"] = given_name
            if family_name:
                payload["name"]["familyName"] = family_name

        if emails:
            payload["emails"] = [
                {
                    "value": email,
                    "type": "work",
                    "primary": idx == 0,
                }
                for idx, email in enumerate(emails)
            ]

        if external_id:
            payload["externalId"] = external_id

        if extra_payload:
            payload.update(extra_payload)

        if payload.get("active") is False:
            raise ValueError("deactivate は手動運用とのことなので、active=False を含む payload は禁止しています。")

        return self._request(
            "POST",
            "/Users",
            json_body=payload,
            expected_status=(200, 201),
        )

    def update_user(
        self,
        *,
        user_id: Optional[str] = None,
        filter_expr: Optional[str] = None,
        operations: Optional[list[dict[str, Any]]] = None,
        replace: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if not operations and not replace:
            raise ValueError("operations または replace のどちらかを指定してください。")

        if not user_id:
            target = self.get_user(user_id=None, filter_expr=filter_expr, attributes=["id"])
            user_id = target["id"]

        patch_operations: list[dict[str, Any]] = []

        if replace:
            for path, value in replace.items():
                if path == "active" and value is False:
                    raise ValueError("deactivate は手動運用とのことなので、active=False の更新は禁止しています。")
                patch_operations.append(
                    {
                        "op": "replace",
                        "path": path,
                        "value": value,
                    }
                )

        if operations:
            for op in operations:
                op_name = str(op.get("op", "")).lower()
                path = op.get("path")
                value = op.get("value")
                if op_name == "replace" and path == "active" and value is False:
                    raise ValueError("deactivate は手動運用とのことなので、active=False の更新は禁止しています。")
                patch_operations.append(op)

        payload = {
            "schemas": [PATCH_OP_SCHEMA],
            "Operations": patch_operations,
        }

        return self._request(
            "PATCH",
            f"/Users/{user_id}",
            json_body=payload,
            expected_status=(200,),
        )

    # -------------------------
    # Groups
    # -------------------------
    def list_groups(
        self,
        *,
        filter_expr: Optional[str] = None,
        attributes: Optional[list[str] | tuple[str, ...] | str] = None,
        count: int = 100,
        start_index: int = 1,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        return_all: bool = True,
    ) -> dict[str, Any]:
        return self._paged_get(
            "/Groups",
            filter_expr=filter_expr,
            attributes=attributes,
            count=count,
            start_index=start_index,
            sort_by=sort_by,
            sort_order=sort_order,
            return_all=return_all,
        )

    def get_group(
        self,
        *,
        group_id: Optional[str] = None,
        filter_expr: Optional[str] = None,
        attributes: Optional[list[str] | tuple[str, ...] | str] = None,
    ) -> dict[str, Any]:
        if group_id:
            params = {}
            if attributes:
                params["attributes"] = self._as_csv(attributes)
            return self._request("GET", f"/Groups/{group_id}", params=params, expected_status=(200,))

        return self._resolve_single_resource(
            "get_group",
            self.list_groups,
            resource_id=None,
            filter_expr=filter_expr,
            attributes=attributes,
        )

    # -------------------------
    # Credentials
    # -------------------------
    def list_user_credentials(
        self,
        *,
        user_id: Optional[str] = None,
        user_ocid: Optional[str] = None,
        filter_expr: Optional[str] = None,
        count: int = 100,
        return_all: bool = True,
    ) -> dict[str, Any]:
        """
        API Keys / Auth Tokens をまとめて取得。
        user_id を指定すると `user.value eq "<id>"` で絞ります。
        user_ocid を指定すると `user.ocid eq "<ocid>"` で絞ります。
        filter_expr を追加で与えると AND 連結します。
        """
        filters: list[str] = []
        if filter_expr:
            filters.append(f"({filter_expr})")
        if user_id:
            filters.append(f'user.value eq "{self._escape_scim_string(user_id)}"')
        if user_ocid:
            filters.append(f'user.ocid eq "{self._escape_scim_string(user_ocid)}"')

        combined_filter = " and ".join(filters) if filters else None

        api_keys = self._paged_get(
            "/ApiKeys",
            filter_expr=combined_filter,
            count=count,
            return_all=return_all,
        )
        auth_tokens = self._paged_get(
            "/AuthTokens",
            filter_expr=combined_filter,
            count=count,
            return_all=return_all,
        )

        return {
            "api_keys": api_keys,
            "auth_tokens": auth_tokens,
        }

    # -------------------------
    # Last Successful Login
    # -------------------------
    def get_last_successful_login(
        self,
        *,
        user_id: Optional[str] = None,
        filter_expr: Optional[str] = None,
        count: int = 100,
        return_all: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        attrs = ["id", "userName", "displayName", LAST_SUCCESSFUL_LOGIN_ATTR]

        if user_id:
            user = self.get_user(user_id=user_id, attributes=attrs)
            return self._extract_last_login(user)

        result = self.list_users(
            filter_expr=filter_expr,
            attributes=attrs,
            count=count,
            return_all=return_all,
        )
        return [self._extract_last_login(user) for user in result.get("Resources", [])]

    @staticmethod
    def _extract_last_login(user: dict[str, Any]) -> dict[str, Any]:
        user_state = user.get(USER_STATE_URN) or {}
        return {
            "id": user.get("id"),
            "userName": user.get("userName"),
            "displayName": user.get("displayName"),
            "lastSuccessfulLoginDate": user_state.get("lastSuccessfulLoginDate"),
        }


if __name__ == "__main__":
    # 例:
    # 既存の get_access_token() を同じファイルまたは別モジュールから import して使う
    #
    # from your_token_module import get_access_token

    def get_access_token() -> dict[str, Any]:
        body = prepare_token_request(
        grant_type="client_credentials",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scope=SCOPE,
    )

    response = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    token = get_access_token()
    print(json.dumps(token, indent=2, ensure_ascii=False))
    print("access_token:", token.get("access_token"))

    DOMAIN_URL = "https://idcs-fd7b74bda9fa4b58b28948feef16d8ca.identity.oraclecloud.com:443"

    # トークンを毎回取り直したくないなら、起動時に一度だけ取得して固定でもOK
    token_cache = get_access_token()["access_token"]

    client = IdentityDomainClient(
        domain_url=DOMAIN_URL,
        token_supplier=lambda: token_cache,
        # token_supplier=lambda: get_access_token()["access_token"],  # 毎回取得したい場合
        timeout=30,
        verify_ssl=True,
    )

    # 1) list_users: SCIM filter 対応
    users = client.list_users(
        filter_expr='userName sw "alice"',
        attributes=["id", "userName", "displayName", "active"],
    )
    print("list_users:", users)

    # 2) get_user: id でも filter でも取得可能
    user = client.get_user(filter_expr='userName eq "alice@example.com"')
    print("get_user:", user)

    # 3) create_user
    created = client.create_user(
        user_name="new.user@example.com",
        display_name="New User",
        given_name="New",
        family_name="User",
        emails=["new.user@example.com"],
    )
    print("create_user:", created)

    # 4) update_user: deactivate は禁止
    updated = client.update_user(
        filter_expr='userName eq "new.user@example.com"',
        replace={
            "displayName": "New User Renamed",
        },
    )
    print("update_user:", updated)

    # 5) list_groups: SCIM filter 対応
    groups = client.list_groups(
        filter_expr='displayName co "Admin"',
        attributes=["id", "displayName"],
    )
    print("list_groups:", groups)

    # 6) get_group
    group = client.get_group(filter_expr='displayName eq "Identity Domain Administrator"')
    print("get_group:", group)

    # 7) list_user_credentials
    #    user.value (= user id) / user.ocid で絞り込める
    creds = client.list_user_credentials(user_id=user["id"])
    print("list_user_credentials:", creds)

    # 8) get_last_successful_login
    last_login = client.get_last_successful_login(
        filter_expr='userName eq "alice@example.com"'
    )
    print("get_last_successful_login:", last_login)