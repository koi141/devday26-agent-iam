from __future__ import annotations

from collections import deque
from typing import Any

from iam_agent.application.errors import PermissionDeniedError, TemporaryUpstreamFailure
from iam_agent.infra.auth.workload_identity import OciAuthContext

try:
    import oci
except Exception:  # pragma: no cover
    oci = None


class OciIdentityClient:
    def __init__(self, auth_context: OciAuthContext) -> None:
        self.auth_context = auth_context
        if oci is None:
            raise RuntimeError("oci SDK がインストールされていません。")

        client_kwargs: dict[str, Any] = {"config": auth_context.config}
        # Local profile 認証では signer を明示すると None が渡されて未署名になるため、
        # signer が存在する場合のみ指定する。
        if auth_context.signer is not None:
            client_kwargs["signer"] = auth_context.signer

        self.identity_client = oci.identity.IdentityClient(**client_kwargs)

    def list_compartments(
        self,
        *,
        compartment_id: str,
        include_subtree: bool = True,
        access_level: str = "ANY",
        include_inactive: bool = False,
        max_depth: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            compartments = self._list_compartments_once(
                compartment_id=compartment_id,
                include_subtree=include_subtree,
                access_level=access_level,
            )
        except Exception as exc:  # pragma: no cover - depends on OCI environment
            if include_subtree and self._is_subtree_requires_tenancy_error(exc):
                try:
                    compartments = self._list_compartments_recursive(
                        root_compartment_id=compartment_id,
                        access_level=access_level,
                    )
                except Exception as fallback_exc:  # pragma: no cover - depends on OCI environment
                    self._raise_as_domain_error(fallback_exc, "list_compartments")
                    raise TemporaryUpstreamFailure(f"list_compartments 失敗: {fallback_exc}") from fallback_exc
            else:
                self._raise_as_domain_error(exc, "list_compartments")
                raise TemporaryUpstreamFailure(f"list_compartments 失敗: {exc}") from exc

        if include_subtree:
            compartments = self._append_root_compartment(
                compartments=compartments,
                root_compartment_id=compartment_id,
            )

        return self._apply_compartment_filters(
            compartments=compartments,
            root_compartment_id=compartment_id,
            include_subtree=include_subtree,
            include_inactive=include_inactive,
            max_depth=max_depth,
        )

    def list_policies(self, *, compartment_id: str, include_subtree: bool = False) -> list[dict[str, Any]]:
        try:
            target_compartment_ids = [compartment_id]
            if include_subtree:
                compartments = self.list_compartments(
                    compartment_id=compartment_id,
                    include_subtree=True,
                    access_level="ANY",
                )
                for comp in compartments:
                    comp_id = str(comp.get("id") or "")
                    if comp_id and comp_id not in target_compartment_ids:
                        target_compartment_ids.append(comp_id)

            policies: list[dict[str, Any]] = []
            seen: set[str] = set()
            for cid in target_compartment_ids:
                response = self.identity_client.list_policies(compartment_id=cid)
                for item in response.data:
                    policy = self._serialize_model(item)
                    pid = str(policy.get("id") or "")
                    if pid and pid in seen:
                        continue
                    if pid:
                        seen.add(pid)
                    policies.append(policy)
            return policies
        except Exception as exc:  # pragma: no cover
            self._raise_as_domain_error(exc, "list_policies")
            raise TemporaryUpstreamFailure(f"list_policies 失敗: {exc}") from exc

    def get_policy(self, *, policy_id: str) -> dict[str, Any]:
        try:
            response = self.identity_client.get_policy(policy_id)
            return self._serialize_model(response.data)
        except Exception as exc:  # pragma: no cover
            self._raise_as_domain_error(exc, "get_policy")
            raise TemporaryUpstreamFailure(f"get_policy 失敗: {exc}") from exc

    def _list_compartments_once(
        self,
        *,
        compartment_id: str,
        include_subtree: bool,
        access_level: str,
    ) -> list[dict[str, Any]]:
        response = oci.pagination.list_call_get_all_results(
            self.identity_client.list_compartments,
            compartment_id=compartment_id,
            compartment_id_in_subtree=include_subtree,
            access_level=access_level,
        )
        return [self._serialize_model(item) for item in response.data]

    def _list_compartments_recursive(self, *, root_compartment_id: str, access_level: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        queue: deque[str] = deque([root_compartment_id])

        try:
            root = self.identity_client.get_compartment(root_compartment_id).data.to_dict()
            root_id = str(root.get("id") or root_compartment_id)
            seen.add(root_id)
            results.append(root)
        except Exception:  # pragma: no cover - depends on OCI environment
            seen.add(root_compartment_id)

        while queue:
            parent_id = queue.popleft()
            children = self._list_compartments_once(
                compartment_id=parent_id,
                include_subtree=False,
                access_level=access_level,
            )
            for child in children:
                child_id = str(child.get("id") or "")
                if not child_id or child_id in seen:
                    continue
                seen.add(child_id)
                results.append(child)
                queue.append(child_id)

        return results

    def _append_root_compartment(
        self,
        *,
        compartments: list[dict[str, Any]],
        root_compartment_id: str,
    ) -> list[dict[str, Any]]:
        results = list(compartments)
        if any(str(item.get("id") or "") == root_compartment_id for item in results):
            return results

        try:
            root = self.identity_client.get_compartment(root_compartment_id).data
            root_dict = self._serialize_model(root)
            if root_dict:
                results.append(root_dict)
        except Exception:
            pass
        return results

    def _apply_compartment_filters(
        self,
        *,
        compartments: list[dict[str, Any]],
        root_compartment_id: str,
        include_subtree: bool,
        include_inactive: bool,
        max_depth: int | None,
    ) -> list[dict[str, Any]]:
        if max_depth is not None and max_depth < 0:
            max_depth = None

        depth_map = self._build_depth_map(compartments=compartments, root_compartment_id=root_compartment_id)
        filtered: list[dict[str, Any]] = []
        for item in compartments:
            if not isinstance(item, dict):
                continue
            item_id = self._extract_compartment_id(item)
            if not item_id:
                continue

            lifecycle_state = str(item.get("lifecycle_state") or item.get("lifecycleState") or "").upper()
            if not include_inactive and self._lifecycle_is_inactive(lifecycle_state):
                continue

            depth = depth_map.get(item_id, 0)
            if include_subtree and max_depth is not None and depth > max_depth:
                continue

            normalized = dict(item)
            normalized["_depth"] = depth
            filtered.append(normalized)

        return filtered

    def _build_depth_map(self, *, compartments: list[dict[str, Any]], root_compartment_id: str) -> dict[str, int]:
        children_by_parent: dict[str, list[str]] = {}
        valid_ids: set[str] = set()
        for item in compartments:
            if not isinstance(item, dict):
                continue
            item_id = self._extract_compartment_id(item)
            if not item_id:
                continue
            valid_ids.add(item_id)
            parent_id = self._extract_parent_compartment_id(item)
            if parent_id:
                children_by_parent.setdefault(parent_id, []).append(item_id)

        depth_map: dict[str, int] = {}
        if root_compartment_id in valid_ids:
            queue: deque[tuple[str, int]] = deque([(root_compartment_id, 0)])
            while queue:
                current, depth = queue.popleft()
                if current in depth_map:
                    continue
                depth_map[current] = depth
                for child in children_by_parent.get(current, []):
                    queue.append((child, depth + 1))

        # root から辿れない孤立ノードは parent chain から深度を推定
        for item in compartments:
            item_id = self._extract_compartment_id(item if isinstance(item, dict) else {})
            if not item_id or item_id in depth_map:
                continue

            depth = 0
            seen: set[str] = set()
            current = item if isinstance(item, dict) else {}
            while True:
                parent_id = self._extract_parent_compartment_id(current)
                if not parent_id or parent_id in seen:
                    break
                seen.add(parent_id)
                depth += 1
                if parent_id == root_compartment_id:
                    break
                parent = next(
                    (
                        c
                        for c in compartments
                        if isinstance(c, dict) and self._extract_compartment_id(c) == parent_id
                    ),
                    None,
                )
                if not isinstance(parent, dict):
                    break
                current = parent
            depth_map[item_id] = max(depth, 0)

        return depth_map

    @staticmethod
    def _extract_compartment_id(item: dict[str, Any]) -> str:
        return str(item.get("id") or item.get("identifier") or "")

    @staticmethod
    def _extract_parent_compartment_id(item: dict[str, Any]) -> str:
        return str(
            item.get("compartment_id")
            or item.get("compartmentId")
            or item.get("parent_compartment_ocid")
            or item.get("parentCompartmentId")
            or ""
        )

    @staticmethod
    def _lifecycle_is_inactive(lifecycle_state: str) -> bool:
        normalized = lifecycle_state.upper().strip()
        return normalized in {"INACTIVE", "DELETED"}

    @staticmethod
    def _is_subtree_requires_tenancy_error(exc: Exception) -> bool:
        lowered = str(exc).lower()
        return "compartmentid must be tenancy ocid" in lowered

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

    def _raise_as_domain_error(self, exc: Exception, operation: str) -> None:
        message = str(exc)
        lowered = message.lower()
        if (
            "notauthorized" in lowered
            or "not authorized" in lowered
            or "notauthenticated" in lowered
            or "authentication" in lowered
            or "authorization failed" in lowered
            or "forbidden" in lowered
            or "permission" in lowered
        ):
            raise PermissionDeniedError(f"{operation} 権限不足: {message}") from exc
