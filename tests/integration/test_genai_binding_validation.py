from __future__ import annotations

from iam_agent.application.input_guard import InputGuard
from iam_agent.application.orchestrator import Orchestrator
from iam_agent.application.response_summarizer import ResponseSummarizer
from iam_agent.application.runtime_preflight import run_runtime_preflight
from iam_agent.application.retry_controller import RetryController
from iam_agent.application.semantic_validator import SemanticValidator
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.config.settings import Settings
from iam_agent.infra.logging.audit_logger import AuditLogger


class _PlannerShouldNotRun:
    def create_plan(self, turn_id: str, user_input: str):  # noqa: ARG002
        raise AssertionError("runtime preflight 失敗時は planner を実行しない")


class _GenAIDummy:
    def summarize_response(self, user_input, payload):  # noqa: ANN001,ARG002
        return {"facts": ["ok"], "interpretation": ["ok"], "proposal": ["ok"]}

    def validate_semantic_alignment(self, user_input, answer_text):  # noqa: ANN001,ARG002
        return {"status": "aligned", "reason": ["ok"], "missing_points": []}


def test_genai_project_binding_validation_stops_execution() -> None:
    settings = Settings(
        domain_url="https://example.identity.oraclecloud.com",
        domain_client_id="id",
        domain_client_secret="secret",
        domain_scope="scope",
        token_url="https://example.identity.oraclecloud.com/oauth2/v1/token",
        compartment_ocid="ocid1.compartment.oc1..example",
        genai_baseurl="https://inference.generativeai.ap-osaka-1.oci.oraclecloud.com",
        genai_project="devday-project",
        genai_project_id="ocid1.generativeaiproject.oc1.ap-osaka-1.old",
        genai_api_key="dummy",
        langfuse_host="https://langfuse.devday26.sogawa-yk.com",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        langfuse_org_id="org",
        langfuse_project_id="proj",
        hr_database_user="hr",
        hr_database_pass="pass",
        hr_database_connectstr="dbhost/service",
        runtime_namespace="iam",
        runtime_ingress_host="iam.devday26.sogawa-yk.com",
    )

    orchestrator = Orchestrator(
        action_planner=_PlannerShouldNotRun(),  # type: ignore[arg-type]
        input_guard=InputGuard(),
        skill_executor=SkillExecutor(handlers={}),
        response_summarizer=ResponseSummarizer(genai_client=_GenAIDummy()),  # type: ignore[arg-type]
        semantic_validator=SemanticValidator(genai_client=_GenAIDummy()),  # type: ignore[arg-type]
        retry_controller=RetryController(max_attempts=3),
        audit_logger=AuditLogger(),
        runtime_preflight_checker=lambda: run_runtime_preflight(settings),
    )

    response = orchestrator.handle_user_input(turn_id="t-genai", user_input="ユーザー一覧を出して")

    assert response.status == "error"
    assert any("genai_project" in line for line in response.facts)
    assert any("genai_project_id" in line for line in response.facts)
