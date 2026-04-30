from __future__ import annotations

from typing import Any

from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.skills.user_provisioning import _normalized_from_result


class ResourceInventorySkill:
    skill_name = "resource_inventory"

    def __init__(self, skill_executor: SkillExecutor) -> None:
        self.skill_executor = skill_executor

    def execute(self, *, turn_id: str, payload: dict[str, Any] | None = None) -> NormalizedResponse:
        params = payload.copy() if isinstance(payload, dict) else {}

        compartments_result = self.skill_executor.execute("list_compartments", params)
        compartments_normalized = _normalized_from_result(
            result=compartments_result,
            fallback_target={"skill": self.skill_name, "turn_id": turn_id},
            fallback_reason=["resource_inventory.list_compartments"],
        )
        if compartments_normalized.status != "success":
            return compartments_normalized

        resources_result = self.skill_executor.execute("list_resources", params)
        resources_normalized = _normalized_from_result(
            result=resources_result,
            fallback_target={"skill": self.skill_name, "turn_id": turn_id},
            fallback_reason=["resource_inventory.list_resources"],
        )
        if resources_normalized.status != "success":
            return resources_normalized

        compartments = ((compartments_normalized.data or {}).get("compartments") or [])
        resources = ((resources_normalized.data or {}).get("resources") or [])

        return NormalizedResponse.success(
            facts=[f"コンパートメント {len(compartments)} 件、リソース {len(resources)} 件を収集しました。"],
            interpretation=["コンパートメント階層とリソース一覧を統合して返却しています。"],
            proposal=["必要なら include_subtree や resource_type を指定して再実行してください。"],
            data={
                "compartments": compartments,
                "resources": resources,
                "compartment_summary": compartments_normalized.data or {},
                "resource_summary": resources_normalized.data or {},
            },
            audit=AuditPayload(
                target={"skill": self.skill_name, "turn_id": turn_id},
                input_summary=params,
                decision_reason=["list_compartments", "list_resources"],
                result="success",
            ),
        )
