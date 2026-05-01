from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
import uuid

from iam_agent.application.errors import (
    AppError,
    DelegationTimeoutError,
    IdempotencyConflictError,
    InvalidArgumentError,
    LoopDetectedError,
    PeerUntrustedError,
    classify_exception,
)
from iam_agent.application.high_risk_guard import HIGH_RISK_TOOLS
from iam_agent.application.input_guard import InputGuard, TOOL_REQUIRED_INPUTS
from iam_agent.application.retry_controller import RetryController
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.config.settings import Settings
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.domain.models import (
    A2AAuditRecord,
    A2ACapabilityOperation,
    A2ACapabilityProfile,
    A2ACapabilitySkill,
    A2AExecutionRequest,
    A2AExecutionStep,
    A2AIdempotencyRecord,
    A2AExecutionResult,
    SkillExecutionResult,
)
from iam_agent.infra.clients.a2a_peer_client import A2APeerClient
from iam_agent.infra.logging.audit_logger import AuditLogger


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class A2ACollaborationService:
    def __init__(
        self,
        *,
        settings: Settings,
        input_guard: InputGuard,
        skill_executor: SkillExecutor,
        audit_logger: AuditLogger,
        peer_client: A2APeerClient,
        retry_controller: RetryController | None = None,
    ) -> None:
        self.settings = settings
        self.input_guard = input_guard
        self.skill_executor = skill_executor
        self.audit_logger = audit_logger
        self.peer_client = peer_client
        self.retry_controller = retry_controller
        self._orchestrator: Any | None = None
        self._idempotency_records: dict[str, tuple[A2AIdempotencyRecord, NormalizedResponse]] = {}
        self._supported_operations = self._build_supported_operations()

    def bind_orchestrator(self, orchestrator: Any) -> None:
        self._orchestrator = orchestrator

    def capabilities(self, *, source_agent_id: str = "", auth_token: str = "") -> dict[str, Any]:
        if not self.settings.a2a_enabled:
            return self._error_payload(
                code="a2a_disabled",
                facts=["A2A 機能は無効化されています。"],
                interpretation=["a2a_enabled=false のため capabilities を返却できません。"],
                proposal=["A2A機能を有効化して再実行してください。"],
            )

        if not source_agent_id.strip():
            return self._error_payload(
                code="peer_untrusted",
                facts=["依頼元識別子が不足しているため拒否しました。"],
                interpretation=["A2A capabilities は信頼済み peer のみ取得できます。"],
                proposal=["X-Source-Agent-ID または source_agent_id を指定してください。"],
            )
        try:
            self.peer_client.verify_incoming_peer(source_agent_id=source_agent_id, auth_token=auth_token)
        except Exception as exc:
            app_error = classify_exception(exc)
            return self._error_payload(
                code=app_error.code,
                facts=["信頼されていない依頼元のため拒否しました。"],
                interpretation=[app_error.message],
                proposal=["peer registry と認証トークンを確認してください。"],
            )

        sorted_operations = sorted(tool_name for tool_name in self._supported_operations if tool_name != "delegate_to_peer")
        operations: list[dict[str, Any]] = []
        for tool_name in sorted_operations:
            operation = A2ACapabilityOperation(
                operation_name=tool_name,
                required_inputs=TOOL_REQUIRED_INPUTS.get(tool_name, []),
                risk_level="high" if tool_name in HIGH_RISK_TOOLS else "low",
                description=f"{tool_name} を A2A で実行可能",
            )
            operations.append(asdict(operation))

        profile = A2ACapabilityProfile(
            agent_id=self.settings.a2a_agent_id,
            version="1.0.0",
            description=(
                "OCI IAM / Identity Domains の運用支援エージェントです。"
                "ユーザー・グループ管理、権限調査、ポリシー/リソース参照、HR補完を実行できます。"
            ),
            skills=self._build_capability_skills(sorted_operations),
            operations=[
                A2ACapabilityOperation(
                    operation_name=str(item.get("operation_name") or ""),
                    required_inputs=[str(x) for x in item.get("required_inputs", [])],
                    risk_level=str(item.get("risk_level") or "low"),  # type: ignore[arg-type]
                    description=str(item.get("description") or ""),
                )
                for item in operations
            ],
            constraints=[
                "高リスク操作では idempotency_key が必須です。",
                "hop_count が上限を超える要求は拒否します。",
                "未信頼peerからの要求は拒否します。",
            ],
        )
        return asdict(profile)

    def execute(self, *, payload: dict[str, Any], auth_token: str = "") -> NormalizedResponse:
        if not self.settings.a2a_enabled:
            return self._error_response(
                code="a2a_disabled",
                message="A2A 機能が無効です。",
                proposal=["a2a_enabled を有効化して再実行してください。"],
                request_payload=payload,
            )

        violations = self.input_guard.validate_a2a_request(
            payload,
            max_hops=self.settings.a2a_max_hops,
            self_agent_id=self.settings.a2a_agent_id,
            high_risk_operations=HIGH_RISK_TOOLS,
        )
        if violations:
            return self._build_validation_error(payload=payload, violations=violations)

        request = A2AExecutionRequest.from_payload(payload)
        if request.target_agent_id and request.target_agent_id != self.settings.a2a_agent_id:
            return self._error_response(
                code="invalid_argument",
                message=f"target_agent_id が不正です: {request.target_agent_id}",
                proposal=[f"target_agent_id に {self.settings.a2a_agent_id} を指定してください。"],
                request_payload=payload,
                correlation_id=request.correlation_id,
                peer_agent=request.source_agent_id,
                delegation_outcome="rejected",
            )

        try:
            self.peer_client.verify_incoming_peer(source_agent_id=request.source_agent_id, auth_token=auth_token)
        except Exception as exc:
            app_error = classify_exception(exc)
            return self._error_response(
                code=app_error.code,
                message=app_error.message,
                proposal=["source_agent_id と peer 認証トークンを確認してください。"],
                request_payload=payload,
                correlation_id=request.correlation_id,
                peer_agent=request.source_agent_id,
                delegation_outcome="rejected",
            )

        if request.requested_operation not in self._supported_operations:
            return self._error_response(
                code="unsupported_operation",
                message=f"未対応操作です: {request.requested_operation}",
                proposal=["/.well-known/agent.json で対応操作を確認してください。"],
                request_payload=payload,
                correlation_id=request.correlation_id,
                peer_agent=request.source_agent_id,
                delegation_outcome="rejected",
            )

        try:
            self._ensure_loop_protection(request)
            replay_response = self._handle_idempotency_replay_if_needed(request)
            if replay_response is not None:
                return replay_response

            step = A2AExecutionStep(
                step_id=f"step-{uuid.uuid4()}",
                executor_agent_id=self.settings.a2a_agent_id,
                operation_name=request.requested_operation,
                status="skipped",
            )
            execute_payload = dict(request.input_payload)
            execute_payload["__a2a_context"] = {
                "source_agent_id": request.source_agent_id,
                "correlation_id": request.correlation_id,
                "request_id": request.request_id,
                "idempotency_key": request.idempotency_key,
                "hop_count": request.hop_count,
                "visited_agents": request.visited_agents,
            }
            result = self.skill_executor.execute(request.requested_operation, execute_payload)
            response = self._response_from_skill_result(request=request, result=result, step=step)
            self._save_idempotency_record_if_needed(request=request, response=response)
            self._record_audit(request=request, response=response, delegation_outcome="handled_locally")
            return response
        except Exception as exc:
            app_error = classify_exception(exc)
            return self._error_response(
                code=app_error.code,
                message=app_error.message,
                proposal=["入力項目とA2A設定を確認して再実行してください。"],
                request_payload=payload,
                correlation_id=request.correlation_id,
                peer_agent=request.source_agent_id,
                delegation_outcome="error",
                retryable=app_error.retryable,
            )

    def delegate_to_peer(self, payload: dict[str, Any]) -> NormalizedResponse:
        objective = str(payload.get("objective") or "").strip()
        requested_operation = str(payload.get("requested_operation") or payload.get("operation_name") or "").strip()
        if not objective:
            return NormalizedResponse.error(
                message="objective が必要です。",
                code="missing_input",
                retryable=False,
                proposal=["委譲目的 objective を指定して再実行してください。"],
                audit=AuditPayload(
                    target={"service": "a2a"},
                    input_summary={"keys": sorted(payload.keys())},
                    decision_reason=["委譲要求の必須入力不足"],
                    result="error",
                ),
            )
        if not requested_operation:
            return NormalizedResponse.error(
                message="requested_operation が必要です。",
                code="missing_input",
                retryable=False,
                proposal=["委譲先で実行する requested_operation を指定してください。"],
                audit=AuditPayload(
                    target={"service": "a2a"},
                    input_summary={"objective": objective},
                    decision_reason=["委譲操作の不足"],
                    result="error",
                ),
            )

        correlation_id = str(payload.get("correlation_id") or f"corr-{uuid.uuid4()}").strip()
        visited_agents = [str(item) for item in (payload.get("visited_agents") or []) if str(item).strip()]
        visited_set = set(visited_agents)
        visited_set.add(self.settings.a2a_agent_id)

        selected, candidates = self.peer_client.select_peer_for_operation(
            operation_name=requested_operation,
            exclude_agent_ids=visited_set,
        )
        if selected is None and candidates:
            return NormalizedResponse.needs_confirmation(
                facts=["委譲候補が複数見つかり優先順位を確定できません。"],
                interpretation=["同優先度の trusted peer が複数存在します。"],
                proposal=["委譲先エージェントIDを指定してください。"],
                data={
                    "candidate_peers": [asdict(item) for item in candidates],
                    "requested_operation": requested_operation,
                },
                audit=AuditPayload(
                    target={"service": "a2a", "requested_operation": requested_operation},
                    input_summary={"objective": objective},
                    decision_reason=["peer選定が曖昧"],
                    result="needs_confirmation",
                    correlation_id=correlation_id,
                    delegation_outcome="selection_ambiguous",
                ),
            )
        if selected is None:
            return NormalizedResponse.error(
                message=f"委譲先が見つかりません: {requested_operation}",
                code="peer_not_found",
                retryable=False,
                proposal=["peer registry の supported_operations を確認してください。"],
                audit=AuditPayload(
                    target={"service": "a2a", "requested_operation": requested_operation},
                    input_summary={"objective": objective},
                    decision_reason=["委譲先未登録"],
                    result="error",
                    correlation_id=correlation_id,
                    delegation_outcome="peer_not_found",
                ),
            )

        request_payload = {
            "request_id": str(payload.get("request_id") or f"a2a-{uuid.uuid4()}"),
            "correlation_id": correlation_id,
            "source_agent_id": self.settings.a2a_agent_id,
            "target_agent_id": selected.agent_id,
            "requested_operation": requested_operation,
            "objective": objective,
            "input_payload": payload.get("input_payload") if isinstance(payload.get("input_payload"), dict) else {},
            "constraints": payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {},
            "idempotency_key": str(payload.get("idempotency_key") or ""),
            "hop_count": int(payload.get("hop_count") or 0) + 1,
            "visited_agents": sorted(visited_set),
            "requested_at": payload.get("requested_at") or _utc_now_iso(),
        }

        if self.retry_controller is not None and request_payload.get("idempotency_key"):
            self.retry_controller.bind_a2a_idempotency(str(request_payload["idempotency_key"]))

        try:
            remote_response = self.peer_client.execute_delegation(
                peer=selected,
                request_payload=request_payload,
                max_retries=1,
            )
        except DelegationTimeoutError as exc:
            return NormalizedResponse.error(
                message=str(exc),
                code="delegation_timeout",
                retryable=True,
                proposal=["しばらく待って再実行するか、別の委譲先を指定してください。"],
                audit=AuditPayload(
                    target={"service": "a2a", "peer_agent": selected.agent_id},
                    input_summary={"requested_operation": requested_operation},
                    decision_reason=["委譲先タイムアウト"],
                    result="error",
                    correlation_id=correlation_id,
                    peer_agent=selected.agent_id,
                    delegation_outcome="timeout",
                ),
            )
        except Exception as exc:
            app_error = classify_exception(exc)
            return NormalizedResponse.error(
                message=app_error.message,
                code=app_error.code,
                retryable=app_error.retryable,
                proposal=["委譲先の可用性または認証を確認してください。"],
                audit=AuditPayload(
                    target={"service": "a2a", "peer_agent": selected.agent_id},
                    input_summary={"requested_operation": requested_operation},
                    decision_reason=["委譲実行失敗"],
                    result="error",
                    correlation_id=correlation_id,
                    peer_agent=selected.agent_id,
                    delegation_outcome="failed",
                ),
            )

        response = self._normalized_from_dict(remote_response)
        response.audit.correlation_id = correlation_id
        response.audit.peer_agent = selected.agent_id
        response.audit.delegation_outcome = (
            "partial_success" if response.status == "partial_success" else "delegated_success"
        )
        return response

    def _build_supported_operations(self) -> set[str]:
        supported = set(self.skill_executor.handlers.keys())
        supported.add("delegate_to_peer")
        return supported

    @staticmethod
    def _build_capability_skills(operations: list[str]) -> list[A2ACapabilitySkill]:
        operation_set = set(operations)
        skill_catalog: list[tuple[str, str, set[str]]] = [
            (
                "identity_user_group_ops",
                "Identity Domains のユーザー/グループ運用（一覧・詳細・作成・所属変更）",
                {
                    "list_users",
                    "get_user",
                    "create_user",
                    "list_groups",
                    "get_group",
                    "add_user_to_group",
                    "remove_user_from_group",
                },
            ),
            (
                "permission_investigation",
                "ユーザー権限の調査（所属グループ・関連ポリシー・実効操作の把握）",
                {"list_users", "get_user", "list_groups", "list_policies", "get_policy", "get_last_successful_login"},
            ),
            (
                "resource_inventory",
                "OCIリソース参照（コンパートメント階層・リソース・ポリシーの把握）",
                {"list_compartments", "list_resources", "list_policies", "get_policy"},
            ),
            (
                "credential_audit",
                "認証情報監査（資格情報一覧・最終ログイン確認）",
                {"list_user_credentials", "get_last_successful_login"},
            ),
            (
                "hr_assisted_resolution",
                "HRデータベース補完によるユーザー特定/不足情報補完",
                {"query_hr_database", "create_user", "add_user_to_group", "remove_user_from_group"},
            ),
        ]

        skills: list[A2ACapabilitySkill] = []
        for skill_name, description, required_ops in skill_catalog:
            covered = sorted(operation_set.intersection(required_ops))
            if not covered:
                continue
            skills.append(
                A2ACapabilitySkill(
                    skill_name=skill_name,
                    description=description,
                    related_operations=covered,
                )
            )
        return skills

    def _build_validation_error(self, *, payload: dict[str, Any], violations: list[str]) -> NormalizedResponse:
        missing_inputs = [item for item in violations if item not in {"hop_count_exceeded", "loop_detected"}]
        if "hop_count_exceeded" in violations:
            message = f"hop_count が上限 {self.settings.a2a_max_hops} を超えています。"
            code = "invalid_argument"
        elif "loop_detected" in violations:
            message = "循環委譲を検知したため処理を停止しました。"
            code = "loop_detected"
        elif "idempotency_key" in violations:
            message = "高リスク操作には idempotency_key が必須です。"
            code = "missing_input"
        else:
            message = f"必須入力が不足しています: {', '.join(missing_inputs)}"
            code = "missing_input"

        return NormalizedResponse.error(
            message=(
                f"{message} "
                f"/ 影響: A2A 実行を継続できません。"
                f" / 次アクション: 不足項目を指定して再実行してください。"
            ),
            code=code,
            retryable=False,
            proposal=["不足項目と hop_count / visited_agents を確認して再実行してください。"],
            meta={"missing_inputs": missing_inputs},
            audit=AuditPayload(
                target={"service": "a2a"},
                input_summary={"payload_keys": sorted(payload.keys())},
                decision_reason=["A2A入力検証エラー"],
                result="error",
                delegation_outcome="validation_error",
            ),
        )

    def _ensure_loop_protection(self, request: A2AExecutionRequest) -> None:
        if request.hop_count > self.settings.a2a_max_hops:
            raise InvalidArgumentError(f"hop_count が上限を超えています: {request.hop_count}")
        if self.settings.a2a_agent_id in request.visited_agents:
            raise LoopDetectedError("visited_agents に自エージェントが含まれています。")

    def _build_request_fingerprint(self, request: A2AExecutionRequest) -> str:
        payload = {
            "source_agent_id": request.source_agent_id,
            "target_agent_id": request.target_agent_id,
            "requested_operation": request.requested_operation,
            "objective": request.objective,
            "input_payload": request.input_payload,
            "constraints": request.constraints,
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _handle_idempotency_replay_if_needed(self, request: A2AExecutionRequest) -> NormalizedResponse | None:
        if request.requested_operation not in HIGH_RISK_TOOLS:
            return None
        idem_key = request.idempotency_key.strip()
        if not idem_key:
            raise InvalidArgumentError("高リスク操作には idempotency_key が必要です。")
        fingerprint = self._build_request_fingerprint(request)
        existing = self._idempotency_records.get(idem_key)
        if existing is None:
            return None
        record, saved_response = existing
        if record.request_fingerprint != fingerprint:
            raise IdempotencyConflictError("同一 idempotency_key で内容が異なる要求が検出されました。")
        replay = NormalizedResponse(
            status=saved_response.status,
            facts=list(saved_response.facts) + ["同一 idempotency_key のため前回結果を返却しました。"],
            interpretation=list(saved_response.interpretation),
            proposal=list(saved_response.proposal),
            data=saved_response.data.copy() if isinstance(saved_response.data, dict) else saved_response.data,
            meta=saved_response.meta.copy() if isinstance(saved_response.meta, dict) else saved_response.meta,
            errors=saved_response.errors,
            audit=AuditPayload(
                target=saved_response.audit.target,
                input_summary=saved_response.audit.input_summary,
                decision_reason=list(saved_response.audit.decision_reason) + ["idempotency replay"],
                result=saved_response.audit.result,
                correlation_id=request.correlation_id,
                peer_agent=request.source_agent_id,
                delegation_outcome="idempotency_replay",
            ),
        )
        return replay

    def _save_idempotency_record_if_needed(self, *, request: A2AExecutionRequest, response: NormalizedResponse) -> None:
        if request.requested_operation not in HIGH_RISK_TOOLS:
            return
        idem_key = request.idempotency_key.strip()
        if not idem_key:
            return
        fingerprint = self._build_request_fingerprint(request)
        record = A2AIdempotencyRecord(
            idempotency_key=idem_key,
            request_fingerprint=fingerprint,
            final_status=(
                "success"
                if response.status == "success"
                else "partial_success"
                if response.status == "partial_success"
                else "error"
            ),
            response_reference=request.request_id,
        )
        self._idempotency_records[idem_key] = (record, response)

    def _response_from_skill_result(
        self,
        *,
        request: A2AExecutionRequest,
        result: SkillExecutionResult,
        step: A2AExecutionStep,
    ) -> NormalizedResponse:
        step.finished_at = datetime.now(timezone.utc)
        step.errors = [result.error_message] if result.error_message else []
        step.facts = [f"tool={result.tool_name}", f"status={result.status}"]
        if result.status == "success":
            step.status = "success"
        elif result.status == "needs_confirmation":
            step.status = "partial_success"
        else:
            step.status = "failed"

        execution_result = A2AExecutionResult(
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            overall_status=(
                "success"
                if result.status == "success"
                else "needs_confirmation"
                if result.status == "needs_confirmation"
                else "error"
            ),
            facts=[f"A2A依頼を処理しました: {request.requested_operation}"],
            interpretation=["既存ツール契約に従って実行しました。"],
            proposal=["必要に応じて追加入力を指定して再実行してください。"],
            steps=[step],
        )

        if result.status == "success":
            return NormalizedResponse.success(
                facts=execution_result.facts,
                interpretation=execution_result.interpretation,
                proposal=execution_result.proposal,
                data={
                    "request_id": request.request_id,
                    "correlation_id": request.correlation_id,
                    "operation": request.requested_operation,
                    "result": result.normalized_data,
                    "a2a_execution": asdict(execution_result),
                },
                meta={"status": "success", "request_id": request.request_id, "correlation_id": request.correlation_id},
                audit=AuditPayload(
                    target={"service": "a2a", "operation": request.requested_operation},
                    input_summary={"request_id": request.request_id},
                    decision_reason=["A2A受信要求をローカル実行"],
                    result="success",
                    correlation_id=request.correlation_id,
                    peer_agent=request.source_agent_id,
                    delegation_outcome="handled_locally",
                ),
            )

        if result.status == "needs_confirmation":
            return NormalizedResponse.partial_success(
                facts=execution_result.facts,
                interpretation=["実行は完了しましたが追加確認が必要です。"],
                proposal=["不足情報を指定して再実行してください。"],
                data={
                    "request_id": request.request_id,
                    "correlation_id": request.correlation_id,
                    "operation": request.requested_operation,
                    "result": result.normalized_data,
                    "a2a_execution": asdict(execution_result),
                },
                meta={
                    "status": "partial_success",
                    "request_id": request.request_id,
                    "correlation_id": request.correlation_id,
                },
                audit=AuditPayload(
                    target={"service": "a2a", "operation": request.requested_operation},
                    input_summary={"request_id": request.request_id},
                    decision_reason=["A2A受信要求をローカル実行", "追加確認が必要"],
                    result="partial_success",
                    correlation_id=request.correlation_id,
                    peer_agent=request.source_agent_id,
                    delegation_outcome="handled_locally_partial",
                ),
            )

        return NormalizedResponse.error(
            message=result.error_message or "A2A実行中にエラーが発生しました。",
            code=result.error_code or "execution_error",
            retryable=bool(result.retryable),
            proposal=["入力情報と権限を確認して再実行してください。"],
            meta={"request_id": request.request_id, "correlation_id": request.correlation_id},
            audit=AuditPayload(
                target={"service": "a2a", "operation": request.requested_operation},
                input_summary={"request_id": request.request_id},
                decision_reason=["A2A受信要求の実行失敗"],
                result="error",
                correlation_id=request.correlation_id,
                peer_agent=request.source_agent_id,
                delegation_outcome="handled_locally_error",
            ),
        )

    def _record_audit(self, *, request: A2AExecutionRequest, response: NormalizedResponse, delegation_outcome: str) -> None:
        audit_record = A2AAuditRecord(
            actor=request.source_agent_id,
            target={"operation": request.requested_operation, "target_agent_id": request.target_agent_id},
            timestamp=datetime.now(timezone.utc),
            request_summary={
                "request_id": request.request_id,
                "objective": request.objective,
                "hop_count": request.hop_count,
            },
            decision_reason=list(response.audit.decision_reason),
            result=response.status,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
        )
        self.audit_logger.record_workflow(
            request_id=request.request_id,
            turn_id=request.request_id,
            workflow_name="a2a_execute",
            execution_order=1,
            target={
                "actor": audit_record.actor,
                "operation": request.requested_operation,
                "target_agent_id": request.target_agent_id,
            },
            input_summary=audit_record.request_summary,
            decision_reason=audit_record.decision_reason,
            result=response.status,
            compatibility_status="additive_layer",
            trace_id=str((response.meta or {}).get("trace_id") if isinstance(response.meta, dict) else ""),
            telemetry_delivery_status=str((response.meta or {}).get("telemetry_delivery_status") if isinstance(response.meta, dict) else ""),
            telemetry_delivery_reason=str((response.meta or {}).get("telemetry_delivery_reason") if isinstance(response.meta, dict) else ""),
            correlation_id=request.correlation_id,
            peer_agent=request.source_agent_id,
            delegation_outcome=delegation_outcome,
        )

    def _error_response(
        self,
        *,
        code: str,
        message: str,
        proposal: list[str],
        request_payload: dict[str, Any],
        correlation_id: str = "",
        peer_agent: str = "",
        delegation_outcome: str = "",
        retryable: bool = False,
    ) -> NormalizedResponse:
        return NormalizedResponse.error(
            message=message,
            code=code,
            retryable=retryable,
            proposal=proposal,
            meta={"missing_inputs": []},
            audit=AuditPayload(
                target={"service": "a2a"},
                input_summary={"payload_keys": sorted(request_payload.keys())},
                decision_reason=["A2A要求処理失敗"],
                result="error",
                correlation_id=correlation_id,
                peer_agent=peer_agent,
                delegation_outcome=delegation_outcome,
            ),
        )

    @staticmethod
    def _error_payload(*, code: str, facts: list[str], interpretation: list[str], proposal: list[str]) -> dict[str, Any]:
        return {
            "error_code": code,
            "facts": facts,
            "interpretation": interpretation,
            "proposal": proposal,
            "meta": {"generated_at": _utc_now_iso()},
        }

    def _normalized_from_dict(self, payload: dict[str, Any]) -> NormalizedResponse:
        status = str(payload.get("status") or "error")
        facts = [str(item) for item in payload.get("facts", [])]
        interpretation = [str(item) for item in payload.get("interpretation", [])]
        proposal = [str(item) for item in payload.get("proposal", [])]
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        audit = AuditPayload(
            target={"service": "a2a"},
            input_summary={},
            decision_reason=["委譲先応答を受領"],
            result=status,
        )
        if status == "success":
            return NormalizedResponse.success(
                facts=facts,
                interpretation=interpretation,
                proposal=proposal,
                data=data,
                meta=meta,
                audit=audit,
            )
        if status in {"partial_success", "needs_confirmation"}:
            return NormalizedResponse.partial_success(
                facts=facts,
                interpretation=interpretation,
                proposal=proposal,
                data=data,
                meta=meta,
                audit=audit,
            )
        error_code = str(payload.get("error_code") or "delegation_failed")
        error_message = " / ".join(interpretation) if interpretation else "委譲先でエラーが発生しました。"
        return NormalizedResponse.error(
            message=error_message,
            code=error_code,
            retryable=False,
            proposal=proposal or ["委譲先設定を確認して再実行してください。"],
            meta=meta,
            audit=audit,
        )
