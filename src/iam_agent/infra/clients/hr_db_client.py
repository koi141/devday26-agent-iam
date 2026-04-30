from __future__ import annotations

from typing import Any

from iam_agent.application.errors import MissingCredentialError, TemporaryUpstreamFailure
from iam_agent.config.settings import Settings

try:
    import oracledb
except Exception:  # pragma: no cover - local unit tests may mock this client
    oracledb = None


class HrDbClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _connect(self):
        missing = self.settings.missing_for_route("hr_db_credentials")
        if missing:
            raise MissingCredentialError(missing)
        if oracledb is None:
            raise RuntimeError("oracledb がインストールされていません。")

        return oracledb.connect(
            user=self.settings.hr_database_user,
            password=self.settings.hr_database_pass,
            dsn=self.settings.hr_database_connectstr,
        )

    def query_employees(self, criteria: dict[str, Any]) -> list[dict[str, Any]]:
        where_parts: list[str] = []
        binds: dict[str, Any] = {}

        if criteria.get("emp_id") is not None:
            where_parts.append("EMP_ID = :emp_id")
            binds["emp_id"] = criteria["emp_id"]
        if criteria.get("email"):
            where_parts.append("LOWER(EMAIL) = LOWER(:email)")
            binds["email"] = criteria["email"]
        if criteria.get("first_name"):
            where_parts.append("LOWER(FIRST_NAME) = LOWER(:first_name)")
            binds["first_name"] = criteria["first_name"]
        if criteria.get("last_name"):
            where_parts.append("LOWER(LAST_NAME) = LOWER(:last_name)")
            binds["last_name"] = criteria["last_name"]
        if criteria.get("first_name_kanji"):
            where_parts.append("FIRST_NAME_KANJI = :first_name_kanji")
            binds["first_name_kanji"] = criteria["first_name_kanji"]
        if criteria.get("last_name_kanji"):
            where_parts.append("LAST_NAME_KANJI = :last_name_kanji")
            binds["last_name_kanji"] = criteria["last_name_kanji"]

        sql = (
            "SELECT EMP_ID, FIRST_NAME, LAST_NAME, EMAIL, PHONE_NUMBER, DEPARTMENT, "
            "HIRE_DATE, STATUS, FIRST_NAME_KANJI, LAST_NAME_KANJI FROM HR.EMPLOYEES"
        )
        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)

        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, binds)
                    columns = [d[0].lower() for d in cur.description]
                    return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]
        except Exception as exc:  # pragma: no cover - database/network dependent
            raise TemporaryUpstreamFailure(f"HR DB照会に失敗しました: {exc}") from exc
