from __future__ import annotations

import iam_agent.app.chainlit_entry as chainlit_entry
from iam_agent.application.errors import TemporaryUpstreamFailure


def test_process_message_returns_structured_error_when_orchestrator_raises(monkeypatch) -> None:
    def _raise() -> None:
        raise TemporaryUpstreamFailure("上流サービスが一時的に利用できません。")

    monkeypatch.setattr(chainlit_entry, "get_orchestrator", _raise)

    payload = chainlit_entry.process_message("ポリシー一覧を出して")

    assert payload["status"] == "error"
    assert payload["facts"] == ["要求を完了できませんでした。"]
    assert "上流サービスが一時的に利用できません" in payload["interpretation"][0]
    assert payload["errors"][0]["code"] == "temporary_upstream_failure"
