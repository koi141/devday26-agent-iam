from __future__ import annotations

import re
from typing import Any

from iam_agent.application.high_risk_guard import ensure_unique
from iam_agent.domain.models import UserResolutionCandidate, UserResolutionResult


def extract_resources(body: dict[str, Any]) -> list[dict[str, Any]]:
    resources = body.get("Resources")
    if isinstance(resources, list):
        return [item for item in resources if isinstance(item, dict)]
    return []


def resolve_by_selector(
    resources: list[dict[str, Any]],
    selector: dict[str, Any],
    *,
    id_key: str = "id",
    name_keys: tuple[str, ...] = ("displayName", "userName"),
) -> dict[str, Any]:
    if not selector:
        return ensure_unique(resources, "対象")

    if selector.get("id"):
        for item in resources:
            if item.get(id_key) == selector["id"]:
                return item

    selector_name = selector.get("name") or selector.get("display_name")
    if selector_name:
        matched: list[dict[str, Any]] = []
        for item in resources:
            for key in name_keys:
                if str(item.get(key, "")).lower() == str(selector_name).lower():
                    matched.append(item)
                    break
        return ensure_unique(matched, "対象")

    return ensure_unique(resources, "対象")


def extract_user_hint(user_input: str) -> dict[str, Any]:
    hint: dict[str, Any] = {}
    text = user_input.strip()
    if not text:
        return hint

    email_match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    if email_match:
        hint["email"] = email_match.group(0)
        hint["user_name"] = email_match.group(0)

    emp_match = re.search(r"(?:emp[_ -]?id|社員番号)\s*[:：]?\s*([0-9]{2,12})", text, flags=re.IGNORECASE)
    if emp_match:
        hint["emp_id"] = emp_match.group(1)

    kanji_match = re.search(r"([一-龥々]{1,12})(?:[ 　]?([一-龥々]{1,12}))?さん", text)
    if kanji_match:
        hint["family_name_kanji"] = kanji_match.group(1)
        if kanji_match.group(2):
            hint["given_name_kanji"] = kanji_match.group(2)
            hint["name"] = f"{kanji_match.group(1)} {kanji_match.group(2)}"
        else:
            hint["name"] = kanji_match.group(1)

    roman_match = re.search(r"\b([A-Za-z][A-Za-z'\\-]{0,30})\s+([A-Za-z][A-Za-z'\\-]{0,30})\b", text)
    if roman_match:
        hint.setdefault("family_name", roman_match.group(1))
        hint.setdefault("given_name", roman_match.group(2))

    username_from_text = _extract_username_token(text)
    if username_from_text:
        hint.setdefault("user_name", username_from_text)
        if "@" in username_from_text:
            hint.setdefault("email", username_from_text)
    return hint


def _extract_username_token(text: str) -> str:
    def _valid(candidate: str) -> bool:
        lowered = candidate.lower()
        if lowered in {"oci", "iam", "idcs", "identity", "domain", "domains", "user", "users"}:
            return False
        return True

    explicit = re.search(
        r"(?:ユーザー名|username|user[_ -]?name)\s*[:：]\s*([A-Za-z][A-Za-z0-9_.@-]{1,127})",
        text,
        flags=re.IGNORECASE,
    )
    if explicit:
        token = explicit.group(1).strip()
        if _valid(token):
            return token

    quoted = re.search(r"[「\"']([A-Za-z][A-Za-z0-9_.@-]{1,127})[」\"']", text)
    if quoted:
        token = quoted.group(1).strip()
        if _valid(token):
            return token

    topic = re.search(
        r"(?:^|[\s　])([A-Za-z][A-Za-z0-9_.@-]{1,127})(?:\s*ユーザー)?\s*(?:は|が|の|を)",
        text,
    )
    if topic:
        token = topic.group(1).strip()
        if _valid(token):
            return token

    return ""


def build_hr_query_from_hint(hint: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "emp_id": "emp_id",
        "email": "email",
        "given_name": "first_name",
        "family_name": "last_name",
        "given_name_kanji": "first_name_kanji",
        "family_name_kanji": "last_name_kanji",
    }
    payload: dict[str, Any] = {}
    for key, target in mapping.items():
        value = hint.get(key)
        if value:
            payload[target] = value
    return payload


