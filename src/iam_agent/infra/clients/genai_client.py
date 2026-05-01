from __future__ import annotations

import json
import re
from typing import Any

from iam_agent.application.errors import InvalidArgumentError, MissingCredentialError, TemporaryUpstreamFailure
from iam_agent.config.runtime_contract import EXPECTED_GENAI_PROJECT_ID, EXPECTED_GENAI_PROJECT_NAME
from iam_agent.config.settings import Settings

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


class GenAIClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None

        if OpenAI is not None and settings.genai_api_key and settings.genai_baseurl:
            # OCI Generative AI Responses API は OpenAI-Project ヘッダーが必須。
            self._client = OpenAI(
                api_key=settings.genai_api_key,
                base_url=settings.genai_baseurl,
                project=settings.genai_project_id,
            )

    def _ensure_credentials(self) -> None:
        missing = self.settings.missing_for_route("genai_api_key")
        if missing:
            raise MissingCredentialError(missing)
        self._ensure_project_binding()

    def _ensure_project_binding(self) -> None:
        if self.settings.genai_project != EXPECTED_GENAI_PROJECT_NAME:
            raise InvalidArgumentError(
                f"genai_project が不正です。期待値={EXPECTED_GENAI_PROJECT_NAME}, 実値={self.settings.genai_project or '(empty)'}"
            )
        if self.settings.genai_project_id != EXPECTED_GENAI_PROJECT_ID:
            raise InvalidArgumentError(
                f"genai_project_id が不正です。期待値={EXPECTED_GENAI_PROJECT_ID}, 実値={self.settings.genai_project_id or '(empty)'}"
            )

    def _response_text(self, response: Any) -> str:
        try:
            return response.output_text
        except Exception:
            pass
        try:
            return str(response)
        except Exception:
            return ""

    @staticmethod
    def _preview(values: list[str], *, limit: int = 8) -> str:
        visible = values[:limit]
        text = ", ".join(visible)
        remaining = len(values) - len(visible)
        if remaining > 0:
            return f"{text} ほか{remaining}件"
        return text

    def _summarize_locally(self, payload: dict[str, Any]) -> dict[str, list[str]]:
        facts: list[str] = []
        interpretation: list[str] = ["GenAI要約の生成に失敗したため、実行結果を要約して返します。"]
        proposal: list[str] = []

        results = payload.get("results")
        if not isinstance(results, list):
            return {
                "facts": ["処理結果を受領しました。"],
                "interpretation": interpretation,
                "proposal": ["再試行するか、対象条件を具体化してください。"],
            }

        for item in results:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "") != "success":
                continue

            tool_name = str(item.get("tool_name") or "")
            data = item.get("data")
            if not isinstance(data, dict):
                continue

            if tool_name == "list_users":
                users = data.get("users")
                if isinstance(users, list):
                    total_raw = data.get("total_results")
                    try:
                        total = int(total_raw) if total_raw is not None else len(users)
                    except Exception:
                        total = len(users)
                    facts.append(f"ユーザー一覧を取得しました（{total}件）。")
                    names = [
                        str(user.get("userName") or user.get("displayName") or "").strip()
                        for user in users
                        if isinstance(user, dict)
                    ]
                    names = [name for name in names if name]
                    if names:
                        facts.append(f"主なユーザー: {self._preview(names)}")
                    proposal.append("対象ユーザーを指定すると、詳細情報を続けて確認できます。")
                continue

            if tool_name == "list_policies":
                policies = data.get("policies")
                if isinstance(policies, list):
                    facts.append(f"ポリシー一覧を取得しました（{len(policies)}件）。")
                    names = [
                        str(policy.get("name") or "").strip()
                        for policy in policies
                        if isinstance(policy, dict)
                    ]
                    names = [name for name in names if name]
                    if names:
                        facts.append(f"ポリシー名: {self._preview(names)}")
                    interpretation.append("各ポリシーの statements から、許可操作の範囲を確認できます。")
                    proposal.append("対象ポリシー名を指定すると、影響範囲を具体的に説明できます。")
                continue

        if not facts:
            facts = ["処理結果を受領しました。"]
        if len(interpretation) == 1 and not facts:
            interpretation.append("実行結果から解釈可能な情報を抽出できませんでした。")
        if not proposal:
            proposal = ["必要に応じて対象ユーザー名やポリシー名を指定して再実行してください。"]
        return {"facts": facts, "interpretation": interpretation, "proposal": proposal}

    def plan_action(self, user_input: str, available_tools: list[str]) -> dict[str, Any]:
        self._ensure_credentials()
        if self._client is None:
            return {
                "steps": [
                    {
                        "step_id": "step-1",
                        "tool_name": "list_users",
                        "required_inputs": [],
                        "provided_inputs": {},
                        "execution_order": 1,
                        "reason": "GenAIクライアント未初期化のため既定プランを使用",
                    }
                ]
            }

        prompt = (
            "ユーザー入力を処理するためのActionPlanをJSONのみで返してください。"
            "キーは steps (配列) で、各stepに step_id, tool_name, required_inputs, "
            "provided_inputs, execution_order, reason を含めてください。"
            "provided_inputs には `${...}` や `{{...}}` の未解決プレースホルダーを含めないでください。"
            "OCIユーザーの作成・追加依頼では create_user を優先してください。"
            "ただし、グループへの追加/削除依頼（例: ○○グループに追加）は add_user_to_group/remove_user_from_group を選択してください。"
            f"利用可能ツール: {available_tools}. ユーザー入力: {user_input}"
        )
        try:
            response = self._client.responses.create(model=self.settings.genai_model, input=prompt)
            parsed = _extract_json(self._response_text(response))
            return parsed if parsed else {"steps": []}
        except Exception as exc:  # pragma: no cover - network dependent
            raise TemporaryUpstreamFailure(f"ActionPlan生成に失敗しました: {exc}") from exc

    def summarize_response(self, user_input: str, payload: dict[str, Any]) -> dict[str, list[str]]:
        self._ensure_credentials()
        if self._client is None:
            return {
                "facts": ["処理結果を受領しました。"],
                "interpretation": ["ローカルフォールバック要約を返します。"],
                "proposal": ["詳細入力が必要な場合は追加してください。"],
            }

        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        prompt = (
            "次のJSONをユーザー向けに日本語で要約し、facts/interpretation/proposal の"
            "3キーJSONで返してください。各キーは必ず文字列の配列にしてください。"
            "配列要素にオブジェクト(JSON/dict)や配列を入れないでください。"
            f" user_input={user_input}, payload={payload_json}"
        )
        try:
            response = self._client.responses.create(model=self.settings.genai_model, input=prompt)
            parsed = _extract_json(self._response_text(response))
            if parsed:
                return {
                    "facts": parsed.get("facts") or [],
                    "interpretation": parsed.get("interpretation") or [],
                    "proposal": parsed.get("proposal") or [],
                }
        except Exception:  # pragma: no cover - network dependent
            return self._summarize_locally(payload)

        return self._summarize_locally(payload)

    def validate_semantic_alignment(self, user_input: str, answer_text: str) -> dict[str, Any]:
        self._ensure_credentials()
        if self._client is None:
            aligned = user_input[:8] in answer_text if user_input else True
            return {
                "status": "aligned" if aligned else "not_aligned",
                "reason": ["ローカルヒューリスティック判定"],
                "missing_points": [] if aligned else ["ユーザー入力の主要語が不足"],
            }

        prompt = (
            "次の user_input と answer が意味的に対応しているか判定し、"
            "status(aligned/not_aligned), reason(配列), missing_points(配列) をJSONで返してください。"
            f"user_input={user_input}, answer={answer_text}"
        )
        try:
            response = self._client.responses.create(model=self.settings.genai_model, input=prompt)
            parsed = _extract_json(self._response_text(response))
            if parsed:
                return {
                    "status": parsed.get("status", "not_aligned"),
                    "reason": parsed.get("reason") or ["判定理由なし"],
                    "missing_points": parsed.get("missing_points") or [],
                }
        except Exception as exc:  # pragma: no cover - network dependent
            raise TemporaryUpstreamFailure(f"意味整合チェックに失敗しました: {exc}") from exc

        return {
            "status": "not_aligned",
            "reason": ["判定結果を解釈できませんでした。"],
            "missing_points": ["要約の再生成が必要"],
        }
