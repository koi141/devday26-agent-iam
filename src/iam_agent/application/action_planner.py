from __future__ import annotations

import re
import uuid
from typing import Any, Callable

from iam_agent.application.input_guard import TOOL_REQUIRED_INPUTS
from iam_agent.domain.models import ActionPlan, ActionPlanStep
from iam_agent.infra.clients.genai_client import GenAIClient


AVAILABLE_TOOLS = list(TOOL_REQUIRED_INPUTS.keys())
UNRESOLVED_REF_PATTERN = re.compile(r"^\s*(?:\$\{[^{}]+\}|\{\{[^{}]+\}\})\s*$")
CREATE_USER_INPUT_ALIASES = {
    "user_name": "username",
    "first_name": "given_name",
    "last_name": "family_name",
    "first_name_kanji": "given_name_kanji",
    "last_name_kanji": "family_name_kanji",
}
CREATE_USER_INTENT_USER_HINTS = (
    "ociユーザー",
    "oci user",
    "ユーザーとして",
    "ユーザーを",
    "アカウントとして",
)
CREATE_USER_INTENT_ACTION_HINTS = ("作成", "追加", "登録", "発行", "create", "provision")
GROUP_MEMBERSHIP_ADD_HINTS = ("追加", "アサイン", "所属", "参加", "入れ", "付与", "add", "assign", "join")
GROUP_MEMBERSHIP_REMOVE_HINTS = ("削除", "解除", "外し", "除外", "remove", "unassign", "detach")
PERMISSION_INVESTIGATION_HINTS = (
    "何ができます",
    "何ができる",
    "権限を教えて",
    "できること",
    "許可されている操作",
    "何の操作が許可",
    "どのような操作を許可",
    "どのような操作が許可",
    "どの操作が許可",
    "許可されていますか",
    "許可されているか",
    "許可されている",
    "権限調査",
)
ACCESS_DENIAL_HINTS = (
    "アクセス拒否",
    "アクセスできない",
    "権限不足",
    "not authorized",
    "denied",
    "拒否され",
    "トラブルシュート",
)
POLICY_IMPACT_HINTS = ("影響", "削除", "消す", "delete", "remove")
DELEGATION_HINTS = ("他エージェント", "別エージェント", "委譲", "delegate", "a2a")


