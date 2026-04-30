from __future__ import annotations

from iam_agent.tools.target_resolution import extract_user_hint


def test_extract_user_hint_accepts_username_token_with_underscore() -> None:
    hint = extract_user_hint("IAM_Agentはどのような操作を許可されていますか")
    assert hint.get("user_name") == "IAM_Agent"


def test_extract_user_hint_prefers_explicit_username_label() -> None:
    hint = extract_user_hint("ユーザー名: iam-agent.user を調べて")
    assert hint.get("user_name") == "iam-agent.user"

