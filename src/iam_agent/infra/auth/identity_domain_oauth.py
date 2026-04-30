from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import requests

from iam_agent.application.errors import MissingCredentialError, TemporaryUpstreamFailure
from iam_agent.config.settings import Settings


@dataclass(slots=True)
class AccessToken:
    token: str
    expires_at: float

    def valid(self) -> bool:
        return time.time() < self.expires_at - 60


class IdentityDomainOAuthProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        timeout: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.timeout = timeout
        self.session = session or requests.Session()
        self._cache: AccessToken | None = None

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        missing = self.settings.missing_for_route("identity_domain_oauth")
        if missing:
            raise MissingCredentialError(missing)

        if not force_refresh and self._cache and self._cache.valid():
            return self._cache.token

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.settings.domain_client_id,
            "client_secret": self.settings.domain_client_secret,
        }
        if self.settings.domain_scope:
            payload["scope"] = self.settings.domain_scope

        try:
            response = self.session.post(
                self.settings.token_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:  # pragma: no cover - network failure path
            raise TemporaryUpstreamFailure(f"OAuthトークン取得に失敗しました: {exc}") from exc

        if response.status_code >= 400:
            raise TemporaryUpstreamFailure(
                f"OAuthトークン取得エラー status={response.status_code}: {response.text}"
            )

        body: dict[str, Any] = response.json()
        token = body.get("access_token")
        if not token:
            raise TemporaryUpstreamFailure("OAuthレスポンスに access_token がありません。")

        expires_in = int(body.get("expires_in", 3600))
        self._cache = AccessToken(token=token, expires_at=time.time() + expires_in)
        return token
