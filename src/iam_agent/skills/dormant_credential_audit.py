from __future__ import annotations

from typing import Any

from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.skills.user_provisioning import _normalized_from_result


class DormantCredentialAuditSkill:
    skill_name = "dormant_credential_audit"

    def __init__(self, skill_executor: SkillExecutor) -> None:
        self.skill_executor = skill_executor

    def execute(self, *, turn_id: str, payload: dict[str, Any] | None = None) -> NormalizedResponse:
        params = payload.copy() if isinstance(payload, dict) else {}

        credential_result = self.skill_executor.execute("list_user_credentials", params)
        credentials_normalized = _normalized_from_result(
            result=credential_result,
            fallback_target={"skill": self.skill_name, "turn_id": turn_id},
            fallback_reason=["dormant_credential_audit.list_user_credentials"],
        )
        if credentials_normalized.status != "success":
            return credentials_normalized

        login_result = self.skill_executor.execute("get_last_successful_login", params)
        login_normalized = _normalized_from_result(
            result=login_result,
            fallback_target={"skill": self.skill_name, "turn_id": turn_id},
            fallback_reason=["dormant_credential_audit.get_last_successful_login"],
        )
        if login_normalized.status != "success":
            return login_normalized

        credential_count = int(((credentials_normalized.data or {}).get("credential_count") or 0))
        last_login = (login_normalized.data or {}).get("last_successful_login_at")
        dormant_suspected = credential_count > 0 and not bool(last_login)

        interpretation = ["認証情報件数と最終ログインを突合しました。"]
        proposal = ["対象ユーザーに不要な資格情報がないか確認してください。"]
        if dormant_suspected:
            interpretation.append("資格情報が存在しますが最終ログインが確認できず、休眠候補の可能性があります。")
            proposal = ["休眠候補として棚卸しし、不要な資格情報の無効化を検討してください。"]

        return NormalizedResponse.success(
            facts=[
                f"資格情報件数: {credential_count}",
                f"最終ログイン: {last_login or '未確認'}",
                f"休眠候補判定: {'yes' if dormant_suspected else 'no'}",
            ],
            interpretation=interpretation,
            proposal=proposal,
            data={
                "credential_summary": credentials_normalized.data or {},
                "login_summary": login_normalized.data or {},
                "dormant_suspected": dormant_suspected,
            },
            audit=AuditPayload(
                target={"skill": self.skill_name, "turn_id": turn_id},
                input_summary=params,
                decision_reason=["list_user_credentials", "get_last_successful_login", "dormant_check"],
                result="success",
            ),
        )
