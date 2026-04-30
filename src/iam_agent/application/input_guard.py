from __future__ import annotations

from iam_agent.domain.models import ActionPlanStep, MissingInputRequest


TOOL_REQUIRED_INPUTS: dict[str, list[str]] = {
    "list_users": [],
    "get_user": ["user_id"],
    "create_user": ["family_name", "given_name", "email"],
    "list_groups": [],
    "get_group": ["group_id"],
    "add_user_to_group": ["user_selector", "group_selector"],
    "remove_user_from_group": ["user_selector", "group_selector"],
    "list_user_credentials": [],
    "get_last_successful_login": ["user_selector"],
    "query_hr_database": [],
    "list_compartments": [],
    "list_resources": [],
    "list_policies": [],
    "get_policy": ["policy_id"],
    "delegate_to_peer": ["objective"],
}

WORKFLOW_REQUIRED_INPUTS: dict[str, list[str]] = {
    "permission_investigation": ["user_hint"],
    "access_denial_troubleshooting": ["user_hint", "target_resource", "requested_action"],
    "single_tool_passthrough": [],
}

# create_user はツール内部で HR 補完を試みるため、
# オーケストレーション段階で必須入力不足として停止しない。
DEFER_MISSING_CHECK_TO_TOOL = {"create_user"}
GROUP_MEMBERSHIP_TOOLS = {"add_user_to_group", "remove_user_from_group"}
USER_SELECTOR_ALIASES = ("user_id", "username", "user_name", "email")
GROUP_SELECTOR_ALIASES = ("group_id", "group_name", "display_name", "name")
POLICY_SELECTOR_ALIASES = ("policy_name", "name", "display_name")
A2A_REQUEST_REQUIRED_FIELDS = (
    "request_id",
    "correlation_id",
    "source_agent_id",
    "target_agent_id",
    "requested_operation",
    "objective",
    "input_payload",
    "hop_count",
    "visited_agents",
)
USER_RESOLUTION_ALIASES = (
    "user_id",
    "id",
    "username",
    "user_name",
    "email",
    "name",
    "display_name",
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
)


class InputGuard:
    @staticmethod
    def is_single_tool_passthrough(request_type: str) -> bool:
        return request_type == "single_tool_passthrough"

    @staticmethod
    def _is_present(value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, dict):
            for item in value.values():
                if InputGuard._is_present(item):
                    return True
            return False
        return True

    @classmethod
    def _has_selector(cls, provided_inputs: dict[str, object], selector_key: str, aliases: tuple[str, ...]) -> bool:
        selector_value = provided_inputs.get(selector_key)
        if cls._is_present(selector_value):
            return True
        for alias in aliases:
            if cls._is_present(provided_inputs.get(alias)):
                return True
        return False

    def find_missing_inputs(self, step: ActionPlanStep) -> list[str]:
        if step.tool_name in DEFER_MISSING_CHECK_TO_TOOL:
            return []

        if step.tool_name in GROUP_MEMBERSHIP_TOOLS:
            missing: list[str] = []
            if not self._has_selector(step.provided_inputs, "user_selector", USER_SELECTOR_ALIASES):
                missing.append("user_selector")
            if not self._has_selector(step.provided_inputs, "group_selector", GROUP_SELECTOR_ALIASES):
                missing.append("group_selector")
            return missing

        if step.tool_name == "get_policy":
            has_policy_id = self._has_selector(step.provided_inputs, "policy_id", POLICY_SELECTOR_ALIASES)
            return [] if has_policy_id else ["policy_id"]

        if step.tool_name == "get_user":
            has_user = self._has_selector(step.provided_inputs, "user_id", USER_RESOLUTION_ALIASES) or self._has_selector(
                step.provided_inputs,
                "user_selector",
                USER_RESOLUTION_ALIASES,
            )
            return [] if has_user else ["user_id"]

        if step.tool_name == "get_last_successful_login":
            has_user_selector = self._has_selector(step.provided_inputs, "user_selector", USER_RESOLUTION_ALIASES)
            return [] if has_user_selector else ["user_selector"]

        if step.tool_name == "delegate_to_peer":
            missing: list[str] = []
            if not self._is_present(step.provided_inputs.get("objective")):
                missing.append("objective")
            if not self._is_present(step.provided_inputs.get("requested_operation")):
                missing.append("requested_operation")
            return missing

        required = step.required_inputs or TOOL_REQUIRED_INPUTS.get(step.tool_name, [])
        missing: list[str] = []
        for key in required:
            value = step.provided_inputs.get(key)
            if value is None:
                missing.append(key)
                continue
            if isinstance(value, str) and not value.strip():
                missing.append(key)
        return missing

    def build_missing_input_request(self, turn_id: str, step: ActionPlanStep, missing: list[str]) -> MissingInputRequest:
        return MissingInputRequest(
            turn_id=turn_id,
            step_id=step.step_id,
            tool_name=step.tool_name,
            missing_fields=missing,
            why_needed=[f"`{step.tool_name}` 実行に `{name}` が必要" for name in missing],
            prompt_to_user="不足している入力を指定してください: " + ", ".join(missing),
        )

    def find_missing_workflow_inputs(self, request_type: str, payload: dict[str, object]) -> list[str]:
        required = WORKFLOW_REQUIRED_INPUTS.get(request_type, [])
        missing: list[str] = []
        for key in required:
            value = payload.get(key)
            if not self._is_present(value):
                missing.append(key)
        return missing

    def find_missing_a2a_request_fields(self, payload: dict[str, object]) -> list[str]:
        missing: list[str] = []
        for key in A2A_REQUEST_REQUIRED_FIELDS:
            value = payload.get(key)
            if key == "input_payload":
                if not isinstance(value, dict):
                    missing.append(key)
                continue
            if key == "visited_agents":
                if not isinstance(value, list):
                    missing.append(key)
                continue
            if key == "hop_count":
                if value is None:
                    missing.append(key)
                continue
            if not self._is_present(value):
                missing.append(key)
        return missing

    def validate_a2a_request(
        self,
        payload: dict[str, object],
        *,
        max_hops: int,
        self_agent_id: str,
        high_risk_operations: set[str] | None = None,
    ) -> list[str]:
        violations: list[str] = []
        violations.extend(self.find_missing_a2a_request_fields(payload))
        if violations:
            return violations

        hop_count = int(payload.get("hop_count") or 0)
        if hop_count > max_hops:
            violations.append("hop_count_exceeded")

        visited = payload.get("visited_agents")
        if isinstance(visited, list) and self_agent_id in [str(item) for item in visited]:
            violations.append("loop_detected")

        operation = str(payload.get("requested_operation") or "")
        if high_risk_operations and operation in high_risk_operations:
            idem_key = str(payload.get("idempotency_key") or "").strip()
            if not idem_key:
                violations.append("idempotency_key")

        return violations
