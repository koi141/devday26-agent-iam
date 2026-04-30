from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

import requests

from iam_agent.application.errors import (
    AppError,
    DelegationTimeoutError,
    InvalidArgumentError,
    MissingCredentialError,
    PeerUntrustedError,
)
from iam_agent.config.settings import Settings
from iam_agent.domain.models import PeerAgent
from iam_agent.infra.logging.redaction import redact_a2a_payload


class A2APeerClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self._peer_registry_cache: dict[str, PeerAgent] | None = None

    def list_peers(self) -> dict[str, PeerAgent]:
        if self._peer_registry_cache is not None:
            return self._peer_registry_cache
        self._peer_registry_cache = self._load_registry()
        return self._peer_registry_cache

    def refresh(self) -> dict[str, PeerAgent]:
        self._peer_registry_cache = self._load_registry()
        return self._peer_registry_cache

    def list_trusted_peers(
        self,
        *,
        operation_name: str = "",
        exclude_agent_ids: set[str] | None = None,
    ) -> list[PeerAgent]:
        excluded = exclude_agent_ids or set()
        peers = []
        for peer in self.list_peers().values():
            if peer.trust_state != "trusted":
                continue
            if peer.agent_id in excluded:
                continue
            if operation_name and operation_name not in peer.supported_operations:
                continue
            peers.append(peer)
        peers.sort(key=lambda item: (item.priority, item.agent_id))
        return peers

    def select_peer_for_operation(
        self,
        *,
        operation_name: str,
        exclude_agent_ids: set[str] | None = None,
    ) -> tuple[PeerAgent | None, list[PeerAgent]]:
        candidates = self.list_trusted_peers(
            operation_name=operation_name,
            exclude_agent_ids=exclude_agent_ids,
        )
        if not candidates:
            return None, []
        if len(candidates) == 1:
            return candidates[0], candidates
        top = candidates[0]
        second = candidates[1]
        if top.priority == second.priority:
            return None, candidates
        return top, candidates

    def verify_incoming_peer(self, *, source_agent_id: str, auth_token: str) -> None:
        if not source_agent_id.strip():
            raise PeerUntrustedError("source_agent_id が指定されていません。")

        peer = self.list_peers().get(source_agent_id)
        if peer is None or peer.trust_state != "trusted":
            raise PeerUntrustedError(f"未信頼の依頼元です: {source_agent_id}")

        expected_token = self.settings.a2a_peer_auth_token.strip()
        if expected_token and auth_token.strip() != expected_token:
            raise PeerUntrustedError("peer 認証トークンが一致しません。")

    def fetch_capabilities(self, *, peer: PeerAgent, auth_token: str = "", timeout_seconds: float = 5.0) -> dict[str, Any]:
        if not peer.base_url.strip():
            raise InvalidArgumentError(f"peer `{peer.agent_id}` の base_url が未設定です。")

        headers = self._build_headers(auth_token=auth_token)
        headers["X-Source-Agent-ID"] = self.settings.a2a_agent_id
        try:
            base_url = peer.base_url.rstrip("/")
            for path in ("/.well-known/agent.json", "/a2a/capabilities"):
                response = self.session.get(
                    f"{base_url}{path}",
                    headers=headers,
                    timeout=timeout_seconds,
                )
                data = self._response_json(response)
                if response.status_code < 400:
                    return data
                if response.status_code == 404:
                    continue
                raise AppError(
                    code="peer_capability_error",
                    message=str(data.get("detail") or data.get("error_code") or f"HTTP {response.status_code}"),
                    retryable=False,
                )
            raise AppError(
                code="peer_capability_error",
                message="peer の agent card エンドポイントが見つかりません。",
                retryable=False,
            )
        except requests.Timeout as exc:
            raise DelegationTimeoutError(f"capabilities 取得がタイムアウトしました: {peer.agent_id}") from exc
        except requests.RequestException as exc:
            raise AppError(code="source_unavailable", message=str(exc), retryable=True) from exc

    def execute_delegation(
        self,
        *,
        peer: PeerAgent,
        request_payload: dict[str, Any],
        auth_token: str = "",
        timeout_seconds: float = 12.0,
        max_retries: int = 1,
    ) -> dict[str, Any]:
        if not peer.base_url.strip():
            raise InvalidArgumentError(f"peer `{peer.agent_id}` の base_url が未設定です。")

        headers = self._build_headers(auth_token=auth_token)
        headers["X-Source-Agent-ID"] = self.settings.a2a_agent_id
        payload = redact_a2a_payload(request_payload)
        attempt = 0
        last_error: Exception | None = None
        while attempt <= max_retries:
            attempt += 1
            try:
                response = self.session.post(
                    f"{peer.base_url.rstrip('/')}/a2a/execute",
                    json=payload,
                    headers=headers,
                    timeout=timeout_seconds,
                )
                data = self._response_json(response)
                if response.status_code == 504:
                    raise DelegationTimeoutError(f"peer `{peer.agent_id}` でタイムアウトしました。")
                if response.status_code >= 400:
                    error_code = str(data.get("error_code") or "delegation_failed")
                    retryable = response.status_code >= 500
                    raise AppError(
                        code=error_code,
                        message=str(data.get("detail") or data.get("interpretation") or f"HTTP {response.status_code}"),
                        retryable=retryable,
                    )
                return data
            except DelegationTimeoutError as exc:
                last_error = exc
                if attempt > max_retries:
                    break
                continue
            except requests.Timeout as exc:
                last_error = DelegationTimeoutError(f"peer `{peer.agent_id}` でタイムアウトしました。")
                if attempt > max_retries:
                    break
                continue
            except requests.RequestException as exc:
                last_error = AppError(code="source_unavailable", message=str(exc), retryable=True)
                if attempt > max_retries:
                    break
                continue
        if last_error is None:
            raise DelegationTimeoutError(f"peer `{peer.agent_id}` から応答を取得できませんでした。")
        if isinstance(last_error, Exception):
            raise last_error
        raise DelegationTimeoutError(f"peer `{peer.agent_id}` から応答を取得できませんでした。")

    def to_registry_payload(self) -> list[dict[str, Any]]:
        return [asdict(peer) for peer in self.list_peers().values()]

    def _load_registry(self) -> dict[str, PeerAgent]:
        raw = self.settings.a2a_peer_registry_json.strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MissingCredentialError(["a2a_peer_registry_json"]) from exc

        candidates: list[dict[str, Any]] = []
        if isinstance(payload, list):
            candidates = [item for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            raw_peers = payload.get("peers")
            if isinstance(raw_peers, list):
                candidates = [item for item in raw_peers if isinstance(item, dict)]

        peers: dict[str, PeerAgent] = {}
        for item in candidates:
            agent_id = str(item.get("agent_id") or item.get("id") or "").strip()
            if not agent_id:
                continue
            trust_state = str(item.get("trust_state") or "pending").strip().lower()
            if trust_state not in {"trusted", "blocked", "pending"}:
                trust_state = "pending"
            operations_raw = item.get("supported_operations") or item.get("operations") or []
            if not isinstance(operations_raw, list):
                operations_raw = []
            operations = [str(op).strip() for op in operations_raw if str(op).strip()]
            priority_raw = item.get("priority", 100)
            try:
                priority = int(priority_raw)
            except Exception:
                priority = 100
            peers[agent_id] = PeerAgent(
                agent_id=agent_id,
                display_name=str(item.get("display_name") or item.get("name") or agent_id),
                trust_state=trust_state,  # type: ignore[arg-type]
                base_url=str(item.get("base_url") or "").strip(),
                supported_operations=operations,
                priority=priority,
            )
        return peers

    @staticmethod
    def _response_json(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except Exception:
            return {"detail": response.text}
        if isinstance(data, dict):
            return data
        return {"data": data}

    def _build_headers(self, *, auth_token: str = "") -> dict[str, str]:
        token = auth_token.strip() or self.settings.a2a_peer_auth_token.strip()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers
