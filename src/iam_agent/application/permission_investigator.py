from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any
import uuid

from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.domain.models import InvestigationRequest, UserResolutionCandidate, UserResolutionResult
from iam_agent.tools.target_resolution import (
    build_hr_query_from_hint,
    extract_user_hint,
    resolve_user_with_hr,
)


class PermissionInvestigator:
    def __init__(self, skill_executor: SkillExecutor) -> None:
        self.skill_executor = skill_executor

    def investigate(self, *, turn_id: str, user_input: str) -> NormalizedResponse:
        request_id = f"inv-{uuid.uuid4()}"
        request = InvestigationRequest(
            request_id=request_id,
            request_type="permission_investigation",
            raw_prompt=user_input,
            intent_confidence=0.9,
        )

        user_hint = extract_user_hint(user_input)
        if not user_hint:
            return NormalizedResponse.needs_confirmation(
                facts=["対象ユーザーを特定する情報が不足しています。"],
                interpretation=["氏名・メールアドレス・社員番号のいずれかが必要です。"],
                proposal=["例: 「山田太郎さんは何ができますか？」のように対象ユーザーを指定してください。"],
                data={"missing_fields": ["user_hint"]},
                audit=AuditPayload(
                    target={"request_type": request.request_type},
                    input_summary={"turn_id": turn_id},
                    decision_reason=["権限調査の対象不足"],
                    result="needs_confirmation",
                ),
            )

        list_users_result = self.skill_executor.execute(
            "list_users",
            {
                "count": 200,
                "attributes": ["id", "ocid", "userName", "displayName", "emails", "groups"],
            },
        )
        if list_users_result.status != "success":
            return self._from_skill_error(list_users_result, "list_users 失敗")

        users = (list_users_result.normalized_data or {}).get("users", [])
        if not isinstance(users, list):
            users = []

        hr_candidates: list[dict[str, Any]] = []
        hr_query = build_hr_query_from_hint(user_hint)
        if hr_query:
            hr_result = self.skill_executor.execute("query_hr_database", hr_query)
            if hr_result.status == "success":
                data = hr_result.normalized_data or {}
                candidates = data.get("candidates")
                if isinstance(candidates, list):
                    hr_candidates = [item for item in candidates if isinstance(item, dict)]

        resolution = resolve_user_with_hr(
            request_id=request.request_id,
            users=[item for item in users if isinstance(item, dict)],
            hint=user_hint,
            hr_candidates=hr_candidates,
        )

        if resolution.status == "ambiguous":
            return NormalizedResponse.needs_confirmation(
                facts=["対象ユーザー候補が複数あり一意に特定できません。"],
                interpretation=["自動選択は禁止のため確認が必要です。"],
                proposal=["メールアドレスまたは社員番号を指定してください。"],
                data={
                    "resolution": asdict(resolution),
                    "required_confirmation_fields": resolution.required_confirmation_fields,
                },
                audit=AuditPayload(
                    target={"request_type": request.request_type},
                    input_summary={"user_hint": user_hint},
                    decision_reason=["ユーザー同定が曖昧"],
                    result="needs_confirmation",
                ),
            )
        if resolution.status in {"insufficient", "not_found"}:
            return NormalizedResponse.error(
                message="対象ユーザーを特定できませんでした。",
                code="insufficient_input" if resolution.status == "insufficient" else "not_found",
                retryable=False,
                proposal=["氏名・メールアドレス・社員番号のいずれかを追加してください。"],
                audit=AuditPayload(
                    target={"request_type": request.request_type},
                    input_summary={"user_hint": user_hint},
                    decision_reason=["ユーザー同定失敗"],
                    result="error",
                ),
            )

        resolved = resolution.selected_user
        if resolved is None:
            return NormalizedResponse.error(
                message="ユーザー同定結果が不正です。",
                code="resolution_invalid",
                retryable=False,
                proposal=["対象ユーザー情報を指定して再実行してください。"],
                audit=AuditPayload(result="error"),
            )

        user_id = resolved.oci_user_id or self._find_user_id_by_email(users, resolved.email)
        user: dict[str, Any] | None = None
        fallback_selector: dict[str, Any] = {}

        if not user_id:
            fallback_selector = self._build_fallback_user_selector(
                user_hint=user_hint,
                resolved=resolved,
                hr_candidates=hr_candidates,
            )
            if fallback_selector:
                fallback_result = self.skill_executor.execute(
                    "get_user",
                    {
                        "user_selector": fallback_selector,
                        "attributes": ["id", "ocid", "userName", "displayName", "groups", "emails"],
                    },
                )
                if fallback_result.status == "success":
                    payload = fallback_result.normalized_data or {}
                    candidate_user = payload.get("user")
                    if isinstance(candidate_user, dict):
                        user = candidate_user
                        user_id = str(user.get("id") or user.get("ocid") or "").strip()
                        if user_id:
                            resolved.oci_user_id = user_id
                            if not resolved.username:
                                resolved.username = str(user.get("userName") or "")
                            if not resolved.display_name:
                                resolved.display_name = str(user.get("displayName") or user.get("userName") or "")
                            if not resolved.email:
                                resolved.email = self._extract_email_from_user(candidate_user)

        if not user_id:
            has_concrete_identity = any(
                fallback_selector.get(key)
                for key in ("email", "user_name", "emp_id")
            )
            if has_concrete_identity:
                return NormalizedResponse.needs_confirmation(
                    facts=["HR候補は特定できましたが、OCIユーザーは見つかりませんでした。"],
                    interpretation=["指定されたユーザーは OCI Identity Domains に未登録の可能性があります。"],
                    proposal=["必要であれば「加藤さんをOCIユーザーとして作成してください」と指示してください。"],
                    data={"resolution": asdict(resolution), "attempted_user_selector": fallback_selector},
                    audit=AuditPayload(result="needs_confirmation"),
                )
            return NormalizedResponse.needs_confirmation(
                facts=["HR候補は特定できましたが、OCIユーザーIDへ解決できません。"],
                interpretation=["OCI側の一致候補が見つからないため調査を継続できません。"],
                proposal=["対象ユーザーのメールアドレスまたは userName を指定してください。"],
                data={"resolution": asdict(resolution), "attempted_user_selector": fallback_selector},
                audit=AuditPayload(result="needs_confirmation"),
            )

        if user is None:
            get_user_result = self.skill_executor.execute(
                "get_user",
                {"user_id": user_id, "attributes": ["id", "ocid", "userName", "displayName", "groups"]},
            )
            if get_user_result.status != "success":
                return self._from_skill_error(get_user_result, "get_user 失敗")
            loaded_user = (get_user_result.normalized_data or {}).get("user", {})
            user = loaded_user if isinstance(loaded_user, dict) else {}

        groups = self._extract_group_names(user)

        if not groups:
            evidence_result = self.skill_executor.execute("list_groups", {"count": 200, "attributes": ["id", "displayName", "members"]})
            if evidence_result.status == "success":
                groups = self._extract_groups_from_memberships(user_id=user_id, groups=(evidence_result.normalized_data or {}).get("groups", []))

        policies_result = self.skill_executor.execute("list_policies", {})
        if policies_result.status != "success":
            return self._from_skill_error(policies_result, "list_policies 失敗")
        policies = (policies_result.normalized_data or {}).get("policies", [])
        if not isinstance(policies, list):
            policies = []

        matched_policy_statements = self._match_policies(groups=groups, policies=policies)
        last_login_result = self.skill_executor.execute("get_last_successful_login", {"user_selector": {"id": user_id}})
        last_login = None
        if last_login_result.status == "success":
            last_login = (last_login_result.normalized_data or {}).get("last_successful_login_at")

        facts = [
            f"対象ユーザー: {user.get('displayName') or user.get('userName') or resolved.display_name}",
            f"所属グループ: {', '.join(groups) if groups else 'なし'}",
            f"関連ポリシー文: {len(matched_policy_statements)} 件",
        ]
        facts.extend(self._build_statement_excerpt_facts(matched_policy_statements))
        if last_login:
            facts.append(f"最終ログイン: {last_login}")

        interpretation = [
            self._interpret_permissions(groups=groups, statements=matched_policy_statements),
        ]
        interpretation.extend(self._build_concrete_permission_interpretation(matched_policy_statements))
        interpretation.append("ポリシー文をグループ名で紐付けて実効権限を推定しています。")
        proposal = self._build_proposals(groups=groups, matched_policy_statements=matched_policy_statements, last_login=last_login)

        return NormalizedResponse.success(
            facts=facts,
            interpretation=interpretation,
            proposal=proposal,
            data={
                "request_id": request.request_id,
                "request_type": request.request_type,
                "user_resolution": asdict(resolution),
                "group_names": groups,
                "policy_evidence": matched_policy_statements,
                "last_successful_login_at": last_login,
            },
            audit=AuditPayload(
                target={"request_type": request.request_type, "user_id": user_id},
                input_summary={"user_hint": user_hint},
                decision_reason=["resolve_user", "collect_groups", "collect_policies", "derive_effective_permissions"],
                result="success",
            ),
        )

    @staticmethod
    def _find_user_id_by_email(users: list[Any], email: str) -> str:
        if not email:
            return ""
        for user in users:
            if not isinstance(user, dict):
                continue
            user_name = str(user.get("userName") or "").lower()
            if user_name == email.lower():
                return str(user.get("id") or user.get("ocid") or "")
            emails = user.get("emails")
            if isinstance(emails, list):
                for item in emails:
                    if isinstance(item, dict) and str(item.get("value") or "").lower() == email.lower():
                        return str(user.get("id") or user.get("ocid") or "")
        return ""

    @staticmethod
    def _extract_group_names(user: Any) -> list[str]:
        if not isinstance(user, dict):
            return []
        groups = user.get("groups")
        if not isinstance(groups, list):
            return []
        names: list[str] = []
        for item in groups:
            if not isinstance(item, dict):
                continue
            name = str(item.get("display") or item.get("value") or "").strip()
            if name:
                names.append(name)
        return names

    @staticmethod
    def _extract_groups_from_memberships(*, user_id: str, groups: Any) -> list[str]:
        if not isinstance(groups, list):
            return []
        names: list[str] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            members = group.get("members")
            if not isinstance(members, list):
                continue
            matched = any(
                isinstance(member, dict) and str(member.get("value") or "") == user_id
                for member in members
            )
            if matched:
                name = str(group.get("displayName") or group.get("id") or "").strip()
                if name:
                    names.append(name)
        return names

    @staticmethod
    def _match_policies(*, groups: list[str], policies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not groups:
            return []
        normalized_groups = [PermissionInvestigator._normalize_group_name(group) for group in groups]
        matched: list[dict[str, Any]] = []
        for policy in policies:
            statements = policy.get("statements") or []
            if not isinstance(statements, list):
                continue
            for statement in statements:
                if not isinstance(statement, str):
                    continue
                referenced_groups = PermissionInvestigator._extract_referenced_groups(statement)
                matched_groups = [
                    group
                    for group, normalized_group in zip(groups, normalized_groups, strict=False)
                    if normalized_group in referenced_groups
                ]
                if matched_groups:
                    parsed = PermissionInvestigator._parse_statement_components(statement)
                    matched.append(
                        {
                            "policy_id": policy.get("id"),
                            "policy_name": policy.get("name"),
                            "statement": statement,
                            "matched_groups": matched_groups,
                            "action": parsed.get("action"),
                            "resource": parsed.get("resource"),
                            "scope": parsed.get("scope"),
                            "condition": parsed.get("condition"),
                        }
                    )
        return matched

    @staticmethod
    def _normalize_group_name(value: str) -> str:
        normalized = str(value or "").strip().strip("'\"").lower()
        if "/" in normalized:
            normalized = normalized.split("/")[-1].strip().strip("'\"")
        return normalized

    @classmethod
    def _extract_referenced_groups(cls, statement: str) -> set[str]:
        referenced: set[str] = set()
        lower_statement = statement.lower()

        # 1) group 'domain'/'group'
        for match in re.finditer(r"group\s+'[^']+'\s*/\s*'([^']+)'", lower_statement):
            referenced.add(cls._normalize_group_name(match.group(1)))

        # 2) group 'group'
        for match in re.finditer(r"group\s+'([^']+)'", lower_statement):
            referenced.add(cls._normalize_group_name(match.group(1)))

        # 3) group group_name
        for match in re.finditer(r"group\s+([a-z0-9_.-]+)", lower_statement):
            referenced.add(cls._normalize_group_name(match.group(1)))

        return {item for item in referenced if item}

    @classmethod
    def _interpret_permissions(cls, *, groups: list[str], statements: list[dict[str, Any]]) -> str:
        if not groups:
            return "所属グループが確認できないため、グループベースの権限は評価できません。"
        if not statements:
            return "所属グループに直接一致するポリシー文を確認できず、許可操作は限定的と判断されます。"
        operations: list[str] = []
        for item in statements:
            action = str(item.get("action") or "").strip().lower()
            if not action:
                action = cls._extract_action_from_statement(str(item.get("statement") or ""))
            if action:
                operations.append(action)
        unique_operations = sorted(set(operations))
        op_text = ", ".join(unique_operations) if unique_operations else "不明"
        return f"一致ポリシーから、対象ユーザーは主に `{op_text}` レベルの操作が可能と推定されます。"

    @classmethod
    def _build_statement_excerpt_facts(cls, statements: list[dict[str, Any]], *, limit: int = 5) -> list[str]:
        if not statements:
            return []
        sorted_items = sorted(
            statements,
            key=lambda item: (
                cls._action_priority(str(item.get("action") or cls._extract_action_from_statement(str(item.get("statement") or "")))),
                str(item.get("policy_name") or ""),
                str(item.get("statement") or ""),
            ),
        )
        lines: list[str] = ["一致ステートメント抜粋:"]
        for item in sorted_items[:limit]:
            policy_name = str(item.get("policy_name") or "unknown-policy")
            statement = str(item.get("statement") or "").strip()
            if len(statement) > 220:
                statement = f"{statement[:217]}..."
            lines.append(f"[{policy_name}] {statement}")
        if len(sorted_items) > limit:
            lines.append(f"他 {len(sorted_items) - limit} 件")
        return lines

    @classmethod
    def _build_concrete_permission_interpretation(cls, statements: list[dict[str, Any]]) -> list[str]:
        if not statements:
            return []

        grouped: dict[str, dict[str, Any]] = {}
        conditional_count = 0
        for item in statements:
            details = cls._resolve_statement_details(item)
            action = details["action"] or "unknown"
            entry = grouped.setdefault(action, {"count": 0, "resources": [], "scopes": []})
            entry["count"] = int(entry["count"]) + 1
            if details["resource"]:
                entry["resources"].append(details["resource"])
            if details["scope"]:
                entry["scopes"].append(details["scope"])
            if details["condition"]:
                conditional_count += 1

        lines: list[str] = []
        for action in ("manage", "use", "read", "inspect", "unknown"):
            entry = grouped.get(action)
            if not entry:
                continue
            action_desc = cls._describe_action(action)
            resources_text = cls._format_examples([str(v) for v in entry.get("resources", [])], limit=3) or "対象リソース不明"
            scopes_text = cls._format_examples([str(v) for v in entry.get("scopes", [])], limit=2)
            text = f"`{action}` は {resources_text} に対する {action_desc} が可能です（根拠 {entry['count']} 文）"
            if scopes_text:
                text += f"。主なスコープ: {scopes_text}"
            lines.append(text)

        if conditional_count:
            lines.append(f"`where` 条件付きの許可が {conditional_count} 文あり、条件不一致時は拒否される可能性があります。")
        return lines

    @classmethod
    def _resolve_statement_details(cls, item: dict[str, Any]) -> dict[str, str]:
        statement = str(item.get("statement") or "")
        parsed = cls._parse_statement_components(statement)
        action = str(item.get("action") or "").strip().lower() or parsed["action"]
        resource = str(item.get("resource") or "").strip() or parsed["resource"]
        scope = str(item.get("scope") or "").strip() or parsed["scope"]
        condition = str(item.get("condition") or "").strip() or parsed["condition"]
        return {
            "action": action,
            "resource": resource,
            "scope": scope,
            "condition": condition,
        }

    @classmethod
    def _parse_statement_components(cls, statement: str) -> dict[str, str]:
        text = statement.strip()
        matched = re.search(
            (
                r"allow\s+group\s+.+?\s+to\s+"
                r"(?P<action>manage|use|read|inspect)\s+"
                r"(?P<resource>.+?)(?=\s+in\s+|\s+where\s+|$)"
                r"(?:\s+in\s+(?P<scope>.+?))?"
                r"(?:\s+where\s+(?P<condition>.+))?$"
            ),
            text,
            flags=re.IGNORECASE,
        )
        action = str(matched.group("action") or "").lower().strip() if matched else ""
        resource = str(matched.group("resource") or "").strip() if matched else ""
        scope = str(matched.group("scope") or "").strip() if matched else ""
        condition = str(matched.group("condition") or "").strip() if matched else ""

        if not action:
            action = cls._extract_action_from_statement(text)
        if not resource:
            resource_match = re.search(
                r"\b(?:manage|use|read|inspect)\s+(.+?)(?=\s+in\s+|\s+where\s+|$)",
                text,
                flags=re.IGNORECASE,
            )
            if resource_match:
                resource = str(resource_match.group(1) or "").strip()
        if not scope:
            scope_match = re.search(r"\sin\s+(.+?)(?:\s+where\s+|$)", text, flags=re.IGNORECASE)
            if scope_match:
                scope = str(scope_match.group(1) or "").strip()
        if not condition:
            where_match = re.search(r"\swhere\s+(.+)$", text, flags=re.IGNORECASE)
            if where_match:
                condition = str(where_match.group(1) or "").strip()
        return {
            "action": action,
            "resource": resource,
            "scope": scope,
            "condition": condition,
        }

    @staticmethod
    def _extract_action_from_statement(statement: str) -> str:
        lowered = statement.lower()
        for action in ("manage", "use", "read", "inspect"):
            if f" {action} " in lowered:
                return action
        return ""

    @staticmethod
    def _action_priority(action: str) -> int:
        normalized = str(action or "").strip().lower()
        order = {"manage": 0, "use": 1, "read": 2, "inspect": 3}
        return order.get(normalized, 9)

    @staticmethod
    def _describe_action(action: str) -> str:
        normalized = str(action or "").strip().lower()
        mapping = {
            "manage": "作成・更新・削除を含む管理操作",
            "use": "利用系操作",
            "read": "詳細参照操作",
            "inspect": "一覧・属性参照操作",
            "unknown": "操作内容未分類",
        }
        return mapping.get(normalized, "操作内容未分類")

    @staticmethod
    def _format_examples(values: list[str], *, limit: int) -> str:
        uniq: list[str] = []
        for raw in values:
            value = str(raw or "").strip()
            if not value:
                continue
            if value in uniq:
                continue
            uniq.append(value)
        if not uniq:
            return ""
        selected = [f"`{item}`" for item in uniq[:limit]]
        suffix = " など" if len(uniq) > limit else ""
        return ", ".join(selected) + suffix

    @staticmethod
    def _build_proposals(*, groups: list[str], matched_policy_statements: list[dict[str, Any]], last_login: Any) -> list[str]:
        proposals: list[str] = []
        if not groups:
            proposals.append("対象ユーザーの所属グループを確認し、必要なグループへ追加してください。")
        if groups and not matched_policy_statements:
            proposals.append("所属グループに対応するポリシーが不足していないか確認してください。")
        if last_login in (None, ""):
            proposals.append("必要に応じて最終ログイン情報を再確認し、休眠アカウント運用ルールを適用してください。")
        else:
            proposals.append("必要な操作に対して過不足がないか、該当ポリシーの statement をレビューしてください。")
        return proposals or ["必要な操作と対象リソースを指定すると、より詳細な権限評価ができます。"]

    @staticmethod
    def _from_skill_error(result: Any, reason: str) -> NormalizedResponse:
        return NormalizedResponse.error(
            message=result.error_message or "調査中にエラーが発生しました。",
            code=result.error_code or "execution_error",
            retryable=bool(result.retryable),
            proposal=["権限・認証情報・入力条件を確認して再実行してください。"],
            audit=AuditPayload(
                target={"tool": result.tool_name if hasattr(result, "tool_name") else "unknown"},
                input_summary={},
                decision_reason=[reason],
                result="error",
            ),
        )

    @staticmethod
    def _extract_email_from_user(user: dict[str, Any]) -> str:
        user_name = str(user.get("userName") or "").strip()
        if "@" in user_name:
            return user_name
        emails = user.get("emails")
        if isinstance(emails, list):
            for item in emails:
                if isinstance(item, dict) and item.get("primary") and item.get("value"):
                    return str(item.get("value"))
            for item in emails:
                if isinstance(item, dict) and item.get("value"):
                    return str(item.get("value"))
        return ""

    @staticmethod
    def _build_fallback_user_selector(
        *,
        user_hint: dict[str, Any],
        resolved: UserResolutionCandidate,
        hr_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        selector: dict[str, Any] = {}

        if resolved.email:
            selector["email"] = resolved.email
            selector["user_name"] = resolved.email
        if resolved.username and "@" in resolved.username and "email" not in selector:
            selector["email"] = resolved.username
            selector["user_name"] = resolved.username

        for key in ("emp_id", "name", "family_name", "given_name", "family_name_kanji", "given_name_kanji", "email", "user_name"):
            value = user_hint.get(key)
            if value not in (None, ""):
                selector.setdefault(key, value)

        if len(hr_candidates) == 1:
            candidate = hr_candidates[0]
            mapping = {
                "email": "email",
                "user_name": "email",
                "emp_id": "emp_id",
                "family_name": "last_name",
                "given_name": "first_name",
                "family_name_kanji": "last_name_kanji",
                "given_name_kanji": "first_name_kanji",
            }
            for target, source in mapping.items():
                value = candidate.get(source)
                if value not in (None, ""):
                    selector.setdefault(target, value)

            if "name" not in selector:
                family_kanji = str(candidate.get("last_name_kanji") or "").strip()
                given_kanji = str(candidate.get("first_name_kanji") or "").strip()
                if family_kanji:
                    selector["name"] = f"{family_kanji} {given_kanji}".strip() if given_kanji else family_kanji
                else:
                    family = str(candidate.get("last_name") or "").strip()
                    given = str(candidate.get("first_name") or "").strip()
                    if family:
                        selector["name"] = f"{family} {given}".strip() if given else family

        return selector
