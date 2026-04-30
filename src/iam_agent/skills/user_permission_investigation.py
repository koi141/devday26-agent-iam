from __future__ import annotations

from iam_agent.application.permission_investigator import PermissionInvestigator
from iam_agent.domain.contracts import NormalizedResponse


class UserPermissionInvestigationSkill:
    skill_name = "user_permission_investigation"

    def __init__(self, investigator: PermissionInvestigator) -> None:
        self.investigator = investigator

    def execute(self, *, turn_id: str, user_input: str) -> NormalizedResponse:
        return self.investigator.investigate(turn_id=turn_id, user_input=user_input)
