from __future__ import annotations

from typing import Any

from iam_agent.domain.contracts import NormalizedResponse
from iam_agent.infra.clients.hr_db_client import HrDbClient
from iam_agent.tools.hr_database.users import HrUserTools


class HrTools:
    def __init__(self, client: HrDbClient) -> None:
        self.client = client
        self.user_tools = HrUserTools(client)

    def query_hr_database(self, payload: dict[str, Any]) -> NormalizedResponse:
        return self.user_tools.query_hr_user(payload)
