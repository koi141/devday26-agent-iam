from __future__ import annotations

import copy
import time
import uuid
from typing import Any, Callable

from iam_agent.application.errors import AppError, classify_exception
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.domain.models import ActionPlan, SkillExecutionResult


ToolHandler = Callable[[dict[str, Any]], NormalizedResponse]
SkillHandler = Callable[..., NormalizedResponse]


TOOL_AUTH_ROUTE = {
    "list_users": "identity_domain_oauth",
    "get_user": "identity_domain_oauth",
    "create_user": "identity_domain_oauth",
    "list_groups": "identity_domain_oauth",
    "get_group": "identity_domain_oauth",
    "add_user_to_group": "identity_domain_oauth",
    "remove_user_from_group": "identity_domain_oauth",
    "list_user_credentials": "identity_domain_oauth",
    "get_last_successful_login": "identity_domain_oauth",
    "query_hr_database": "hr_db_credentials",
    "list_compartments": "oci_workload_identity",
    "list_resources": "oci_workload_identity",
    "list_policies": "oci_workload_identity",
    "get_policy": "oci_workload_identity",
    "delegate_to_peer": "a2a_peer_auth",
}


class SkillExecutor:
    def __init__(
        self,
        handlers: dict[str, ToolHandler],
        skill_handlers: dict[str, SkillHandler] | None = None,
    ) -> None:
        self.handlers = handlers
        self.skill_handlers = skill_handlers or {}

    def register_skill(self, skill_name: str, handler: SkillHandler) -> None:
        self.skill_handlers[skill_name] = handler

    def execute_skill(
        self,
        skill_name: str,
        *,
        turn_id: str,
        user_input: str,
        payload: dict[str, Any] | None = None,
    ) -> NormalizedResponse:
        handler = self.skill_handlers.get(skill_name)
        if handler is None:
            return NormalizedResponse.error(
                message=f"未対応スキル: {skill_name}",
                code="unknown_skill",
                retryable=False,
                proposal=["利用可能なスキルを確認してください。"],
                audit=AuditPayload(
                    target={"skill_name": skill_name, "turn_id": turn_id},
                    input_summary={"payload_keys": sorted((payload or {}).keys())},
                    decision_reason=["skill handler 未登録"],
                    result="error",
                ),
            )

        try:
            return handler(turn_id=turn_id, user_input=user_input, payload=copy.deepcopy(payload or {}))
        except TypeError:
            try:
                return handler(turn_id=turn_id, user_input=user_input)
            except Exception as exc:
                app_error = classify_exception(exc)
                return NormalizedResponse.error(
                    message=app_error.message,
                    code=app_error.code,
                    retryable=app_error.retryable,
                    proposal=["入力値・認証情報・スキル設定を確認してください。"],
                    audit=AuditPayload(
                        target={"skill_name": skill_name, "turn_id": turn_id},
                        input_summary={"payload_keys": sorted((payload or {}).keys())},
                        decision_reason=["skill execute 失敗"],
                        result="error",
                    ),
                )
        except Exception as exc:
            app_error = classify_exception(exc)
            return NormalizedResponse.error(
                message=app_error.message,
                code=app_error.code,
                retryable=app_error.retryable,
                proposal=["入力値・認証情報・スキル設定を確認してください。"],
                audit=AuditPayload(
                    target={"skill_name": skill_name, "turn_id": turn_id},
                    input_summary={"payload_keys": sorted((payload or {}).keys())},
                    decision_reason=["skill execute 失敗"],
                    result="error",
                ),
            )

    def auth_route_for(self, tool_name: str) -> str:
        return TOOL_AUTH_ROUTE.get(tool_name, "")

    def execute(self, tool_name: str, payload: dict[str, Any]) -> SkillExecutionResult:
        request_id = f"req-{uuid.uuid4()}"
        started = time.perf_counter()
        auth_route = TOOL_AUTH_ROUTE.get(tool_name, "")
        handler = self.handlers.get(tool_name)
        if handler is None:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return SkillExecutionResult(
                request_id=request_id,
                tool_name=tool_name,
                status="error",
                error_code="unknown_tool",
                error_message=f"未対応ツール: {tool_name}",
                retryable=False,
                auth_route=auth_route,
                duration_ms=duration_ms,
            )

        try:
            normalized = handler(copy.deepcopy(payload))
            duration_ms = int((time.perf_counter() - started) * 1000)
            error_code = ""
            error_message = ""
            retryable = False
            if normalized.status == "error" and normalized.errors:
                first_error = normalized.errors[0]
                error_code = first_error.code
                error_message = first_error.message
                retryable = bool(first_error.retryable)
            raw = normalized.to_dict()
            oci_request_id = self._extract_oci_request_id(raw)
            return SkillExecutionResult(
                request_id=request_id,
                tool_name=tool_name,
                status=normalized.status,
                raw_response=raw,
                normalized_data=normalized.data or {},
                error_code=error_code,
                error_message=error_message,
                retryable=retryable,
                auth_route=auth_route,
                duration_ms=duration_ms,
                oci_request_id=oci_request_id,
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            app_error: AppError = classify_exception(exc)
            return SkillExecutionResult(
                request_id=request_id,
                tool_name=tool_name,
                status="error",
                error_code=app_error.code,
                error_message=app_error.message,
                retryable=app_error.retryable,
                auth_route=auth_route,
                duration_ms=duration_ms,
            )

    def execute_plan(self, plan: ActionPlan) -> list[SkillExecutionResult]:
        results: list[SkillExecutionResult] = []
        for step in plan.ordered_steps():
            results.append(self.execute(step.tool_name, step.provided_inputs))
            if results[-1].status == "error":
                break
        return results

    @staticmethod
    def _extract_oci_request_id(payload: dict[str, Any]) -> str:
        candidates = ("oci_request_id", "opc_request_id", "opc-request-id", "request_id")

        def _walk(value: Any) -> str:
            if isinstance(value, dict):
                for key in candidates:
                    raw = value.get(key)
                    if isinstance(raw, str) and raw.strip():
                        return raw
                for item in value.values():
                    found = _walk(item)
                    if found:
                        return found
            if isinstance(value, list):
                for item in value:
                    found = _walk(item)
                    if found:
                        return found
            return ""

        return _walk(payload)
