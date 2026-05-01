from __future__ import annotations

from pathlib import Path

import iam_agent.api.orch_routes as routes


ROOT = Path(__file__).resolve().parents[2]


def test_k8s_manifests_target_new_namespace_and_domain() -> None:
    deployment = (ROOT / "k8s" / "deployment.yaml").read_text(encoding="utf-8")
    service = (ROOT / "k8s" / "service.yaml").read_text(encoding="utf-8")
    ingress = (ROOT / "k8s" / "ingress.yaml").read_text(encoding="utf-8")
    configmap = (ROOT / "k8s" / "configmap.yaml").read_text(encoding="utf-8")

    assert "namespace: iam" in deployment
    assert "namespace: iam" in service
    assert "namespace: iam" in ingress
    assert "host: iam.devday26.sogawa-yk.com" in ingress
    assert 'genai_project: "iam"' in configmap
    assert "genai_project_id:" in configmap


def test_health_and_ui_contract_still_available() -> None:
    assert routes.health() == {"status": "ok"}
    redirect = routes.chat_ui_redirect()
    assert redirect.status_code == 307
    assert redirect.headers.get("location") == "/ui"
