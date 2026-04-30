from __future__ import annotations

from iam_agent.application.errors import AppError
from iam_agent.config.settings import Settings
from iam_agent.domain.models import PeerAgent
from iam_agent.infra.clients.a2a_peer_client import A2APeerClient


class _DummyResponse:
    def __init__(self, *, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _DummySession:
    def __init__(self, responses: list[_DummyResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def get(self, url: str, headers: dict, timeout: float):  # noqa: ANN001
        _ = headers
        _ = timeout
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("stub response is exhausted")
        return self._responses.pop(0)


def _peer() -> PeerAgent:
    return PeerAgent(
        agent_id="peer-1",
        display_name="Peer One",
        trust_state="trusted",
        base_url="https://peer.example.com",
        supported_operations=["list_users"],
        priority=10,
    )


def test_fetch_capabilities_prefers_well_known_agent_card_endpoint() -> None:
    session = _DummySession(
        responses=[
            _DummyResponse(
                status_code=200,
                payload={"agent_id": "peer-1", "version": "1.0.0", "operations": []},
            )
        ]
    )
    client = A2APeerClient(Settings(a2a_agent_id="iam-agent"), session=session)

    payload = client.fetch_capabilities(peer=_peer())

    assert payload["agent_id"] == "peer-1"
    assert session.calls == ["https://peer.example.com/.well-known/agent.json"]


def test_fetch_capabilities_falls_back_to_legacy_endpoint_when_well_known_not_found() -> None:
    session = _DummySession(
        responses=[
            _DummyResponse(status_code=404, payload={"detail": "not found"}),
            _DummyResponse(
                status_code=200,
                payload={"agent_id": "peer-1", "version": "1.0.0", "operations": []},
            ),
        ]
    )
    client = A2APeerClient(Settings(a2a_agent_id="iam-agent"), session=session)

    payload = client.fetch_capabilities(peer=_peer())

    assert payload["agent_id"] == "peer-1"
    assert session.calls == [
        "https://peer.example.com/.well-known/agent.json",
        "https://peer.example.com/a2a/capabilities",
    ]


def test_fetch_capabilities_raises_when_no_card_endpoint_exists() -> None:
    session = _DummySession(
        responses=[
            _DummyResponse(status_code=404, payload={"detail": "not found"}),
            _DummyResponse(status_code=404, payload={"detail": "not found"}),
        ]
    )
    client = A2APeerClient(Settings(a2a_agent_id="iam-agent"), session=session)

    try:
        client.fetch_capabilities(peer=_peer())
    except AppError as exc:
        assert exc.code == "peer_capability_error"
        return
    raise AssertionError("peer_capability_error が発生しませんでした。")
