from __future__ import annotations

from typing import Any

from iam_agent.application.errors import classify_exception
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.infra.clients.hr_db_client import HrDbClient


class HrUserTools:
    def __init__(self, client: HrDbClient) -> None:
        self.client = client

    def query_hr_user(self, payload: dict[str, Any]) -> NormalizedResponse:
        try:
            candidates = self.client.query_employees(payload)
            candidate_count = len(candidates)
            interpretation = ["候補件数を確認してください。"]
            proposal = ["必要に応じて検索条件を追加してください。"]
            facts = [f"HR検索候補 {candidate_count} 件を取得しました。"]

            if candidate_count == 0:
                interpretation = ["指定条件に一致する候補が見つかりませんでした。"]
                proposal = [
                    "email または emp_id を指定して再検索してください。",
                    "姓名のみの場合は漢字/ローマ字の揺れを確認してください。",
                ]
            elif candidate_count > 1:
                interpretation = ["候補が複数あるため自動選択できません。"]
                proposal = ["emp_id もしくは email を追加して1件に絞ってください。"]
                facts.append(
                    "候補識別子: "
                    + ", ".join(str(item.get("emp_id") or item.get("email") or "-") for item in candidates[:5])
                )

            return NormalizedResponse.success(
                facts=facts,
                interpretation=interpretation,
                proposal=proposal,
                data={"candidates": candidates, "candidate_count": candidate_count},
                audit=AuditPayload(
                    target={"table": "HR.EMPLOYEES"},
                    input_summary={"keys": sorted(payload.keys())},
                    decision_reason=["query_hr_database 実行"],
                    result="success",
                ),
            )
        except Exception as exc:
            app_error = classify_exception(exc)
            return NormalizedResponse.error(
                message=app_error.message,
                code=app_error.code,
                retryable=app_error.retryable,
                proposal=["DB接続情報と検索条件を確認してください。"],
                audit=AuditPayload(
                    target={"table": "HR.EMPLOYEES"},
                    input_summary={"keys": sorted(payload.keys())},
                    decision_reason=["query_hr_database 失敗"],
                    result="error",
                ),
            )
