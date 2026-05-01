from __future__ import annotations

import ast
import json
from typing import Any, Callable

from iam_agent.application.errors import classify_exception
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.domain.models import ResponseDraft, SkillExecutionResult
from iam_agent.infra.clients.genai_client import GenAIClient


class ResponseSummarizer:
    def __init__(
        self,
        genai_client: GenAIClient,
        observation_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.genai_client = genai_client
        self.observation_hook = observation_hook

    @staticmethod
    def _parse_structured_text(text: str) -> Any | None:
        stripped = text.strip()
        if not stripped or stripped[0] not in "{[":
            return None
        for parser in (json.loads, ast.literal_eval):
            try:
                return parser(stripped)
            except Exception:
                continue
        return None

    def _format_structured_value(self, value: Any) -> list[str]:
        if isinstance(value, dict):
            lines: list[str] = []
            for key, item in value.items():
                if isinstance(item, (dict, list)):
                    lines.append(f"{key}:")
                    nested = self._format_structured_value(item)
                    lines.extend([f"  {line}" for line in nested])
                else:
                    lines.append(f"{key}: {item}")
            return lines

        if isinstance(value, list):
            lines = []
            for idx, item in enumerate(value, start=1):
                if isinstance(item, (dict, list)):
                    nested = self._format_structured_value(item)
                    if not nested:
                        lines.append(f"{idx}.")
                        continue
                    lines.append(f"{idx}. {nested[0]}")
                    lines.extend([f"   {line}" for line in nested[1:]])
                else:
                    lines.append(f"{idx}. {item}")
            return lines

        return [str(value)]

    def _coerce_single(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (dict, list)):
            return self._format_structured_value(value)
        text = str(value).strip()
        if not text:
            return []
        parsed = self._parse_structured_text(text)
        if parsed is not None:
            return self._format_structured_value(parsed)
        return [text]

    def _coerce_to_lines(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            lines: list[str] = []
            for item in value:
                lines.extend(self._coerce_single(item))
            return lines
        return self._coerce_single(value)

    @staticmethod
    def _ensure_section_lines(lines: list[str], fallback: str) -> list[str]:
        cleaned = [line for line in lines if str(line).strip()]
        if cleaned:
            return cleaned
        return [fallback]

    @staticmethod
    def _fallback_summary_for_exception(
        *,
        results: list[SkillExecutionResult],
        fallback_message: str,
    ) -> dict[str, list[str]]:
        failed = next((item for item in results if item.status == "error"), None)
        if failed is not None:
            message = failed.error_message or fallback_message or "処理中にエラーが発生しました。"
            proposal = [
                "一時障害の可能性があるため、時間をおいて再試行してください。"
                if failed.retryable
                else "入力条件または権限設定を確認して再実行してください。"
            ]
            return {
                "facts": ["要求を完了できませんでした。"],
                "interpretation": [message],
                "proposal": proposal,
            }

        executed_tools = [item.tool_name for item in results if item.tool_name]
        tool_summary = "、".join(executed_tools[:3]) if executed_tools else "ツール実行結果"
        return {
            "facts": [f"{tool_summary} を受領しました。"],
            "interpretation": ["要約生成処理で上流障害が発生したため、フォールバック要約を返します。"],
            "proposal": ["必要に応じて同じ依頼を再実行してください。"],
        }

    def to_markdown_sections(
        self,
        *,
        facts: list[str],
        interpretation: list[str],
        proposal: list[str],
    ) -> str:
        facts_text = "\n".join(f"- {line}" for line in self._ensure_section_lines(facts, "該当する事実はありません。"))
        interpretation_text = "\n".join(
            f"- {line}" for line in self._ensure_section_lines(interpretation, "解釈を生成できませんでした。")
        )
        proposal_text = "\n".join(f"- {line}" for line in self._ensure_section_lines(proposal, "追加の情報を指定してください。"))
        return (
            f"### 【事実】\n{facts_text}\n\n"
            f"### 【解釈】\n{interpretation_text}\n\n"
            f"### 【提案】\n{proposal_text}"
        )

    def summarize_permission_investigation(self, payload: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
        facts = self._coerce_to_lines(payload.get("facts"))
        interpretation = self._coerce_to_lines(payload.get("interpretation"))
        proposal = self._coerce_to_lines(payload.get("proposal"))
        return (
            self._ensure_section_lines(facts, "対象ユーザーと関連証拠を収集しました。"),
            self._ensure_section_lines(interpretation, "収集証拠から実効権限を評価しました。"),
            self._ensure_section_lines(proposal, "必要な追加調査を実施してください。"),
        )

    def summarize_access_denial(self, payload: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
        facts = self._coerce_to_lines(payload.get("facts"))
        interpretation = self._coerce_to_lines(payload.get("interpretation"))
        proposal = self._coerce_to_lines(payload.get("proposal"))
        return (
            self._ensure_section_lines(facts, "アクセス拒否の事実情報を収集しました。"),
            self._ensure_section_lines(interpretation, "拒否原因を評価しました。"),
            self._ensure_section_lines(proposal, "追加調査または修正アクションを検討してください。"),
        )

    def summarize_comparison_snapshot(self, snapshot: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
        success_rate = float(snapshot.get("success_rate") or 0.0)
        retry_rate = float(snapshot.get("retry_rate") or 0.0)
        p95 = int(snapshot.get("p95_latency_ms") or 0)
        error_breakdown = snapshot.get("error_breakdown") or {}

        facts = [
            f"対象スコープ: {snapshot.get('scope') or 'unknown'}",
            f"成功率: {success_rate:.2%}",
            f"p95処理時間: {p95} ms",
            f"再試行率: {retry_rate:.2%}",
        ]
        interpretation = [
            "成功率・再試行率・遅延の差分を継続改善の評価軸として扱います。",
            f"失敗分類: {error_breakdown}" if error_breakdown else "失敗分類は記録されていません。",
        ]
        proposal = [
            "失敗分類の上位項目に対して優先的に改善タスクを設定してください。",
            "期間を分けて比較すると改善施策の有効性を確認しやすくなります。",
        ]
        return facts, interpretation, proposal

    def summarize_a2a_delegation(self, result_payload: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
        facts = self._coerce_to_lines(result_payload.get("facts"))
        interpretation = self._coerce_to_lines(result_payload.get("interpretation"))
        proposal = self._coerce_to_lines(result_payload.get("proposal"))
        if not facts:
            facts = ["他エージェントへの委譲結果を受領しました。"]
        if not interpretation:
            interpretation = ["委譲先の応答を統合して返却します。"]
        if not proposal:
            proposal = ["必要に応じて対象や条件を具体化して再実行してください。"]
        return facts, interpretation, proposal

    def summarize(
        self,
        *,
        turn_id: str,
        user_input: str,
        attempt: int,
        results: list[SkillExecutionResult],
    ) -> ResponseDraft:
        delegation_result = next((item for item in results if item.tool_name == "delegate_to_peer"), None)
        if delegation_result is not None:
            source_payload = delegation_result.raw_response or delegation_result.normalized_data or {}
            if isinstance(source_payload, dict):
                facts, interpretation, proposal = self.summarize_a2a_delegation(source_payload)
                return ResponseDraft(
                    turn_id=turn_id,
                    attempt=attempt,
                    facts=self._ensure_section_lines(facts, "委譲結果を受領しました。"),
                    interpretation=self._ensure_section_lines(interpretation, "委譲結果を解釈しました。"),
                    proposal=self._ensure_section_lines(proposal, "必要な追加入力を指定してください。"),
                    referenced_requests=[item.request_id for item in results],
                    generated_by_model="delegation_passthrough",
                )

        payload = {
            "user_input": user_input,
            "results": [
                {
                    "tool_name": item.tool_name,
                    "status": item.status,
                    "error_code": item.error_code,
                    "error_message": item.error_message,
                    "data": item.normalized_data,
                }
                for item in results
            ],
        }
        generated_by_model = "genai"
        try:
            summary = self.genai_client.summarize_response(user_input=user_input, payload=payload)
        except Exception as exc:
            app_error = classify_exception(exc)
            generated_by_model = "heuristic"
            summary = self._fallback_summary_for_exception(results=results, fallback_message=app_error.message)
        if self.observation_hook is not None:
            try:
                self.observation_hook(
                    {
                        "operation": "response_summarizer",
                        "model_name": generated_by_model,
                        "input_summary": user_input[:200],
                        "output_summary": json.dumps(summary, ensure_ascii=False)[:500],
                    }
                )
            except Exception:
                pass
        return ResponseDraft(
            turn_id=turn_id,
            attempt=attempt,
            facts=self._ensure_section_lines(self._coerce_to_lines(summary.get("facts")), "処理結果を受領しました。"),
            interpretation=self._ensure_section_lines(
                self._coerce_to_lines(summary.get("interpretation")),
                "解釈情報を生成できませんでした。",
            ),
            proposal=self._ensure_section_lines(
                self._coerce_to_lines(summary.get("proposal")),
                "追加条件を指定して再実行してください。",
            ),
            referenced_requests=[item.request_id for item in results],
            generated_by_model=generated_by_model,
        )

    def to_normalized_response(
        self,
        draft: ResponseDraft,
        results: list[SkillExecutionResult],
    ) -> NormalizedResponse:
        result_status = "success"
        for item in results:
            if item.status == "error":
                result_status = "error"
                break
            if item.status == "needs_confirmation":
                result_status = "needs_confirmation"

        merged_data: dict[str, Any] = {item.tool_name: item.normalized_data for item in results}
        audit = AuditPayload(
            target={"tools": [item.tool_name for item in results]},
            input_summary={"request_ids": draft.referenced_requests},
            decision_reason=["スキル実行結果を要約しました。"],
            result=result_status,
        )
        if result_status == "success":
            return NormalizedResponse.success(
                facts=draft.facts,
                interpretation=draft.interpretation,
                proposal=draft.proposal,
                data=merged_data,
                audit=audit,
            )

        if result_status == "needs_confirmation":
            return NormalizedResponse.needs_confirmation(
                facts=draft.facts or ["確認が必要です。"],
                interpretation=draft.interpretation,
                proposal=draft.proposal,
                data=merged_data,
                audit=audit,
            )

        error_item = next((item for item in results if item.status == "error"), None)
        message = error_item.error_message if error_item else "処理に失敗しました。"
        code = error_item.error_code if error_item else "execution_error"
        retryable = bool(error_item.retryable) if error_item else False
        return NormalizedResponse.error(
            message=message,
            code=code,
            retryable=retryable,
            proposal=draft.proposal or ["入力条件を見直して再実行してください。"],
            audit=audit,
        )