class ActionPlanner:
    def __init__(
        self,
        genai_client: GenAIClient,
        observation_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.genai_client = genai_client
        self.observation_hook = observation_hook

    @staticmethod
    def _is_unresolved_ref(value: Any) -> bool:
        return isinstance(value, str) and bool(UNRESOLVED_REF_PATTERN.match(value))

    def _normalize_provided_inputs(self, tool_name: str, provided: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in provided.items():
            normalized_key = str(key)
            if tool_name == "create_user":
                normalized_key = CREATE_USER_INPUT_ALIASES.get(normalized_key, normalized_key)

            if self._is_unresolved_ref(value):
                continue

            normalized[normalized_key] = value
        return normalized

    @staticmethod
    def _has_any_hint(text: str, hints: tuple[str, ...]) -> bool:
        return any(hint in text for hint in hints)

    def _is_create_user_intent(self, user_input: str) -> bool:
        text = user_input.strip()
        if not text:
            return False

        lowered = text.lower()
        has_user_hint = self._has_any_hint(lowered, CREATE_USER_INTENT_USER_HINTS)
        has_action_hint = self._has_any_hint(lowered, CREATE_USER_INTENT_ACTION_HINTS)
        refers_group_membership = ("グループ" in text) or ("group" in lowered)
        return has_user_hint and has_action_hint and not refers_group_membership

    def _group_membership_action(self, user_input: str) -> str | None:
        text = user_input.strip()
        if not text:
            return None

        lowered = text.lower()
        refers_group = ("グループ" in text) or ("group" in lowered)
        if not refers_group:
            return None

        has_add = self._has_any_hint(lowered, GROUP_MEMBERSHIP_ADD_HINTS)
        has_remove = self._has_any_hint(lowered, GROUP_MEMBERSHIP_REMOVE_HINTS)
        if has_remove and not has_add:
            return "remove"
        if has_add and not has_remove:
            return "add"
        if has_remove:
            return "remove"
        if has_add:
            return "add"
        return None

    def _is_permission_investigation_intent(self, user_input: str) -> bool:
        text = user_input.strip().lower()
        if not text:
            return False
        if self._has_any_hint(text, ACCESS_DENIAL_HINTS):
            return False
        if ("操作" in text or "権限" in text) and ("許可" in text):
            return True
        return self._has_any_hint(text, PERMISSION_INVESTIGATION_HINTS)

    def _is_access_denial_intent(self, user_input: str) -> bool:
        text = user_input.strip().lower()
        if not text:
            return False
        return self._has_any_hint(text, ACCESS_DENIAL_HINTS)

    def _detect_request_type(self, user_input: str) -> str:
        if self._is_access_denial_intent(user_input):
            return "access_denial_troubleshooting"
        if self._is_permission_investigation_intent(user_input):
            return "permission_investigation"
        return "single_tool_passthrough"

    def _is_delegation_intent(self, user_input: str) -> bool:
        text = user_input.strip().lower()
        if not text:
            return False
        return self._has_any_hint(text, DELEGATION_HINTS)

    @staticmethod
    def _infer_delegation_operation(user_input: str) -> str:
        text = user_input.lower()
        if "ポリシ" in user_input or "policy" in text:
            return "list_policies"
        if "コンパートメント" in user_input or "compartment" in text:
            return "list_compartments"
        if ("リソース" in user_input and "一覧" in user_input) or ("resource" in text and "list" in text):
            return "list_resources"
        if "ユーザー一覧" in user_input or "list users" in text:
            return "list_users"
        return "list_users"

    def _build_delegation_plan(self, *, plan_id: str, turn_id: str, user_input: str) -> ActionPlan:
        requested_operation = self._infer_delegation_operation(user_input)
        step = ActionPlanStep(
            step_id="step-1",
            tool_name="delegate_to_peer",
            required_inputs=TOOL_REQUIRED_INPUTS.get("delegate_to_peer", []),
            provided_inputs={
                "objective": user_input.strip(),
                "requested_operation": requested_operation,
                "input_payload": {"raw_prompt": user_input.strip()},
            },
            execution_order=1,
            reason="他エージェントへの委譲意図を検知",
        )
        return ActionPlan(
            plan_id=plan_id,
            turn_id=turn_id,
            skill_name="single_tool_passthrough",
            request_type="single_tool_passthrough",
            steps=[step],
            planned_by_model="heuristic",
            plan_reasoning_summary=["委譲意図を検知したため delegate_to_peer を選択"],
        )

    def _build_permission_investigation_plan(self, *, plan_id: str, turn_id: str) -> ActionPlan:
        steps = [
            ActionPlanStep(
                step_id="step-1",
                tool_name="list_users",
                required_inputs=TOOL_REQUIRED_INPUTS.get("list_users", []),
                provided_inputs={"count": 200, "attributes": ["id", "ocid", "displayName", "userName", "emails", "groups"]},
                execution_order=1,
                reason="対象ユーザー候補を収集",
            ),
            ActionPlanStep(
                step_id="step-2",
                tool_name="query_hr_database",
                required_inputs=TOOL_REQUIRED_INPUTS.get("query_hr_database", []),
                provided_inputs={},
                execution_order=2,
                reason="不足時のHR補完",
            ),
            ActionPlanStep(
                step_id="step-3",
                tool_name="get_user",
                required_inputs=TOOL_REQUIRED_INPUTS.get("get_user", []),
                provided_inputs={},
                execution_order=3,
                reason="対象ユーザー詳細を取得",
            ),
            ActionPlanStep(
                step_id="step-4",
                tool_name="list_groups",
                required_inputs=TOOL_REQUIRED_INPUTS.get("list_groups", []),
                provided_inputs={"attributes": ["id", "displayName", "members"], "count": 200},
                execution_order=4,
                reason="所属グループ証拠を収集",
            ),
            ActionPlanStep(
                step_id="step-5",
                tool_name="list_policies",
                required_inputs=TOOL_REQUIRED_INPUTS.get("list_policies", []),
                provided_inputs={},
                execution_order=5,
                reason="関連ポリシーを収集",
            ),
            ActionPlanStep(
                step_id="step-6",
                tool_name="get_last_successful_login",
                required_inputs=TOOL_REQUIRED_INPUTS.get("get_last_successful_login", []),
                provided_inputs={},
                execution_order=6,
                reason="最終ログインを補足",
            ),
        ]
        return ActionPlan(
            plan_id=plan_id,
            turn_id=turn_id,
            skill_name="user_permission_investigation",
            request_type="permission_investigation",
            steps=steps,
            planned_by_model="heuristic",
            plan_reasoning_summary=["権限調査意図を検知したため複合ワークフローを選択"],
        )

    def _build_access_denial_plan(self, *, plan_id: str, turn_id: str) -> ActionPlan:
        steps = [
            ActionPlanStep(
                step_id="step-1",
                tool_name="list_users",
                required_inputs=TOOL_REQUIRED_INPUTS.get("list_users", []),
                provided_inputs={"count": 200, "attributes": ["id", "ocid", "displayName", "userName", "emails", "groups"]},
                execution_order=1,
                reason="対象ユーザー候補を収集",
            ),
            ActionPlanStep(
                step_id="step-2",
                tool_name="query_hr_database",
                required_inputs=TOOL_REQUIRED_INPUTS.get("query_hr_database", []),
                provided_inputs={},
                execution_order=2,
                reason="不足時のHR補完",
            ),
            ActionPlanStep(
                step_id="step-3",
                tool_name="get_user",
                required_inputs=TOOL_REQUIRED_INPUTS.get("get_user", []),
                provided_inputs={},
                execution_order=3,
                reason="ユーザー属性と制約情報を取得",
            ),
            ActionPlanStep(
                step_id="step-4",
                tool_name="list_groups",
                required_inputs=TOOL_REQUIRED_INPUTS.get("list_groups", []),
                provided_inputs={"attributes": ["id", "displayName", "members"], "count": 200},
                execution_order=4,
                reason="所属グループ証拠を収集",
            ),
            ActionPlanStep(
                step_id="step-5",
                tool_name="list_policies",
                required_inputs=TOOL_REQUIRED_INPUTS.get("list_policies", []),
                provided_inputs={},
                execution_order=5,
                reason="アクセス拒否に関連するポリシー候補を収集",
            ),
            ActionPlanStep(
                step_id="step-6",
                tool_name="get_policy",
                required_inputs=TOOL_REQUIRED_INPUTS.get("get_policy", []),
                provided_inputs={},
                execution_order=6,
                reason="必要に応じた個別ポリシー確認",
            ),
        ]
        return ActionPlan(
            plan_id=plan_id,
            turn_id=turn_id,
            skill_name="access_denial_troubleshooting",
            request_type="access_denial_troubleshooting",
            steps=steps,
            planned_by_model="heuristic",
            plan_reasoning_summary=["アクセス拒否トラブルシュート意図を検知したため複合ワークフローを選択"],
        )

    def _build_create_user_step(self, provided_inputs: dict[str, Any], reason: str) -> ActionPlanStep:
        return ActionPlanStep(
            step_id="step-1",
            tool_name="create_user",
            required_inputs=TOOL_REQUIRED_INPUTS.get("create_user", []),
            provided_inputs=provided_inputs,
            execution_order=1,
            reason=reason,
        )

    def _build_group_membership_step(
        self,
        *,
        action: str,
        provided_inputs: dict[str, Any],
        reason: str,
    ) -> ActionPlanStep:
        tool_name = "add_user_to_group" if action == "add" else "remove_user_from_group"
        return ActionPlanStep(
            step_id="step-1",
            tool_name=tool_name,
            required_inputs=TOOL_REQUIRED_INPUTS.get(tool_name, []),
            provided_inputs=provided_inputs,
            execution_order=1,
            reason=reason,
        )

    def _enforce_create_user_intent(
        self,
        *,
        user_input: str,
        steps: list[ActionPlanStep],
        inferred_create_user_inputs: dict[str, Any],
    ) -> list[ActionPlanStep]:
        if not self._is_create_user_intent(user_input):
            return steps

        for step in steps:
            if step.tool_name != "create_user":
                continue
            merged = step.provided_inputs.copy()
            for key, value in inferred_create_user_inputs.items():
                merged.setdefault(key, value)
            return [
                self._build_create_user_step(
                    provided_inputs=merged,
                    reason="OCIユーザー作成/追加意図のため create_user を優先",
                )
            ]

        return [
            self._build_create_user_step(
                provided_inputs=inferred_create_user_inputs.copy(),
                reason="OCIユーザー作成/追加意図のため create_user を優先",
            )
        ]

    @staticmethod
    def _extract_group_selector(text: str) -> dict[str, Any]:
        selector: dict[str, Any] = {}
        quoted = re.search(r"[「\"']([^「」\"']{1,80})[」\"']\s*グループ", text)
        if quoted:
            group_name = quoted.group(1).strip().strip("。.,")
            if group_name:
                selector["display_name"] = group_name
                return selector

        inline = re.search(r"([A-Za-z0-9_.:-]{2,128})\s*グループ", text)
        if inline:
            group_name = inline.group(1).strip().strip("。.,")
            if group_name:
                selector["display_name"] = group_name
                return selector

        english = re.search(r"group\s+([A-Za-z0-9_.:-]{2,128})", text, flags=re.IGNORECASE)
        if english:
            group_name = english.group(1).strip().strip("。.,")
            if group_name:
                selector["display_name"] = group_name
        return selector

    def _infer_group_membership_inputs(self, user_input: str) -> dict[str, Any]:
        user_selector: dict[str, Any] = {}
        group_selector = self._extract_group_selector(user_input)
        text = user_input.strip()
        if not text:
            return {"user_selector": user_selector, "group_selector": group_selector}

        email_match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
        if email_match:
            user_selector["email"] = email_match.group(0)

        kanji_match = re.search(r"([一-龥々]{1,12})(?:[ 　]?([一-龥々]{1,12}))?さん", text)
        if kanji_match:
            family = kanji_match.group(1)
            given = kanji_match.group(2)
            user_selector.setdefault("family_name_kanji", family)
            if given:
                user_selector.setdefault("given_name_kanji", given)
                user_selector.setdefault("name", f"{family} {given}")
            else:
                user_selector.setdefault("name", family)

        user_token_match = re.search(r"([A-Za-z0-9._%+\-]{2,64})\s*ユーザー", text)
        if user_token_match:
            token = user_token_match.group(1)
            if "@" in token:
                user_selector.setdefault("email", token)
            else:
                user_selector.setdefault("user_name", token)

        return {"user_selector": user_selector, "group_selector": group_selector}

    @staticmethod
    def _infer_user_selector_inputs(user_input: str) -> dict[str, Any]:
        selector: dict[str, Any] = {}
        text = user_input.strip()
        if not text:
            return selector

        email_match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
        if email_match:
            email = email_match.group(0)
            selector["email"] = email
            selector["user_name"] = email

        emp_match = re.search(r"(?:emp[_ -]?id|社員番号)\s*[:：]?\s*([0-9]{2,12})", text, flags=re.IGNORECASE)
        if emp_match:
            selector["emp_id"] = emp_match.group(1)

        kanji_match = re.search(r"([一-龥々]{1,12})(?:[ 　]?([一-龥々]{1,12}))?さん", text)
        if kanji_match:
            family = kanji_match.group(1)
            given = kanji_match.group(2)
            selector.setdefault("family_name_kanji", family)
            if given:
                selector.setdefault("given_name_kanji", given)
                selector.setdefault("name", f"{family} {given}")
            else:
                selector.setdefault("name", family)

        roman_match = re.search(r"\b([A-Za-z][A-Za-z'\\-]{0,30})\s+([A-Za-z][A-Za-z'\\-]{0,30})\b", text)
        if roman_match:
            selector.setdefault("family_name", roman_match.group(1))
            selector.setdefault("given_name", roman_match.group(2))
        return selector

    def _enforce_user_lookup_inputs(self, *, user_input: str, steps: list[ActionPlanStep]) -> list[ActionPlanStep]:
        inferred_selector = self._infer_user_selector_inputs(user_input)
        if not inferred_selector:
            return steps

        updated_steps: list[ActionPlanStep] = []
        for step in steps:
            if step.tool_name not in {"get_user", "get_last_successful_login"}:
                updated_steps.append(step)
                continue

            merged_inputs = step.provided_inputs.copy()
            existing = merged_inputs.get("user_selector")
            existing_selector = existing if isinstance(existing, dict) else {}
            selector = inferred_selector.copy()
            selector.update(existing_selector)

            if step.tool_name == "get_user" and "user_id" not in merged_inputs and "id" not in selector:
                merged_inputs["user_selector"] = selector
            elif step.tool_name == "get_last_successful_login":
                merged_inputs["user_selector"] = selector

            updated_steps.append(
                ActionPlanStep(
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    required_inputs=step.required_inputs,
                    provided_inputs=merged_inputs,
                    execution_order=step.execution_order,
                    reason=step.reason or "user_id不足時に user_selector から自動解決",
                )
            )
        return updated_steps

    def _enforce_group_membership_intent(self, *, user_input: str, steps: list[ActionPlanStep]) -> list[ActionPlanStep]:
        action = self._group_membership_action(user_input)
        if action is None:
            return steps

        target_tool = "add_user_to_group" if action == "add" else "remove_user_from_group"
        inferred_inputs = self._infer_group_membership_inputs(user_input)
        inferred_user_selector = inferred_inputs.get("user_selector") or {}
        inferred_group_selector = inferred_inputs.get("group_selector") or {}
        reason = "グループ所属変更意図のため対象ツールを優先"

        for step in steps:
            if step.tool_name != target_tool:
                continue
            merged_inputs = step.provided_inputs.copy()
            existing_user_selector = merged_inputs.get("user_selector")
            if not isinstance(existing_user_selector, dict):
                existing_user_selector = {}
            existing_group_selector = merged_inputs.get("group_selector")
            if not isinstance(existing_group_selector, dict):
                existing_group_selector = {}

            user_selector = inferred_user_selector.copy()
            user_selector.update(existing_user_selector)
            group_selector = inferred_group_selector.copy()
            group_selector.update(existing_group_selector)

            if user_selector:
                merged_inputs["user_selector"] = user_selector
            if group_selector:
                merged_inputs["group_selector"] = group_selector
            return [self._build_group_membership_step(action=action, provided_inputs=merged_inputs, reason=reason)]

        provided_inputs: dict[str, Any] = {}
        if inferred_user_selector:
            provided_inputs["user_selector"] = inferred_user_selector
        if inferred_group_selector:
            provided_inputs["group_selector"] = inferred_group_selector
        return [self._build_group_membership_step(action=action, provided_inputs=provided_inputs, reason=reason)]

    def _fallback_tool(self, user_input: str) -> str:
        text = user_input.lower()
        membership_action = self._group_membership_action(user_input)
        if membership_action == "add":
            return "add_user_to_group"
        if membership_action == "remove":
            return "remove_user_from_group"
        if ("リソース" in user_input and ("一覧" in user_input or "list" in text)) or (
            "resource" in text and "list" in text
        ):
            return "list_resources"
        if "ポリシ" in user_input or "policy" in text:
            if self._infer_policy_inputs(user_input):
                return "get_policy"
            return "list_policies"
        if "コンパートメント" in user_input or "compartment" in text:
            return "list_compartments"
        if "グループ" in user_input or "group" in text:
            return "list_groups"
        if "作成" in user_input or "create" in text:
            return "create_user"
        return "list_users"

    def _infer_create_user_inputs(self, user_input: str) -> dict[str, Any]:
        inferred: dict[str, Any] = {}
        text = user_input.strip()
        if not text:
            return inferred

        email_match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
        if email_match:
            email = email_match.group(0)
            inferred["email"] = email
            inferred["username"] = email

        kanji_match = re.search(r"([一-龥々]{1,12})(?:[ 　]?([一-龥々]{1,12}))?さん", text)
        if kanji_match:
            family = kanji_match.group(1)
            given = kanji_match.group(2)
            inferred.setdefault("family_name_kanji", family)
            if given:
                inferred.setdefault("given_name_kanji", given)

        roman_match = re.search(r"\b([A-Za-z][A-Za-z'\\-]{0,30})\s+([A-Za-z][A-Za-z'\\-]{0,30})\b", text)
        if roman_match:
            inferred.setdefault("family_name", roman_match.group(1))
            inferred.setdefault("given_name", roman_match.group(2))

        return inferred

    @staticmethod
    def _extract_policy_name(user_input: str) -> str:
        text = user_input.strip()
        if not text:
            return ""

        quoted = re.search(r"[「\"']([^「」\"']{1,128})[」\"']\s*ポリシ", text)
        if quoted:
            return quoted.group(1).strip().strip("。.,")

        inline = re.search(r"([A-Za-z0-9_.:-]{2,128})\s*ポリシ", text)
        if inline:
            return inline.group(1).strip().strip("。.,")

        english = re.search(r"policy\s+([A-Za-z0-9_.:-]{2,128})", text, flags=re.IGNORECASE)
        if english:
            return english.group(1).strip().strip("。.,")
        return ""

    def _infer_policy_inputs(self, user_input: str) -> dict[str, Any]:
        policy_name = self._extract_policy_name(user_input)
        if not policy_name:
            return {}
        return {"policy_name": policy_name}

    def _enforce_policy_lookup_intent(self, *, user_input: str, steps: list[ActionPlanStep]) -> list[ActionPlanStep]:
        inferred_policy_inputs = self._infer_policy_inputs(user_input)
        if not inferred_policy_inputs:
            return steps

        lowered = user_input.lower()
        has_policy_hint = ("ポリシ" in user_input) or ("policy" in lowered)
        has_impact_hint = self._has_any_hint(lowered, POLICY_IMPACT_HINTS)
        if not (has_policy_hint and has_impact_hint):
            return steps

        for step in steps:
            if step.tool_name != "get_policy":
                continue
            merged = step.provided_inputs.copy()
            for key, value in inferred_policy_inputs.items():
                merged.setdefault(key, value)
            return [
                ActionPlanStep(
                    step_id=step.step_id,
                    tool_name="get_policy",
                    required_inputs=TOOL_REQUIRED_INPUTS.get("get_policy", []),
                    provided_inputs=merged,
                    execution_order=step.execution_order,
                    reason=step.reason or "ポリシー影響調査のため policy_name から get_policy を実行",
                )
            ]

        return [
            ActionPlanStep(
                step_id="step-1",
                tool_name="get_policy",
                required_inputs=TOOL_REQUIRED_INPUTS.get("get_policy", []),
                provided_inputs=inferred_policy_inputs.copy(),
                execution_order=1,
                reason="ポリシー影響調査のため policy_name から get_policy を実行",
            )
        ]

    def create_plan(self, turn_id: str, user_input: str) -> ActionPlan:
        plan_id = f"plan-{uuid.uuid4()}"
        request_type = self._detect_request_type(user_input)
        if request_type == "permission_investigation":
            plan = self._build_permission_investigation_plan(plan_id=plan_id, turn_id=turn_id)
            self._notify_observation(user_input=user_input, plan=plan)
            return plan
        if request_type == "access_denial_troubleshooting":
            plan = self._build_access_denial_plan(plan_id=plan_id, turn_id=turn_id)
            self._notify_observation(user_input=user_input, plan=plan)
            return plan
        if self._is_delegation_intent(user_input):
            plan = self._build_delegation_plan(plan_id=plan_id, turn_id=turn_id, user_input=user_input)
            self._notify_observation(user_input=user_input, plan=plan)
            return plan

        payload = self.genai_client.plan_action(user_input=user_input, available_tools=AVAILABLE_TOOLS)
        steps_payload = payload.get("steps", []) if isinstance(payload, dict) else []
        inferred_create_user_inputs = self._infer_create_user_inputs(user_input)
        inferred_policy_inputs = self._infer_policy_inputs(user_input)
        inferred_user_selector_inputs = self._infer_user_selector_inputs(user_input)

        steps: list[ActionPlanStep] = []
        for index, raw_step in enumerate(steps_payload, start=1):
            tool_name = str(raw_step.get("tool_name", "")).strip()
            if tool_name not in AVAILABLE_TOOLS:
                continue
            provided = raw_step.get("provided_inputs") or {}
            if not isinstance(provided, dict):
                provided = {}
            provided = self._normalize_provided_inputs(tool_name=tool_name, provided=provided)
            if tool_name == "create_user" and inferred_create_user_inputs:
                for key, value in inferred_create_user_inputs.items():
                    provided.setdefault(key, value)
            if tool_name == "get_policy" and inferred_policy_inputs:
                for key, value in inferred_policy_inputs.items():
                    provided.setdefault(key, value)
            if tool_name == "delegate_to_peer":
                provided.setdefault("objective", user_input.strip())
                provided.setdefault("requested_operation", self._infer_delegation_operation(user_input))
                provided.setdefault("input_payload", {"raw_prompt": user_input.strip()})
            if tool_name in {"get_user", "get_last_successful_login"} and inferred_user_selector_inputs:
                existing_selector = provided.get("user_selector")
                if not isinstance(existing_selector, dict):
                    existing_selector = {}
                selector = inferred_user_selector_inputs.copy()
                selector.update(existing_selector)
                provided.setdefault("user_selector", selector)
            required_inputs = TOOL_REQUIRED_INPUTS.get(tool_name, [])

            steps.append(
                ActionPlanStep(
                    step_id=str(raw_step.get("step_id") or f"step-{index}"),
                    tool_name=tool_name,
                    required_inputs=[str(item) for item in required_inputs],
                    provided_inputs=provided,
                    execution_order=int(raw_step.get("execution_order") or index),
                    reason=str(raw_step.get("reason") or ""),
                )
            )

        if not steps:
            tool_name = self._fallback_tool(user_input)
            provided_inputs: dict[str, Any] = {}
            if tool_name == "create_user":
                provided_inputs = inferred_create_user_inputs.copy()
            if tool_name == "get_policy":
                provided_inputs = inferred_policy_inputs.copy()
            if tool_name in {"get_user", "get_last_successful_login"}:
                provided_inputs = {"user_selector": inferred_user_selector_inputs.copy()}
            if tool_name in {"add_user_to_group", "remove_user_from_group"}:
                provided_inputs = self._infer_group_membership_inputs(user_input)
            if tool_name == "delegate_to_peer":
                provided_inputs = {
                    "objective": user_input.strip(),
                    "requested_operation": self._infer_delegation_operation(user_input),
                    "input_payload": {"raw_prompt": user_input.strip()},
                }
            steps = [
                ActionPlanStep(
                    step_id="step-1",
                    tool_name=tool_name,
                    required_inputs=TOOL_REQUIRED_INPUTS.get(tool_name, []),
                    provided_inputs=provided_inputs,
                    execution_order=1,
                    reason="フォールバックプラン",
                )
            ]

        steps = self._enforce_group_membership_intent(user_input=user_input, steps=steps)
        steps = self._enforce_create_user_intent(
            user_input=user_input,
            steps=steps,
            inferred_create_user_inputs=inferred_create_user_inputs,
        )
        steps = self._enforce_policy_lookup_intent(user_input=user_input, steps=steps)
        steps = self._enforce_user_lookup_inputs(user_input=user_input, steps=steps)

        plan = ActionPlan(
            plan_id=plan_id,
            turn_id=turn_id,
            skill_name="single_tool_passthrough",
            request_type="single_tool_passthrough",
            steps=steps,
            planned_by_model="genai",
            plan_reasoning_summary=["ユーザー入力に対応するスキルを選択しました。"],
        )
        self._notify_observation(user_input=user_input, plan=plan)
        return plan

    def _notify_observation(self, *, user_input: str, plan: ActionPlan) -> None:
        if self.observation_hook is None:
            return
        try:
            summary = [f"{step.execution_order}:{step.tool_name}" for step in plan.ordered_steps()]
            self.observation_hook(
                {
                    "operation": "action_planner",
                    "model_name": "genai",
                    "input_summary": user_input[:200],
                    "output_summary": ", ".join(summary),
                }
            )
        except Exception:
            return
