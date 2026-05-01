from __future__ import annotations

from typing import Iterable

from iam_agent.domain.models import ValidationIssue


def format_missing_credential_message(missing_items: list[str]) -> str:
    return (
        "資格情報が不足しています。"
        f"不足項目: {', '.join(missing_items)}。"
        "必要な情報を追加後に再実行してください。"
    )


def format_missing_input_message(*, missing_fields: list[str], impact: str, next_action: str) -> str:
    fields = ", ".join(missing_fields) if missing_fields else "未特定"
    return f"不足項目: {fields} / 影響: {impact} / 次アクション: {next_action}"


def format_execution_error_message(error_code: str, detail: str, retryable: bool) -> str:
    action = "再試行可能です。" if retryable else "入力または権限を確認してください。"
    return f"処理エラー(code={error_code}): {detail} {action}"


def format_permission_denied_message(*, missing_privileges: list[str], impact_scope: str) -> str:
    missing_text = ", ".join(missing_privileges) if missing_privileges else "必要権限未特定"
    return (
        "権限不足により処理できませんでした。"
        f"不足権限: {missing_text}。"
        f"影響範囲: {impact_scope}。"
        "権限付与後に再実行してください。"
    )


def format_transient_failure_message(*, source: str, detail: str, retryable: bool = True) -> str:
    suffix = "一定時間後に再試行してください。" if retryable else "運用管理者へ連絡してください。"
    return f"{source} で一時障害が発生しました: {detail} {suffix}"


def format_source_unavailable_message(*, source: str, detail: str) -> str:
    return f"{source} へ接続できませんでした: {detail} 利用可能状態を確認後に再実行してください。"


def format_binding_invalid_message(*, detail: str) -> str:
    return (
        "Langfuse の記録先設定が不正のためテレメトリ送信を停止しました。"
        f"詳細: {detail}。"
        "設定値（host/org/project）を確認してください。"
    )


def format_telemetry_delivery_failed_message(*, stage: str, detail: str, retryable: bool = True) -> str:
    suffix = "主処理は継続しました。後で再送してください。" if retryable else "主処理は継続しました。設定を見直してください。"
    return f"テレメトリ送信に失敗しました (stage={stage}): {detail} {suffix}"


def _issue_line(issue: ValidationIssue) -> str:
    return f"[{issue.category}] {issue.target}"


def format_runtime_preflight_messages(issues: Iterable[ValidationIssue]) -> tuple[list[str], list[str], list[str]]:
    issue_list = list(issues)
    if not issue_list:
        return (["設定検証は成功しました。"], ["必須設定は充足しています。"], ["そのまま処理を継続できます。"])

    facts = ["起動前設定検証で不足または不整合を検出しました。"]
    facts.extend(_issue_line(issue) for issue in issue_list)

    interpretation = []
    proposal = []
    for issue in issue_list:
        interpretation.append(f"{issue.target}: {issue.impact}")
        proposal.append(f"{issue.target}: {issue.required_action}")
    return (facts, interpretation, proposal)
