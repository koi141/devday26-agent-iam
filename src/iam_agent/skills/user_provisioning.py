from __future__ import annotations

from typing import Any

from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, ErrorDetail, NormalizedResponse


class UserProvisioningSkill:
    skill_name = "user_provisioning"

    def __init__(self, skill_executor: SkillExecutor) -> None:
        self.skill_executor = skill_executor

    def execute(self, *, turn_id: str, user_input: str, provided_inputs: dict[str, Any] | None = None) -> NormalizedResponse:
        payload = provided_inputs.copy() if isinstance(provided_inputs, dict) else {}
        result = self.skill_executor.execute("create_user", payload)
        return _normalized_from_result(
            result=result,
            fallback_target={"skill": self.skill_name, "turn_id": turn_id},
            fallback_reason=["user_provisioning skill 実行"],
        )


def _normalized_from_result(*, result: Any, fallback_target: dict[str, Any], fallback_reason: list[str]) -> NormalizedResponse:
    raw = result.raw_response if hasattr(result, "raw_response") else None
    if isinstance(raw, dict):
        status = str(raw.get("status") or "error")
        errors = raw.get("errors")
        parsed_errors: list[ErrorDetail] | None = None
        if isinstance(errors, list):
            parsed_errors = []
            for item in errors:
                if isinstance(item, dict):
                    parsed_errors.append(
                        ErrorDetail(
                            code=str(item.get("code") or "execution_error"),
                            message=str(item.get("message") or ""),
                            retryable=bool(item.get("retryable")),
                        )
                    )
        audit_raw = raw.get("audit") if isinstance(raw.get("audit"), dict) else {}
        return NormalizedResponse(
            status=status,  # type: ignore[arg-type]
            facts=[str(item) for item in raw.get("facts") or []],
            interpretation=[str(item) for item in raw.get("interpretation") or []],
            proposal=[str(item) for item in raw.get("proposal") or []],
            data=raw.get("data") if isinstance(raw.get("data"), dict) else None,
            meta=raw.get("meta") if isinstance(raw.get("meta"), dict) else None,
            errors=parsed_errors,
            audit=AuditPayload(
                target=audit_raw.get("target") if isinstance(audit_raw.get("target"), dict) else fallback_target,
                input_summary=audit_raw.get("input_summary") if isinstance(audit_raw.get("input_summary"), dict) else {},
                decision_reason=[str(item) for item in audit_raw.get("decision_reason") or fallback_reason],
                result=str(audit_raw.get("result") or status),
                correlation_id=str(audit_raw.get("correlation_id") or ""),
                peer_agent=str(audit_raw.get("peer_agent") or ""),
                delegation_outcome=str(audit_raw.get("delegation_outcome") or ""),
            ),
        )

    return NormalizedResponse.error(
        message=str(getattr(result, "error_message", "skill execution failed")),
        code=str(getattr(result, "error_code", "execution_error")),
        retryable=bool(getattr(result, "retryable", False)),
        proposal=["入力値と認証情報を確認して再実行してください。"],
        audit=AuditPayload(
            target=fallback_target,
            input_summary={},
            decision_reason=fallback_reason,
            result="error",
        ),
    )
