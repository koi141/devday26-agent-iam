from __future__ import annotations

import re
from typing import Any

from iam_agent.application.errors import AmbiguousTargetError, AppError, classify_exception
from iam_agent.application.high_risk_guard import HIGH_RISK_TOOLS, ensure_membership_change_allowed
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.infra.clients.identity_domain_client import IdentityDomainClient
from iam_agent.tools.identity_domain.credentials import IdentityDomainCredentialTools
from iam_agent.tools.identity_domain.groups import IdentityDomainGroupTools
from iam_agent.tools.identity_domain.users import IdentityDomainUserTools
from iam_agent.tools.hr_tools import HrTools
from iam_agent.tools.target_resolution import extract_resources, resolve_by_selector

UNRESOLVED_REF_PATTERN = re.compile(r"^\s*(?:\$\{[^{}]+\}|\{\{[^{}]+\}\})\s*$")


class IdentityDomainTools:
    def __init__(self, client: IdentityDomainClient, hr_tools: HrTools | None = None) -> None:
        self.client = client
        self.hr_tools = hr_tools
        self.user_tools = IdentityDomainUserTools(client)
        self.group_tools = IdentityDomainGroupTools(client)
        self.credential_tools = IdentityDomainCredentialTools(client)

    def list_users(self, payload: dict[str, Any]) -> NormalizedResponse:
        return self.user_tools.list_users(payload)

    def get_user(self, payload: dict[str, Any]) -> NormalizedResponse:
        attributes = payload.get("attributes")
        selector = self._normalize_user_selector(payload)
        user_id = str(payload.get("user_id") or "").strip()
        if user_id:
            selector["id"] = user_id
        if not selector:
            return self._missing_input_response("user_id", "Users")

        try:
            user = self._resolve_user(selector, attributes=attributes)
            return NormalizedResponse.success(
                facts=["ユーザー詳細を取得しました。"],
                interpretation=["対象ユーザーの現在状態です。"],
                proposal=["必要に応じて attributes を追加指定してください。"],
                data={"user": user},
                audit=AuditPayload(
                    target={"resource": "Users", "user_id": user.get("id") or user_id},
                    input_summary={"user_selector": selector, "attributes": attributes},
                    decision_reason=["get_user 実行", "user_id不足時は list_users + HR補完で解決"],
                    result="success",
                ),
            )
        except Exception as exc:
            return self._error_response("Users", "get_user 失敗", payload, exc)

    def create_user(self, payload: dict[str, Any]) -> NormalizedResponse:
        self._ensure_a2a_high_risk_guard(payload=payload, operation_name="create_user")
        required_fields = ["family_name", "given_name", "email"]
        missing = [field for field in required_fields if self._is_missing_or_placeholder(payload.get(field))]
        candidate = payload.copy()
        supplemented_from_hr = False
        hr_lookup_attempted = False
        hr_candidate_count: int | None = None
        hr_query_payload = self._build_hr_query_payload(payload)
        last_hr_query_keys: list[str] = sorted(hr_query_payload.keys()) if hr_query_payload else []

        if missing and self.hr_tools is not None and hr_query_payload:
            for query_payload in self._build_hr_query_payload_candidates(hr_query_payload):
                hr_lookup_attempted = True
                last_hr_query_keys = sorted(query_payload.keys())
                hr_result = self.hr_tools.query_hr_database(query_payload)
                if hr_result.status == "success":
                    candidates = (hr_result.data or {}).get("candidates", [])
                    hr_candidate_count = len(candidates)
                    if len(candidates) == 1:
                        source = candidates[0]
                        self._set_if_missing(candidate, "given_name", source.get("first_name"))
                        self._set_if_missing(candidate, "family_name", source.get("last_name"))
                        self._set_if_missing(candidate, "email", source.get("email"))
                        supplemented_from_hr = True
                        break
                    if len(candidates) > 1:
                        return NormalizedResponse.needs_confirmation(
                            facts=["HR候補が複数見つかりました。"],
                            interpretation=["自動選択は禁止のため確認が必要です。"],
                            proposal=["emp_id または email を指定して候補を1件に絞ってください。"],
                            data={"candidates": candidates},
                            audit=AuditPayload(
                                target={"resource": "Users"},
                                input_summary={"missing": missing, "hr_query_keys": last_hr_query_keys},
                                decision_reason=["HR候補が複数"],
                                result="needs_confirmation",
                            ),
                        )
                    continue
                if hr_result.status == "error":
                    hr_error = hr_result.errors[0] if hr_result.errors else None
                    message = hr_error.message if hr_error else "HRデータベース照会に失敗しました。"
                    return NormalizedResponse.error(
                        message=message,
                        code=hr_error.code if hr_error else "hr_lookup_failed",
                        retryable=bool(hr_error.retryable) if hr_error else True,
                        proposal=["HR接続情報または検索条件を確認して再実行してください。"],
                        audit=AuditPayload(
                            target={"resource": "Users"},
                            input_summary={"missing": missing, "hr_query_keys": last_hr_query_keys},
                            decision_reason=["HR照会エラー"],
                            result="error",
                        ),
                    )

        self._normalize_username_from_email(candidate)
        missing = [field for field in required_fields if self._is_missing_or_placeholder(candidate.get(field))]
        if missing:
            proposal = ["不足項目を指定するか query_hr_database で補完可能な情報を追加してください。"]
            if hr_lookup_attempted and hr_candidate_count == 0:
                proposal = ["HRデータベースを検索しましたが候補が見つかりませんでした。"] + proposal
            if not hr_query_payload:
                proposal = [
                    "HR補完のために emp_id / email / family_name(または family_name_kanji) など検索条件を指定してください。"
                ]
            return NormalizedResponse.error(
                message=f"create_user の必須項目が不足しています: {', '.join(missing)}",
                code="missing_input",
                retryable=False,
                proposal=proposal,
                audit=AuditPayload(
                    target={"resource": "Users"},
                    input_summary={"missing": missing, "hr_query_keys": last_hr_query_keys},
                    decision_reason=["必須項目不足"],
                    result="error",
                ),
            )

        body = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": candidate["email"],
            "name": {
                "familyName": candidate["family_name"],
                "givenName": candidate["given_name"],
            },
            "emails": [{"value": candidate["email"], "type": "work", "primary": True}],
            "active": True,
        }

        try:
            created = self.user_tools.create_user_raw(body)
            return NormalizedResponse.success(
                facts=["ユーザーを作成しました。"],
                interpretation=["高リスク操作として監査対象です。"],
                proposal=["必要に応じてグループ所属を追加してください。"],
                data={"created_user": created, "supplemented_from_hr": supplemented_from_hr},
                audit=AuditPayload(
                    target={"resource": "Users"},
                    input_summary={
                        "email": candidate["email"],
                        "username": candidate["email"],
                        "supplemented_from_hr": supplemented_from_hr,
                    },
                    decision_reason=["create_user 実行"],
                    result="success",
                ),
            )
        except Exception as exc:
            return self._error_response("Users", "create_user 失敗", payload, exc)

    @classmethod
    def _normalize_username_from_email(cls, candidate: dict[str, Any]) -> None:
        if cls._is_missing_or_placeholder(candidate.get("email")):
            return
        email = str(candidate["email"]).strip()
        candidate["email"] = email
        candidate["username"] = email

    @staticmethod
    def _build_hr_query_payload(payload: dict[str, Any]) -> dict[str, Any]:
        def first_non_empty(*keys: str) -> Any:
            for key in keys:
                value = payload.get(key)
                if IdentityDomainTools._is_missing_or_placeholder(value):
                    continue
                if isinstance(value, str):
                    value = value.strip()
                return value
            return None

        hr_payload: dict[str, Any] = {}
        mappings: list[tuple[str, tuple[str, ...]]] = [
            ("emp_id", ("emp_id", "employee_id")),
            ("email", ("email",)),
            ("first_name", ("first_name", "given_name")),
            ("last_name", ("last_name", "family_name")),
            ("first_name_kanji", ("first_name_kanji", "given_name_kanji")),
            ("last_name_kanji", ("last_name_kanji", "family_name_kanji")),
        ]
        for target_key, aliases in mappings:
            value = first_non_empty(*aliases)
            if value is not None:
                hr_payload[target_key] = value
        return hr_payload

    @staticmethod
    def _build_hr_query_payload_candidates(primary_payload: dict[str, Any]) -> list[dict[str, Any]]:
        payloads = [primary_payload]
        has_name_condition = any(
            key in primary_payload for key in ("first_name", "last_name", "first_name_kanji", "last_name_kanji")
        )
        if "email" in primary_payload and has_name_condition:
            relaxed_payload = {k: v for k, v in primary_payload.items() if k != "email"}
            if relaxed_payload and relaxed_payload not in payloads:
                payloads.append(relaxed_payload)
        return payloads

    @staticmethod
    def _is_missing_or_placeholder(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return True
            if UNRESOLVED_REF_PATTERN.match(stripped):
                return True
        return False

    @classmethod
    def _set_if_missing(cls, target: dict[str, Any], key: str, value: Any) -> None:
        if cls._is_missing_or_placeholder(value):
            return
        if cls._is_missing_or_placeholder(target.get(key)):
            target[key] = value.strip() if isinstance(value, str) else value

    def list_groups(self, payload: dict[str, Any]) -> NormalizedResponse:
        return self.group_tools.list_groups(payload)

    def get_group(self, payload: dict[str, Any]) -> NormalizedResponse:
        return self.group_tools.get_group(payload)

    def add_user_to_group(self, payload: dict[str, Any]) -> NormalizedResponse:
        return self._change_membership(payload, action="add")

    def remove_user_from_group(self, payload: dict[str, Any]) -> NormalizedResponse:
        return self._change_membership(payload, action="remove")

    def list_user_credentials(self, payload: dict[str, Any]) -> NormalizedResponse:
        return self.credential_tools.list_user_credentials(payload)

    def get_last_successful_login(self, payload: dict[str, Any]) -> NormalizedResponse:
        return self.credential_tools.get_last_successful_login(
            payload=payload,
            resolve_user=self._resolve_user_with_attributes,
        )

    def collect_group_membership_evidence(self, payload: dict[str, Any]) -> NormalizedResponse:
        user_id = str(payload.get("user_id") or "").strip()
        if not user_id:
            return self._missing_input_response("user_id", "GroupMembershipEvidence")

        try:
            response = self.group_tools.list_groups_raw(
                count=payload.get("count", 200),
                attributes=["id", "displayName", "members"],
            )
            groups = extract_resources(response)
            memberships: list[dict[str, Any]] = []
            for group in groups:
                members = group.get("members")
                if not isinstance(members, list):
                    continue
                for member in members:
                    if not isinstance(member, dict):
                        continue
                    if str(member.get("value") or "") == user_id:
                        memberships.append(
                            {
                                "group_id": group.get("id"),
                                "group_name": group.get("displayName"),
                                "member_ref": member,
                            }
                        )
                        break
            return NormalizedResponse.success(
                facts=[f"ユーザー所属グループ証拠 {len(memberships)} 件を収集しました。"],
                interpretation=["members 属性を参照して所属を判定しました。"],
                proposal=["必要に応じて get_group で詳細を確認してください。"],
                data={
                    "user_id": user_id,
                    "group_membership_evidence": memberships,
                    "source_trace": ["/admin/v1/Groups?attributes=members"],
                },
                audit=AuditPayload(
                    target={"resource": "Groups", "user_id": user_id},
                    input_summary={"count": payload.get("count", 200)},
                    decision_reason=["collect_group_membership_evidence 実行"],
                    result="success",
                ),
            )
        except Exception as exc:
            return self._error_response("GroupMembershipEvidence", "collect_group_membership_evidence 失敗", payload, exc)

    def _change_membership(self, payload: dict[str, Any], *, action: str) -> NormalizedResponse:
        operation_name = "add_user_to_group" if action == "add" else "remove_user_from_group"
        self._ensure_a2a_high_risk_guard(payload=payload, operation_name=operation_name)
        user_selector = self._normalize_user_selector(payload)
        group_selector = self._normalize_group_selector(payload)

        try:
            user = self._resolve_user(user_selector)
            group = self._resolve_group(group_selector)
            ensure_membership_change_allowed(bool(user), bool(group))

            if action == "add":
                operations = [{"op": "add", "path": "members", "value": [{"value": user["id"]}]}]
            else:
                operations = [{"op": "remove", "path": f'members[value eq "{user["id"]}"]'}]

            self.group_tools.patch_group_membership(group_id=group["id"], operations=operations)
            return NormalizedResponse.success(
                facts=[f"グループ所属を {action} しました。"],
                interpretation=["一意特定できた対象に対して変更を実行しました。"],
                proposal=["必要に応じて get_group で結果を確認してください。"],
                data={"membership_change": {"action": action, "user_id": user["id"], "group_id": group["id"]}},
                audit=AuditPayload(
                    target={"resource": "GroupMembership", "group_id": group["id"], "user_id": user["id"]},
                    input_summary={"user_selector": user_selector, "group_selector": group_selector},
                    decision_reason=[f"{action}_user_to_group 実行"],
                    result="success",
                ),
            )
        except AmbiguousTargetError as exc:
            return NormalizedResponse.needs_confirmation(
                facts=["対象を一意に特定できませんでした。"],
                interpretation=[str(exc)],
                proposal=["user/group をID指定して再実行してください。"],
                data={"user_selector": user_selector, "group_selector": group_selector},
                audit=AuditPayload(
                    target={"resource": "GroupMembership"},
                    input_summary={"user_selector": user_selector, "group_selector": group_selector},
                    decision_reason=["一意特定失敗"],
                    result="needs_confirmation",
                ),
            )
        except Exception as exc:
            return self._error_response("GroupMembership", f"{action}_user_to_group 失敗", payload, exc)

    @classmethod
    def _normalize_user_selector(cls, payload: dict[str, Any]) -> dict[str, Any]:
        selector = payload.get("user_selector") if isinstance(payload.get("user_selector"), dict) else {}
        source: dict[str, Any] = dict(selector)
        for key in (
            "user_id",
            "id",
            "user_name",
            "username",
            "email",
            "name",
            "emp_id",
            "employee_id",
            "family_name",
            "given_name",
            "last_name",
            "first_name",
            "family_name_kanji",
            "given_name_kanji",
            "last_name_kanji",
            "first_name_kanji",
            "filter",
        ):
            if key not in source and key in payload:
                source[key] = payload.get(key)

        aliases: list[tuple[str, tuple[str, ...]]] = [
            ("id", ("id", "user_id")),
            ("user_name", ("user_name", "username")),
            ("email", ("email",)),
            ("name", ("name", "display_name")),
            ("emp_id", ("emp_id", "employee_id")),
            ("family_name", ("family_name", "last_name")),
            ("given_name", ("given_name", "first_name")),
            ("family_name_kanji", ("family_name_kanji", "last_name_kanji")),
            ("given_name_kanji", ("given_name_kanji", "first_name_kanji")),
            ("filter", ("filter",)),
        ]
        normalized: dict[str, Any] = {}
        for target_key, keys in aliases:
            value: Any | None = None
            for key in keys:
                raw = source.get(key)
                if cls._is_missing_or_placeholder(raw):
                    continue
                value = raw.strip() if isinstance(raw, str) else raw
                break
            if value is not None:
                normalized[target_key] = value
        return normalized

    @classmethod
    def _normalize_group_selector(cls, payload: dict[str, Any]) -> dict[str, Any]:
        selector = payload.get("group_selector") if isinstance(payload.get("group_selector"), dict) else {}
        source: dict[str, Any] = dict(selector)
        for key in ("group_id", "id", "display_name", "group_name", "name", "filter"):
            if key not in source and key in payload:
                source[key] = payload.get(key)

        aliases: list[tuple[str, tuple[str, ...]]] = [
            ("id", ("id", "group_id")),
            ("display_name", ("display_name", "group_name", "name")),
            ("name", ("name", "display_name", "group_name")),
            ("filter", ("filter",)),
        ]
        normalized: dict[str, Any] = {}
        for target_key, keys in aliases:
            value: Any | None = None
            for key in keys:
                raw = source.get(key)
                if cls._is_missing_or_placeholder(raw):
                    continue
                value = raw.strip() if isinstance(raw, str) else raw
                break
            if value is not None:
                normalized[target_key] = value
        return normalized

    @staticmethod
    def _scim_eq(attr: str, value: Any) -> str:
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'{attr} eq "{escaped}"'

    def _enrich_user_selector_from_hr(self, selector: dict[str, Any]) -> dict[str, Any]:
        if not selector or self.hr_tools is None:
            return selector
        if any(
            not self._is_missing_or_placeholder(selector.get(key))
            for key in ("id", "filter", "user_name", "email")
        ):
            return selector

        hr_query_payload = self._build_hr_query_payload(selector)
        if not hr_query_payload and not self._is_missing_or_placeholder(selector.get("name")):
            name = str(selector["name"]).strip()
            if name.endswith("さん"):
                name = name[:-2].strip()
            kanji_parts = [part for part in re.split(r"[ 　]+", name) if part]
            if kanji_parts and all(re.fullmatch(r"[一-龥々]{1,12}", part) for part in kanji_parts):
                hr_query_payload["last_name_kanji"] = kanji_parts[0]
                if len(kanji_parts) >= 2:
                    hr_query_payload["first_name_kanji"] = kanji_parts[1]

        if not hr_query_payload:
            return selector

        hr_result = self.hr_tools.query_hr_database(hr_query_payload)
        if hr_result.status == "error":
            hr_error = hr_result.errors[0] if hr_result.errors else None
            raise AppError(
                code=hr_error.code if hr_error else "hr_lookup_failed",
                message=hr_error.message if hr_error else "HRデータベース照会に失敗しました。",
                retryable=bool(hr_error.retryable) if hr_error else True,
            )

        candidates = (hr_result.data or {}).get("candidates", [])
        if len(candidates) > 1:
            raise AmbiguousTargetError("HR候補が複数見つかりました。emp_id または email を指定してください。")
        if len(candidates) != 1:
            return selector

        source = candidates[0]
        enriched = selector.copy()
        self._set_if_missing(enriched, "email", source.get("email"))
        self._set_if_missing(enriched, "user_name", source.get("email"))
        self._set_if_missing(enriched, "family_name", source.get("last_name"))
        self._set_if_missing(enriched, "given_name", source.get("first_name"))
        self._set_if_missing(enriched, "family_name_kanji", source.get("last_name_kanji"))
        self._set_if_missing(enriched, "given_name_kanji", source.get("first_name_kanji"))
        if self._is_missing_or_placeholder(enriched.get("name")):
            if not self._is_missing_or_placeholder(enriched.get("family_name_kanji")):
                family = str(enriched["family_name_kanji"]).strip()
                given = str(enriched.get("given_name_kanji") or "").strip()
                enriched["name"] = f"{family} {given}".strip() if given else family
        return enriched

    def _resolve_user(self, selector: dict[str, Any], attributes: list[str] | None = None) -> dict[str, Any]:
        if selector.get("id"):
            return self.user_tools.get_user_raw(user_id=str(selector["id"]), attributes=attributes)

        selector = self._enrich_user_selector_from_hr(selector)
        filter_expr = selector.get("filter")
        if not filter_expr and selector.get("user_name"):
            filter_expr = self._scim_eq("userName", selector["user_name"])
        if not filter_expr and selector.get("email"):
            filter_expr = self._scim_eq("emails.value", selector["email"])
        if not filter_expr and selector.get("name"):
            filter_expr = self._scim_eq("displayName", selector["name"])

        response = self.user_tools.list_users_raw(filter_expr=filter_expr, count=2, attributes=attributes)
        resources = extract_resources(response)
        selector_for_resolution = selector.copy()
        if selector_for_resolution.get("user_name") or selector_for_resolution.get("email"):
            selector_for_resolution.pop("name", None)
            selector_for_resolution.pop("display_name", None)
        return resolve_by_selector(resources, selector_for_resolution, id_key="id", name_keys=("displayName", "userName"))

    def _resolve_group(self, selector: dict[str, Any]) -> dict[str, Any]:
        if selector.get("id"):
            return self.group_tools.get_group_raw(group_id=str(selector["id"]))

        filter_expr = selector.get("filter")
        if not filter_expr and selector.get("display_name"):
            filter_expr = self._scim_eq("displayName", selector["display_name"])
        if not filter_expr and selector.get("name"):
            filter_expr = self._scim_eq("displayName", selector["name"])

        response = self.group_tools.list_groups_raw(filter_expr=filter_expr, count=2)
        resources = extract_resources(response)
        return resolve_by_selector(resources, selector, id_key="id", name_keys=("displayName",))

    def _resolve_user_with_attributes(
        self,
        selector: dict[str, Any],
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._resolve_user(selector, attributes=attributes)

    def _missing_input_response(self, field_name: str, resource: str) -> NormalizedResponse:
        return NormalizedResponse.error(
            message=f"{field_name} が必要です。",
            code="missing_input",
            retryable=False,
            proposal=[f"{field_name} を指定して再実行してください。"],
            audit=AuditPayload(
                target={"resource": resource},
                input_summary={"missing": field_name},
                decision_reason=["必須入力不足"],
                result="error",
            ),
        )

    def _error_response(
        self,
        resource: str,
        reason: str,
        payload: dict[str, Any],
        exc: Exception,
    ) -> NormalizedResponse:
        app_error = classify_exception(exc)
        return NormalizedResponse.error(
            message=app_error.message,
            code=app_error.code,
            retryable=app_error.retryable,
            proposal=["入力条件・権限・認証情報を確認して再実行してください。"],
            audit=AuditPayload(
                target={"resource": resource},
                input_summary={"keys": sorted(payload.keys())},
                decision_reason=[reason],
                result="error",
            ),
        )

    @staticmethod
    def _ensure_a2a_high_risk_guard(*, payload: dict[str, Any], operation_name: str) -> None:
        context = payload.get("__a2a_context")
        if not isinstance(context, dict):
            return
        if operation_name not in HIGH_RISK_TOOLS:
            return
        idempotency_key = str(context.get("idempotency_key") or "").strip()
        if idempotency_key:
            return
        raise AppError(
            code="idempotency_conflict",
            message=f"A2A経由の高リスク操作 `{operation_name}` には idempotency_key が必要です。",
            retryable=False,
        )