def _to_candidate_from_oci(user: dict[str, Any], reasons: list[str], score: float) -> UserResolutionCandidate:
    return UserResolutionCandidate(
        candidate_id=str(user.get("id") or user.get("ocid") or ""),
        source="oci",
        oci_user_id=str(user.get("id") or user.get("ocid") or ""),
        username=str(user.get("userName") or ""),
        email=_extract_primary_email(user),
        display_name=str(user.get("displayName") or user.get("userName") or ""),
        match_reason=reasons,
        score=score,
        raw=user,
    )


def _to_candidate_from_hr(employee: dict[str, Any], reasons: list[str], score: float) -> UserResolutionCandidate:
    display = " ".join(
        [str(employee.get("last_name_kanji") or ""), str(employee.get("first_name_kanji") or "")]
    ).strip()
    return UserResolutionCandidate(
        candidate_id=str(employee.get("emp_id") or employee.get("email") or ""),
        source="hr",
        username=str(employee.get("email") or ""),
        email=str(employee.get("email") or ""),
        display_name=display or " ".join(
            [str(employee.get("last_name") or ""), str(employee.get("first_name") or "")]
        ).strip(),
        match_reason=reasons,
        score=score,
        raw=employee,
    )


def _extract_primary_email(user: dict[str, Any]) -> str:
    emails = user.get("emails")
    if isinstance(emails, list):
        for item in emails:
            if isinstance(item, dict) and item.get("primary"):
                return str(item.get("value") or "")
        for item in emails:
            if isinstance(item, dict) and item.get("value"):
                return str(item.get("value") or "")
    return ""


def _score_oci_user(user: dict[str, Any], hint: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    user_id = str(user.get("id") or user.get("ocid") or "")
    user_name = str(user.get("userName") or "").lower()
    display_name = str(user.get("displayName") or "").lower()
    email = _extract_primary_email(user).lower()

    if hint.get("id") and user_id == str(hint["id"]):
        score += 100
        reasons.append("id一致")
    if hint.get("user_name") and user_name == str(hint["user_name"]).lower():
        score += 80
        reasons.append("userName一致")
    if hint.get("email") and (email == str(hint["email"]).lower() or user_name == str(hint["email"]).lower()):
        score += 80
        reasons.append("email一致")
    if hint.get("name") and str(hint["name"]).lower() in display_name:
        score += 40
        reasons.append("表示名一致")

    family_kanji = str(hint.get("family_name_kanji") or "").lower()
    given_kanji = str(hint.get("given_name_kanji") or "").lower()
    if family_kanji and family_kanji in display_name:
        score += 30
        reasons.append("姓(漢字)一致")
    if given_kanji and given_kanji in display_name:
        score += 20
        reasons.append("名(漢字)一致")
    return score, reasons


def resolve_user_with_hr(
    *,
    request_id: str,
    users: list[dict[str, Any]],
    hint: dict[str, Any],
    hr_candidates: list[dict[str, Any]] | None = None,
) -> UserResolutionResult:
    scored: list[UserResolutionCandidate] = []
    for user in users:
        score, reasons = _score_oci_user(user, hint)
        if score > 0:
            scored.append(_to_candidate_from_oci(user, reasons, score))

    scored.sort(key=lambda item: item.score, reverse=True)
    if len(scored) == 1:
        return UserResolutionResult(
            request_id=request_id,
            status="resolved",
            selected_user=scored[0],
            candidates=scored,
        )

    if len(scored) > 1:
        top_score = scored[0].score
        top_candidates = [item for item in scored if item.score == top_score]
        if len(top_candidates) == 1:
            return UserResolutionResult(
                request_id=request_id,
                status="resolved",
                selected_user=top_candidates[0],
                candidates=scored,
            )
        return UserResolutionResult(
            request_id=request_id,
            status="ambiguous",
            candidates=top_candidates,
            required_confirmation_fields=["email", "emp_id", "user_name"],
        )

    if hr_candidates:
        hr_scored = [
            _to_candidate_from_hr(
                item,
                reasons=["HR補完候補"],
                score=50.0,
            )
            for item in hr_candidates
        ]
        if len(hr_scored) == 1:
            return UserResolutionResult(
                request_id=request_id,
                status="resolved",
                selected_user=hr_scored[0],
                candidates=hr_scored,
            )
        return UserResolutionResult(
            request_id=request_id,
            status="ambiguous",
            candidates=hr_scored,
            required_confirmation_fields=["email", "emp_id"],
        )

    if not hint:
        return UserResolutionResult(
            request_id=request_id,
            status="insufficient",
            required_confirmation_fields=["user_hint"],
        )

    return UserResolutionResult(
        request_id=request_id,
        status="not_found",
        required_confirmation_fields=["email", "emp_id", "name"],
    )
