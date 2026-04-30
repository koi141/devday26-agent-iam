from __future__ import annotations

import os
from typing import Any
import uuid

from iam_agent.application.action_planner import ActionPlanner
from iam_agent.application.a2a_collaboration_service import A2ACollaborationService
from iam_agent.application.input_guard import InputGuard
from iam_agent.application.orchestrator import Orchestrator
from iam_agent.application.permission_investigator import PermissionInvestigator
from iam_agent.application.response_summarizer import ResponseSummarizer
from iam_agent.application.retry_controller import RetryController
from iam_agent.application.semantic_validator import SemanticValidator
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.config.settings import get_settings
from iam_agent.infra.auth.identity_domain_oauth import IdentityDomainOAuthProvider
from iam_agent.infra.auth.workload_identity import OciAuthResolver
from iam_agent.infra.clients.a2a_peer_client import A2APeerClient
from iam_agent.infra.clients.genai_client import GenAIClient
from iam_agent.infra.clients.hr_db_client import HrDbClient
from iam_agent.infra.clients.identity_domain_client import IdentityDomainClient
from iam_agent.infra.clients.oci_identity_client import OciIdentityClient
from iam_agent.infra.clients.oci_resource_search_client import OciResourceSearchClient
from iam_agent.infra.logging.audit_logger import AuditLogger
from iam_agent.observability import LangfuseClient, QualityEvaluator, SnapshotStore, TelemetryBridge
from iam_agent.skills.dormant_credential_audit import DormantCredentialAuditSkill
from iam_agent.skills.resource_inventory import ResourceInventorySkill
from iam_agent.skills.user_permission_investigation import UserPermissionInvestigationSkill
from iam_agent.skills.user_provisioning import UserProvisioningSkill
from iam_agent.tools.hr_tools import HrTools
from iam_agent.tools.identity_domain_tools import IdentityDomainTools
from iam_agent.tools.oci_tools import OciTools

try:
    import chainlit as cl
except Exception:  # pragma: no cover - chainlit is optional for tests
    cl = None


_ORCHESTRATOR: Orchestrator | None = None


def build_orchestrator() -> Orchestrator:
    settings = get_settings()

    oauth_provider = IdentityDomainOAuthProvider(settings=settings)
    identity_client = IdentityDomainClient(
        domain_url=settings.domain_url,
        token_supplier=oauth_provider.get_access_token,
    )
    hr_tools = HrTools(HrDbClient(settings=settings))

    oci_client = None
    oci_resource_search_client = None
    oci_init_error = ""
    try:
        use_local = (os.getenv("IAM_AGENT_LOCAL_OCI", "false").lower() == "true")
        auth_resolver = OciAuthResolver(settings=settings)
        auth_context = auth_resolver.resolve_local_profile() if use_local else auth_resolver.resolve_workload_identity()
        oci_client = OciIdentityClient(auth_context=auth_context)
        oci_resource_search_client = OciResourceSearchClient(auth_context=auth_context)
    except Exception as exc:
        oci_init_error = f"{type(exc).__name__}: {exc}"
        oci_client = None
        oci_resource_search_client = None

    identity_tools = IdentityDomainTools(client=identity_client, hr_tools=hr_tools)
    oci_tools = OciTools(
        client=oci_client,
        settings=settings,
        init_error=oci_init_error,
        resource_search_client=oci_resource_search_client,
    )

    # 既存 tool 参照点の棚卸し:
    # - Identity Domains 読み書き
    # - OCI IAM 参照
    # - HR DB 参照
    # 上位層はこの registry だけを参照し、tools 実装詳細には依存しない。
    handlers = {
        "list_users": identity_tools.list_users,
        "get_user": identity_tools.get_user,
        "create_user": identity_tools.create_user,
        "list_groups": identity_tools.list_groups,
        "get_group": identity_tools.get_group,
        "add_user_to_group": identity_tools.add_user_to_group,
        "remove_user_from_group": identity_tools.remove_user_from_group,
        "list_user_credentials": identity_tools.list_user_credentials,
        "get_last_successful_login": identity_tools.get_last_successful_login,
        "query_hr_database": hr_tools.query_hr_database,
        "list_compartments": oci_tools.list_compartments,
        "list_resources": oci_tools.list_resources,
        "list_policies": oci_tools.list_policies,
        "get_policy": oci_tools.get_policy,
    }

    genai = GenAIClient(settings=settings)
    snapshot_store = SnapshotStore()
    input_guard = InputGuard()
    audit_logger = AuditLogger()
    retry_controller = RetryController(max_attempts=3)
    skill_executor = SkillExecutor(handlers=handlers)
    permission_investigator = PermissionInvestigator(skill_executor=skill_executor)
    skill_executor.register_skill(
        UserPermissionInvestigationSkill.skill_name,
        UserPermissionInvestigationSkill(permission_investigator).execute,
    )
    skill_executor.register_skill(
        UserProvisioningSkill.skill_name,
        UserProvisioningSkill(skill_executor).execute,
    )
    skill_executor.register_skill(
        ResourceInventorySkill.skill_name,
        ResourceInventorySkill(skill_executor).execute,
    )
    skill_executor.register_skill(
        DormantCredentialAuditSkill.skill_name,
        DormantCredentialAuditSkill(skill_executor).execute,
    )
    a2a_service = A2ACollaborationService(
        settings=settings,
        input_guard=input_guard,
        skill_executor=skill_executor,
        audit_logger=audit_logger,
        peer_client=A2APeerClient(settings=settings),
        retry_controller=retry_controller,
    )
    skill_executor.handlers["delegate_to_peer"] = a2a_service.delegate_to_peer

    return Orchestrator(
        action_planner=ActionPlanner(genai_client=genai),
        input_guard=input_guard,
        skill_executor=skill_executor,
        response_summarizer=ResponseSummarizer(genai_client=genai),
        semantic_validator=SemanticValidator(genai_client=genai),
        retry_controller=retry_controller,
        audit_logger=audit_logger,
        permission_investigator=permission_investigator,
        a2a_service=a2a_service,
        telemetry_bridge=TelemetryBridge(langfuse_client=LangfuseClient(settings=settings)),
        quality_evaluator=QualityEvaluator(),
        snapshot_store=snapshot_store,
    )


