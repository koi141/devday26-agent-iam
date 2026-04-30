from __future__ import annotations

from typing import Any

from iam_agent.application.errors import classify_exception
from iam_agent.config.settings import Settings
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.infra.clients.oci_identity_client import OciIdentityClient


class OciCompartmentTools:
    def __init__(self, *, client: OciIdentityClient | None, settings: Settings, init_error: str = "") -> None:
        self.client = client
        self.settings = settings
        self.init_error = init_error

    def _ensure_client(self) -> OciIdentityClient:
        if self.client is None:
            detail = f" (reason: {self.init_error})" if self.init_error else ""
            raise RuntimeError(f"OCIクライアントが初期化されていません。{detail}")
        return self.client

    def list_compartments(self, payload: dict[str, Any]) -> NormalizedResponse:
        compartment_id = payload.get("compartment_ocid") or self.settings.compartment_ocid
        include_subtree = bool(payload.get("include_subtree", True))
        include_inactive = bool(payload.get("include_inactive", False))
        access_level = str(payload.get("access_level") or "ANY")
        output_format = str(payload.get("output_format") or "tree").strip().lower()
        max_depth_raw = payload.get("max_depth")
        max_depth: int | None = None

        if output_format not in {"tree", "json"}:
            return NormalizedResponse.error(
                message="output_format は tree または json を指定してください。",
                code="invalid_argument",
                retryable=False,
                proposal=["output_format に tree または json を指定して再実行してください。"],
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "compartments"},
                    input_summary={"output_format": output_format},
                    decision_reason=["無効な出力形式"],
                    result="error",
                ),
            )

        if max_depth_raw not in (None, ""):
            try:
                max_depth = int(max_depth_raw)
            except Exception:
                return NormalizedResponse.error(
                    message="max_depth は 0 以上の整数で指定してください。",
                    code="invalid_argument",
                    retryable=False,
                    proposal=["max_depth を整数で指定して再実行してください。"],
                    audit=AuditPayload(
                        target={"service": "oci.identity", "resource": "compartments"},
                        input_summary={"max_depth": max_depth_raw},
                        decision_reason=["無効な深度指定"],
                        result="error",
                    ),
                )
            if max_depth < 0:
                return NormalizedResponse.error(
                    message="max_depth は 0 以上で指定してください。",
                    code="invalid_argument",
                    retryable=False,
                    proposal=["max_depth を 0 以上の値で指定して再実行してください。"],
                    audit=AuditPayload(
                        target={"service": "oci.identity", "resource": "compartments"},
                        input_summary={"max_depth": max_depth},
                        decision_reason=["無効な深度指定"],
                        result="error",
                    ),
                )

        if not str(compartment_id or "").strip():
            return NormalizedResponse.error(
                message=(
                    "不足項目: compartment_ocid / 影響: list_compartments を実行できません。"
                    " / 次アクション: compartment_ocid を指定して再実行してください。"
                ),
                code="missing_input",
                retryable=False,
                proposal=["compartment_ocid を指定して再実行してください。"],
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "compartments"},
                    input_summary={"compartment_ocid": compartment_id},
                    decision_reason=["必須入力不足"],
                    result="error",
                ),
            )

        try:
            compartments = self._ensure_client().list_compartments(
                compartment_id=compartment_id,
                include_subtree=include_subtree,
                access_level=access_level,
                include_inactive=include_inactive,
                max_depth=max_depth,
            )
            normalized = self._normalize_compartment_nodes(
                compartments=compartments,
                root_compartment_id=str(compartment_id),
            )
            tree_lines = self._build_compartment_tree_lines(normalized) if output_format == "tree" else []
            excluded_states = [] if include_inactive else ["INACTIVE", "DELETED"]
            return NormalizedResponse.success(
                facts=[
                    f"コンパートメント {len(normalized)} 件を取得しました。",
                    f"対象起点: {compartment_id}",
                    *(["inactive/deleted は除外しました。"] if excluded_states else []),
                ],
                interpretation=[
                    "階層情報は depth と path で確認できます。",
                    *(
                        ["tree_lines を使うとインデント付きで階層を確認できます。"]
                        if output_format == "tree"
                        else ["json 形式で機械処理しやすい構造を返しています。"]
                    ),
                ],
                proposal=[
                    "必要なら max_depth を指定して深度を制限してください。",
                    "inactive を含める場合は include_inactive=true を指定してください。",
                ],
                data={
                    "root_compartment_ocid": str(compartment_id),
                    "output_format": output_format,
                    "total_count": len(normalized),
                    "excluded_states": excluded_states,
                    "compartments": normalized,
                    **({"tree_lines": tree_lines} if tree_lines else {}),
                },
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "compartments"},
                    input_summary={
                        "compartment_ocid": compartment_id,
                        "include_subtree": include_subtree,
                        "include_inactive": include_inactive,
                        "max_depth": max_depth,
                        "output_format": output_format,
                    },
                    decision_reason=["list_compartments 実行"],
                    result="success",
                ),
            )
        except Exception as exc:
            app_error = classify_exception(exc)
            return NormalizedResponse.error(
                message=app_error.message,
                code=app_error.code,
                retryable=app_error.retryable,
                proposal=["権限と compartment_ocid を確認してください。"],
                audit=AuditPayload(
                    target={"service": "oci.identity", "resource": "compartments"},
                    input_summary={
                        "compartment_ocid": compartment_id,
                        "include_subtree": include_subtree,
                        "include_inactive": include_inactive,
                        "max_depth": max_depth,
                        "output_format": output_format,
                    },
                    decision_reason=["list_compartments 失敗"],
                    result="error",
                ),
            )

    @staticmethod
    def _compartment_item_id(item: dict[str, Any]) -> str:
        return str(item.get("id") or item.get("compartment_ocid") or "")

    @staticmethod
    def _compartment_parent_id(item: dict[str, Any]) -> str:
        return str(item.get("compartment_id") or item.get("compartmentId") or item.get("parent_compartment_ocid") or "")

    def _normalize_compartment_nodes(
        self,
        *,
        compartments: list[dict[str, Any]],
        root_compartment_id: str,
    ) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for raw in compartments:
            if not isinstance(raw, dict):
                continue
            cid = self._compartment_item_id(raw)
            if not cid:
                continue
            depth_value = raw.get("_depth")
            depth: int | None
            try:
                depth = int(depth_value) if depth_value is not None else None
            except Exception:
                depth = None

            by_id[cid] = {
                "name": str(raw.get("name") or raw.get("display_name") or cid),
                "compartment_ocid": cid,
                "parent_compartment_ocid": self._compartment_parent_id(raw),
                "lifecycle_state": str(raw.get("lifecycle_state") or raw.get("lifecycleState") or "UNKNOWN"),
                "_depth": depth,
            }

        for cid, node in by_id.items():
            if node["_depth"] is None:
                node["_depth"] = self._resolve_compartment_depth(
                    compartment_id=cid,
                    by_id=by_id,
                    root_compartment_id=root_compartment_id,
                )
            node["depth"] = int(node.get("_depth") or 0)
            node["path"] = self._resolve_compartment_path(
                compartment_id=cid,
                by_id=by_id,
                root_compartment_id=root_compartment_id,
            )
            node.pop("_depth", None)

        nodes = list(by_id.values())
        nodes.sort(key=lambda item: (int(item.get("depth") or 0), str(item.get("path") or ""), str(item.get("name") or "")))
        return nodes

    def _resolve_compartment_depth(
        self,
        *,
        compartment_id: str,
        by_id: dict[str, dict[str, Any]],
        root_compartment_id: str,
    ) -> int:
        depth = 0
        current = by_id.get(compartment_id, {})
        seen: set[str] = {compartment_id}
        while True:
            parent_id = str(current.get("parent_compartment_ocid") or "")
            if not parent_id or parent_id in seen:
                break
            seen.add(parent_id)
            depth += 1
            if parent_id == root_compartment_id:
                break
            parent = by_id.get(parent_id)
            if not isinstance(parent, dict):
                break
            current = parent
        return max(depth, 0)

    def _resolve_compartment_path(
        self,
        *,
        compartment_id: str,
        by_id: dict[str, dict[str, Any]],
        root_compartment_id: str,
    ) -> str:
        names: list[str] = []
        current_id = compartment_id
        seen: set[str] = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            node = by_id.get(current_id)
            if not isinstance(node, dict):
                names.insert(0, current_id)
                break
            names.insert(0, str(node.get("name") or current_id))
            parent_id = str(node.get("parent_compartment_ocid") or "")
            if not parent_id:
                break
            if current_id == root_compartment_id:
                break
            current_id = parent_id
        return "/".join(name for name in names if name)

    @staticmethod
    def _build_compartment_tree_lines(compartments: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for item in compartments:
            depth = int(item.get("depth") or 0)
            name = str(item.get("name") or item.get("compartment_ocid") or "")
            cid = str(item.get("compartment_ocid") or "")
            lifecycle = str(item.get("lifecycle_state") or "UNKNOWN")
            indent = "  " * max(depth, 0)
            lines.append(f"{indent}- {name} ({cid}) [{lifecycle}]")
        return lines
