from __future__ import annotations

from typing import Any

from iam_agent.application.errors import PermissionDeniedError, SourceUnavailableError, TemporaryUpstreamFailure
from iam_agent.infra.auth.workload_identity import OciAuthContext

try:
    import oci
except Exception:  # pragma: no cover
    oci = None


class OciResourceSearchClient:
    def __init__(self, auth_context: OciAuthContext) -> None:
        self.auth_context = auth_context
        if oci is None:
            raise RuntimeError("oci SDK がインストールされていません。")

        client_kwargs: dict[str, Any] = {"config": auth_context.config}
        if auth_context.signer is not None:
            client_kwargs["signer"] = auth_context.signer

        self.search_client = oci.resource_search.ResourceSearchClient(**client_kwargs)

    def list_resources(
        self,
        *,
        compartment_id: str,
        resource_type: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query_text = self.build_query(compartment_id=compartment_id, resource_type=resource_type)
        details = oci.resource_search.models.StructuredSearchDetails(
            type="Structured",
            query=query_text,
        )
        return self._search_with_pagination(search_details=details, limit=max(int(limit), 1))

    @staticmethod
    def build_query(*, compartment_id: str, resource_type: str = "") -> str:
        clauses = [f"compartmentId = '{compartment_id}'"]
        normalized_type = str(resource_type or "").strip()
        if normalized_type:
            clauses.append(f"resourceType = '{normalized_type}'")
        return "query all resources where " + " && ".join(clauses)

    def _search_with_pagination(self, *, search_details: Any, limit: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page = ""
        remaining = max(limit, 1)

        while True:
            response = self._search_with_retry(
                search_details=search_details,
                limit=min(remaining, 1000),
                page=page,
            )

            items = list(getattr(response.data, "items", []) or [])
            for item in items:
                results.append(self._serialize_model(item))

            if len(results) >= limit:
                break

            headers = getattr(response, "headers", {}) or {}
            if not isinstance(headers, dict):
                headers = {}
            next_page = str(headers.get("opc-next-page") or "")
            if not next_page:
                break

            page = next_page
            remaining = limit - len(results)
            if remaining <= 0:
                break

        return results[:limit]

    def _search_with_retry(self, *, search_details: Any, limit: int, page: str) -> Any:
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                kwargs: dict[str, Any] = {
                    "search_details": search_details,
                    "limit": limit,
                }
                if page:
                    kwargs["page"] = page
                return self.search_client.search_resources(**kwargs)
            except Exception as exc:  # pragma: no cover - depends on OCI environment
                if attempt < max_attempts and self._is_transient_error(exc):
                    continue
                self._raise_as_domain_error(exc, "list_resources")
                raise TemporaryUpstreamFailure(f"list_resources 失敗: {exc}") from exc

        raise TemporaryUpstreamFailure("list_resources 失敗: retry exhausted")

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        lowered = str(exc).lower()
        return (
            "timeout" in lowered
            or "temporar" in lowered
            or "too many requests" in lowered
            or "rate limit" in lowered
            or "429" in lowered
            or "503" in lowered
            or "502" in lowered
            or "504" in lowered
            or "internal server error" in lowered
        )

    @staticmethod
    def _raise_as_domain_error(exc: Exception, operation: str) -> None:
        message = str(exc)
        lowered = message.lower()
        if (
            "notauthorized" in lowered
            or "not authorized" in lowered
            or "forbidden" in lowered
            or "permission" in lowered
            or "authorization failed" in lowered
        ):
            raise PermissionDeniedError(f"{operation} 権限不足: {message}") from exc
        if (
            "unavailable" in lowered
            or "could not resolve" in lowered
            or "connection refused" in lowered
            or "host unreachable" in lowered
        ):
            raise SourceUnavailableError(f"{operation} 参照先障害: {message}") from exc

    @staticmethod
    def _serialize_model(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return item
        if hasattr(item, "to_dict"):
            converted = item.to_dict()
            if isinstance(converted, dict):
                return converted

        try:
            converted = oci.util.to_dict(item)
            if isinstance(converted, dict):
                return converted
        except Exception:
            pass

        attribute_map = getattr(item, "attribute_map", None)
        if isinstance(attribute_map, dict):
            return {key: getattr(item, key, None) for key in attribute_map}

        return {"value": str(item)}