def get_orchestrator() -> Orchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = build_orchestrator()
    return _ORCHESTRATOR


def reset_orchestrator_for_test() -> None:
    global _ORCHESTRATOR
    _ORCHESTRATOR = None


def process_message(user_input: str) -> dict[str, Any]:
    orchestrator = get_orchestrator()
    turn_id = f"turn-{uuid.uuid4()}"
    response = orchestrator.handle_user_input(turn_id=turn_id, user_input=user_input)
    return response.to_dict()


def get_snapshot(*, scope: str, window_start: str = "", window_end: str = "") -> dict[str, Any]:
    orchestrator = get_orchestrator()
    return orchestrator.snapshot_store.build_snapshot(scope=scope, window_start=window_start, window_end=window_end)


if cl is not None:

    @cl.on_chat_start
    async def on_chat_start() -> None:
        welcome = (
            "OCI IAM / Identity Domains 運用支援エージェントを開始しました。\n\n"
            "このエージェントでできること:\n"
            "- Identity Domains ユーザー操作: 一覧/詳細/作成、最終ログイン確認\n"
            "- グループ操作: 一覧/詳細、ユーザー追加・削除\n"
            "- 資格情報確認: API Keys / Auth Tokens 一覧\n"
            "- OCI IAM 参照: compartments / resources / policies の一覧・詳細\n"
            "- 不足情報の補完: ユーザー作成時に HR データベースを検索\n\n"
            "正しく実行しやすいプロンプト例:\n"
            "- 「ユーザー一覧を出して」\n"
            "- 「devday26 のコンパートメント階層を表示して」\n"
            "- 「devday26 のリソース一覧を表示して」\n"
            "- 「加藤さんをOCIユーザーとして作成してください」\n"
            "- 「加藤さんユーザーをDomain_Administratorsグループに追加してください」\n"
            "- 「ポリシー一覧を表示して」\n\n"
            "補足:\n"
            "- 人名だけで曖昧な場合は、候補を確認してから実行します。\n"
            "- メールアドレスやグループ名が分かる場合は一緒に指定すると精度が上がります。"
        )
        await cl.Message(content=welcome).send()

    @cl.on_message
    async def on_message(message: "cl.Message") -> None:
        def _as_md_lines(items: list[str]) -> str:
            if not items:
                return "- なし"
            return "\n".join(f"- {line}" for line in items)

        try:
            payload = process_message(message.content)
            facts = payload.get("facts", []) or []
            interpretation = payload.get("interpretation", []) or []
            proposal = payload.get("proposal", []) or []
            meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
            delivery_status = str(meta.get("telemetry_delivery_status") or "")
            if delivery_status == "failed":
                interpretation = interpretation + ["可観測性記録は一部欠落しましたが、主処理は継続しています。"]
                proposal = proposal + ["Langfuse設定または接続状態を確認してください。"]
            elif delivery_status == "skipped":
                interpretation = interpretation + ["可観測性記録は無効化または資格情報不足のため送信されませんでした。"]
        except Exception as exc:  # pragma: no cover - runtime safety net
            facts = ["要求を完了できませんでした。"]
            interpretation = [f"内部エラーが発生しました: {type(exc).__name__}"]
            proposal = ["入力条件を確認して再試行してください。問題が続く場合は運用ログを確認してください。"]

        reply = (
            "### 【事実】\n"
            f"{_as_md_lines(facts)}\n\n"
            "### 【解釈】\n"
            f"{_as_md_lines(interpretation)}\n\n"
            "### 【提案】\n"
            f"{_as_md_lines(proposal)}"
        )
        await cl.Message(content=reply).send()
