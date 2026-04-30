from __future__ import annotations

from iam_agent.config.settings import Settings
from iam_agent.observability.langfuse_client import LangfuseClient


class FakeLangfuseSdk:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.scores: list[dict] = []
        self.flush_count = 0

    def create_event(self, **kwargs):  # noqa: ANN003
        self.events.append(kwargs)
        return {"ok": True}

    def create_score(self, **kwargs):  # noqa: ANN003
        self.scores.append(kwargs)

    def flush(self) -> None:
        self.flush_count += 1


def _settings() -> Settings:
    return Settings(
        langfuse_enabled=True,
        langfuse_host="https://langfuse.koin3z.com",
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
        langfuse_org_id="cmoe9rmed0006xu06afe0d9bg",
        langfuse_project_id="cmoe9rrfd000bxu06xlivnbba",
        langfuse_org_name="devday-agents",
        langfuse_project_name="iam-agent",
    )


def test_send_trace_uses_create_event_and_create_score() -> None:
    client = LangfuseClient(_settings())
    fake_sdk = FakeLangfuseSdk()
    client._client = fake_sdk

    status, reason = client.send_trace(
        {
            "trace_id": "trace-1",
            "turn_id": "turn-1",
            "request_id": "req-1",
            "request_type": "permission_investigation",
            "status": "success",
            "compatibility_status": "additive_layer",
            "user_prompt_summary": "加藤さんはどの操作が許可されていますか？",
            "spans": [
                {"span_id": "s1", "stage": "action_planning", "attempt": 1, "status": "success", "latency_ms": 10},
                {"span_id": "s2", "stage": "tool_execution", "attempt": 1, "status": "success", "latency_ms": 20},
            ],
            "quality_score": {"semantic_alignment": 1.0, "retry_count": 0, "response_status": "success"},
        }
    )

    assert status == "sent"
    assert reason == "ok"
    assert fake_sdk.flush_count == 1
    assert len(fake_sdk.events) == 3
    assert fake_sdk.events[0]["name"] == "permission_investigation"
    assert fake_sdk.events[1]["name"] == "stage:action_planning"
    assert fake_sdk.events[2]["name"] == "stage:tool_execution"
    assert fake_sdk.scores
    normalized_trace_id = str(fake_sdk.scores[0]["trace_id"])
    assert len(normalized_trace_id) == 32
    assert all(char in "0123456789abcdef" for char in normalized_trace_id)


def test_send_snapshot_uses_create_event() -> None:
    client = LangfuseClient(_settings())
    fake_sdk = FakeLangfuseSdk()
    client._client = fake_sdk

    status, reason = client.send_snapshot({"scope": "permission_investigation", "count": 1})

    assert status == "sent"
    assert reason == "ok"
    assert fake_sdk.flush_count == 1
    assert len(fake_sdk.events) == 1
    assert fake_sdk.events[0]["name"] == "comparison_snapshot"
