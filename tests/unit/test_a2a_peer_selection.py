from __future__ import annotations

import json

from iam_agent.config.settings import Settings
from iam_agent.infra.clients.a2a_peer_client import A2APeerClient


def _peer_client() -> A2APeerClient:
    settings = Settings(
        a2a_peer_registry_json=json.dumps(
            [
                {
                    "agent_id": "peer-fast",
                    "trust_state": "trusted",
                    "base_url": "https://fast.example.com",
                    "supported_operations": ["list_users", "list_policies"],
                    "priority": 5,
                },
                {
                    "agent_id": "peer-slow",
                    "trust_state": "trusted",
                    "base_url": "https://slow.example.com",
                    "supported_operations": ["list_users"],
                    "priority": 20,
                },
                {
                    "agent_id": "peer-blocked",
                    "trust_state": "blocked",
                    "base_url": "https://blocked.example.com",
                    "supported_operations": ["list_users"],
                    "priority": 1,
                },
            ]
        )
    )
    return A2APeerClient(settings)


def test_peer_selection_prefers_trusted_capability_and_priority() -> None:
    client = _peer_client()
    selected, candidates = client.select_peer_for_operation(operation_name="list_users")
    assert selected is not None
    assert selected.agent_id == "peer-fast"
    assert [peer.agent_id for peer in candidates] == ["peer-fast", "peer-slow"]


def test_peer_selection_returns_ambiguous_when_priority_is_tied() -> None:
    settings = Settings(
        a2a_peer_registry_json=json.dumps(
            [
                {
                    "agent_id": "peer-a",
                    "trust_state": "trusted",
                    "base_url": "https://a.example.com",
                    "supported_operations": ["list_users"],
                    "priority": 10,
                },
                {
                    "agent_id": "peer-b",
                    "trust_state": "trusted",
                    "base_url": "https://b.example.com",
                    "supported_operations": ["list_users"],
                    "priority": 10,
                },
            ]
        )
    )
    client = A2APeerClient(settings)
    selected, candidates = client.select_peer_for_operation(operation_name="list_users")
    assert selected is None
    assert len(candidates) == 2
