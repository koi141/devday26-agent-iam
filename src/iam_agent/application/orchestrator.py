from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from iam_agent.application.access_diagnoser import AccessDiagnoser
from iam_agent.application.input_guard import InputGuard
from iam_agent.application.permission_investigator import PermissionInvestigator
from iam_agent.application.retry_controller import RetryController
from iam_agent.application.skill_executor import SkillExecutor
from iam_agent.application.error_notifier import format_runtime_preflight_messages
from iam_agent.application.runtime_preflight import RuntimePreflightResult, summarize_runtime_preflight
from iam_agent.domain.contracts import AuditPayload, ErrorDetail, NormalizedResponse
from iam_agent.domain.models import ActionPlanStep, UserInputTurn
from iam_agent.infra.logging.audit_logger import AuditLogger
from iam_agent.application.action_planner import ActionPlanner
from iam_agent.application.response_summarizer import ResponseSummarizer
from iam_agent.application.semantic_validator import SemanticValidator
from iam_agent.observability.quality_evaluator import QualityEvaluator
from iam_agent.observability.snapshot_store import SnapshotStore
from iam_agent.observability.telemetry_bridge import TelemetryBridge
from iam_agent.observability.trace_context import TraceContext


class Orchestrator:
    def __init__(
        self,
        *,
        action_planner: ActionPlanner,
        input_guard: InputGuard,
        skill_executor: SkillExecutor,
        response_summarizer: ResponseSummarizer,
        semantic_validator: SemanticValidator,
        retry_controller: RetryController,
        audit_logger: AuditLogger,
        permission_investigator: PermissionInvestigator | None = None,
        access_diagnoser: AccessDiagnoser | None = None,
        a2a_service: Any | None = None,
        telemetry_bridge: TelemetryBridge | None = None,
        quality_evaluator: QualityEvaluator | None = None,
        snapshot_store: SnapshotStore | None = None,
        runtime_preflight_checker: Callable[[], RuntimePreflightResult] | None = None,
        migration_context: dict[str, str] | None = None,
    ) -> None:
        self.action_planner = action_planner
        self.input_guard = input_guard
        self.skill_executor = skill_executor
        self.response_summarizer = response_summarizer
        self.semantic_validator = semantic_validator
        self.retry_controller = retry_controller
        self.audit_logger = audit_logger
        self.permission_investigator = permission_investigator or PermissionInvestigator(skill_executor=skill_executor)
        self.access_diagnoser = access_diagnoser or AccessDiagnoser(self.permission_investigator)
        self.a2a_service = a2a_service
        self.telemetry_bridge = telemetry_bridge
        self.quality_evaluator = quality_evaluator or QualityEvaluator()
        self.snapshot_store = snapshot_store or SnapshotStore()
        self.runtime_preflight_checker = runtime_preflight_checker
        self.migration_context = migration_context or {}
        if self.a2a_service is not None and hasattr(self.a2a_service, "bind_orchestrator"):
            try:
                self.a2a_service.bind_orchestrator(self)
            except Exception:
                pass

    def get_a2a_capabilities(self, *, source_agent_id: str = "", auth_token: str = "") -> dict[str, Any]:
        if self.a2a_service is None:
            return {
                "error_code": "a2a_disabled",
                "facts": ["A2A 機能は有効化されていません。"],
                "interpretation": ["A2Aサービスが初期化されていないため能力照会を実行できません。"],
                "proposal": ["a2a_enabled と peer設定を確認してください。"],
            }
        return self.a2a_service.capabilities(source_agent_id=source_agent_id, auth_token=auth_token)

    def handle_a2a_request(self, *, payload: dict[str, Any], auth_token: str = "") -> NormalizedResponse:
        if self.a2a_service is None:
            return NormalizedResponse.error(
                message="A2A サービスが無効です。",
                code="a2a_disabled",
                retryable=False,
                proposal=["a2a_enabled と peer設定を確認してください。"],
                audit=AuditPayload(
                    target={"service": "a2a"},
                    input_summary={"payload_keys": sorted(payload.keys())},
                    decision_reason=["A2A サービス未初期化"],
                    result="error",
                ),
            )
        response = self.a2a_service.execute(payload=payload, auth_token=auth_token)
        correlation_id = str(payload.get("correlation_id") or "")
        peer_agent = str(payload.get("source_agent_id") or "")
        if not response.audit.correlation_id:
            response.audit.correlation_id = correlation_id
        if not response.audit.peer_agent:
            response.audit.peer_agent = peer_agent
        if not response.audit.delegation_outcome:
            response.audit.delegation_outcome = "a2a_execute"
        meta = response.meta.copy() if isinstance(response.meta, dict) else {}
        meta.setdefault("compatibility_status", "additive_layer")
        meta.setdefault(
            "compatibility",
            {"single_tool_contract_preserved": True, "additive_layer_active": True},
        )
        response.meta = meta
        return response

    def _missing_input_response(self, turn_id: str, step: ActionPlanStep, missing: list[str]) -> NormalizedResponse:
        missing_request = self.input_guard.build_missing_input_request(turn_id=turn_id, step=step, missing=missing)
        return NormalizedResponse.needs_confirmation(
            facts=["入力が不足しているため処理を停止しました。"],
            interpretation=missing_request.why_needed,
            proposal=[missing_request.prompt_to_user],
            data=asdict(missing_request),
            audit=AuditPayload(
                target={"tool": step.tool_name},
                input_summary={"provided_inputs": step.provided_inputs},
                decision_reason=["必須入力不足"],
                result="needs_confirmation",
            ),
        )

    def _start_trace(self, *, turn_id: str, user_input: str) -> TraceContext | None:
        if self.telemetry_bridge is None:
            return None
        return self.telemetry_bridge.start_trace(
            turn_id=turn_id,
            request_type="unknown",
            user_prompt_summary=user_input[:500],
        )

    def _add_prompt_observation(self, trace: TraceContext | None, *, operation: str, model_name: str, input_summary: str, output_summary: str) -> None:
        if trace is None:
            return
        trace.add_prompt_observation(
            operation=operation,
            model_name=model_name,
            input_summary=input_summary[:500],
            output_summary=output_summary[:1000],
            duration_ms=0,
        )

    def _finalize_trace(
        self,
        *,
        trace: TraceContext | None,
        response: NormalizedResponse,
        validation_status: str,
        missing_input_detected: bool,
        compatibility_status: str,
    ) -> dict[str, Any]:
        if trace is None or self.telemetry_bridge is None:
            return {
                "trace_id": "",
                "telemetry_delivery_status": "disabled",
                "telemetry_delivery_reason": "telemetry_bridge_unset",
                "quality_score": {},
            }

        score = self.quality_evaluator.evaluate(
            validation_status=validation_status,
            retry_count=self.retry_controller.attempt_count,
            response_status=response.status,
            missing_input_detected=missing_input_detected,
        )
        delivery = self.telemetry_bridge.finish_trace(
            trace,
            status=response.status,
            quality_score=score.to_dict(),
            compatibility_status=compatibility_status,
            correlation_id=str(response.audit.correlation_id or ""),
            peer_agent=str(response.audit.peer_agent or ""),
            delegation_outcome=str(response.audit.delegation_outcome or ""),
        )

        latency_ms = 0
        if trace.finished_at is not None:
            latency_ms = max(int((trace.finished_at - trace.started_at).total_seconds() * 1000), 0)

        self.snapshot_store.add_metric(
            scope=trace.request_type or compatibility_status,
            status=response.status,
            latency_ms=latency_ms,
            retry_count=self.retry_controller.attempt_count,
            error_class=(response.errors[0].code if response.errors else ""),
        )

        return {
            "trace_id": delivery.trace_id,
            "telemetry_delivery_status": delivery.status,
            "telemetry_delivery_reason": delivery.reason,
            "quality_score": score.to_dict(),
            "comparison_scope": trace.request_type or compatibility_status,
        }

    @staticmethod
    def _attach_meta(response: NormalizedResponse, *, trace_meta: dict[str, Any], compatibility_status: str) -> None:
        existing = response.meta.copy() if isinstance(response.meta, dict) else {}
        existing.update(trace_meta)
        existing["compatibility_status"] = compatibility_status
        existing["compatibility"] = {
            "single_tool_contract_preserved": compatibility_status == "single_tool_passthrough",
            "additive_layer_active": compatibility_status != "single_tool_passthrough",
        }
        response.meta = existing

    def _record_workflow_audit(
        self,
        *,
        turn_id: str,
        workflow_name: str,
        skill_name: str,
        response: NormalizedResponse,
        compatibility_status: str,
        trace_meta: dict[str, Any],
    ) -> None:
        self.audit_logger.record_workflow(
            request_id=f"workflow-{turn_id}",
            turn_id=turn_id,
            workflow_name=workflow_name,
            skill_name=skill_name,
            execution_order=1,
            target=response.audit.target,
            input_summary=response.audit.input_summary,
            decision_reason=response.audit.decision_reason,
            result=response.status,
            retryable=False,
            compatibility_status=compatibility_status,
            trace_id=str(trace_meta.get("trace_id") or ""),
            telemetry_delivery_status=str(trace_meta.get("telemetry_delivery_status") or ""),
            telemetry_delivery_reason=str(trace_meta.get("telemetry_delivery_reason") or ""),
            correlation_id=str(response.audit.correlation_id or ""),
            peer_agent=str(response.audit.peer_agent or ""),
            delegation_outcome=str(response.audit.delegation_outcome or ""),
            context_name=str(self.migration_context.get("context_name") or ""),
            namespace=str(self.migration_context.get("namespace") or ""),
            ingress_host=str(self.migration_context.get("ingress_host") or ""),
        )

    def _runtime_preflight_guard(self, *, turn_id: str) -> NormalizedResponse | None:
        if self.runtime_preflight_checker is None:
            return None

        result = self.runtime_preflight_checker()
        blocking = result.blocking_issues()
        if not blocking:
            return None

        facts, interpretation, proposal = format_runtime_preflight_messages(blocking)
        return NormalizedResponse(
            status="error",
            facts=facts,
            interpretation=interpretation,
            proposal=proposal,
            data=summarize_runtime_preflight(result),
            meta={
                "missing_items": [issue.target for issue in blocking],
                "impact_scope": [issue.impact for issue in blocking],
                "next_action": [issue.required_action for issue in blocking],
            },
            errors=[
                ErrorDetail(
                    code="runtime_config_invalid",
                    message="起動前設定検証で不足または不整合を検出しました。",
                    retryable=False,
                )
            ],
            audit=AuditPayload(
                target={"phase": "runtime_preflight"},
                input_summary={"turn_id": turn_id},
                decision_reason=[f"{issue.category}:{issue.target}" for issue in blocking],
                result="error",
            ),
        )

    def handle_user_input(self, turn_id: str, user_input: str) -> NormalizedResponse:
        turn = UserInputTurn(turn_id=turn_id, user_input=user_input)
        self.retry_controller.reset()
        trace = self._start_trace(turn_id=turn.turn_id, user_input=turn.user_input)

        preflight_block = self._runtime_preflight_guard(turn_id=turn.turn_id)
        if preflight_block is not None:
            trace_meta = self._finalize_trace(
                trace=trace,
                response=preflight_block,
                validation_status="not_aligned",
                missing_input_detected=True,
                compatibility_status="single_tool_passthrough",
            )
            self._attach_meta(preflight_block, trace_meta=trace_meta, compatibility_status="single_tool_passthrough")
            return preflight_block

        planning_span = ""
        if trace and self.telemetry_bridge:
            planning_span = self.telemetry_bridge.start_stage(trace, stage="action_planning", attempt=1)

        plan = self.action_planner.create_plan(turn_id=turn.turn_id, user_input=turn.user_input)
        if trace:
            trace.request_type = plan.request_type
            ordered = ", ".join(step.tool_name for step in plan.ordered_steps())
            self._add_prompt_observation(
                trace,
                operation="action_planner",
                model_name=plan.planned_by_model or "heuristic",
                input_summary=turn.user_input,
                output_summary=ordered,
            )
            if planning_span and self.telemetry_bridge:
                self.telemetry_bridge.end_stage(trace, span_id=planning_span, status="success")

        if plan.request_type == "permission_investigation":
            workflow_span = ""
            if trace and self.telemetry_bridge:
                workflow_span = self.telemetry_bridge.start_stage(trace, stage="tool_execution", attempt=1)
            skill_name = plan.skill_name or "user_permission_investigation"
            response = self.skill_executor.execute_skill(
                skill_name,
                turn_id=turn.turn_id,
                user_input=turn.user_input,
            )
            if response.status == "error" and self.permission_investigator is not None:
                response = self.permission_investigator.investigate(turn_id=turn.turn_id, user_input=turn.user_input)
            if workflow_span and trace and self.telemetry_bridge:
                self.telemetry_bridge.end_stage(trace, span_id=workflow_span, status=response.status)
            trace_meta = self._finalize_trace(
                trace=trace,
                response=response,
                validation_status="aligned" if response.status == "success" else "not_aligned",
                missing_input_detected=(response.status == "needs_confirmation"),
                compatibility_status="additive_layer",
            )
            self._attach_meta(response, trace_meta=trace_meta, compatibility_status="additive_layer")
            self._record_workflow_audit(
                turn_id=turn.turn_id,
                workflow_name="permission_investigation",
                skill_name=skill_name,
                response=response,
                compatibility_status="additive_layer",
                trace_meta=trace_meta,
            )
            return response

        if plan.request_type == "access_denial_troubleshooting":
            workflow_span = ""
            if trace and self.telemetry_bridge:
                workflow_span = self.telemetry_bridge.start_stage(trace, stage="tool_execution", attempt=1)
            response = self.access_diagnoser.diagnose(turn_id=turn.turn_id, user_input=turn.user_input)
            if workflow_span and trace and self.telemetry_bridge:
                self.telemetry_bridge.end_stage(trace, span_id=workflow_span, status=response.status)
            trace_meta = self._finalize_trace(
                trace=trace,
                response=response,
                validation_status="aligned" if response.status == "success" else "not_aligned",
                missing_input_detected=(response.status == "needs_confirmation"),
                compatibility_status="additive_layer",
            )
            self._attach_meta(response, trace_meta=trace_meta, compatibility_status="additive_layer")
            self._record_workflow_audit(
                turn_id=turn.turn_id,
                workflow_name="access_denial_troubleshooting",
                skill_name=plan.skill_name or "access_denial_troubleshooting",
                response=response,
                compatibility_status="additive_layer",
                trace_meta=trace_meta,
            )
            return response

        while True:
            attempt = self.retry_controller.attempt_count + 1
            if attempt > 1:
                if trace and self.telemetry_bridge:
                    replanning_span = self.telemetry_bridge.start_stage(trace, stage="action_planning", attempt=attempt)
                plan = self.action_planner.create_plan(turn_id=turn.turn_id, user_input=turn.user_input)
                if trace:
                    ordered = ", ".join(step.tool_name for step in plan.ordered_steps())
                    self._add_prompt_observation(
                        trace,
                        operation="action_planner",
                        model_name=plan.planned_by_model or "heuristic",
                        input_summary=turn.user_input,
                        output_summary=ordered,
                    )
                if trace and self.telemetry_bridge:
                    self.telemetry_bridge.end_stage(trace, span_id=replanning_span, status="success")
            results = []
            compatibility_status = "single_tool_passthrough"
            ordered_steps = plan.ordered_steps()
            if any(step.tool_name == "delegate_to_peer" for step in ordered_steps):
                compatibility_status = "additive_layer"

            for step in ordered_steps:
                missing = self.input_guard.find_missing_inputs(step)
                if missing:
                    response = self._missing_input_response(turn.turn_id, step, missing)
                    trace_meta = self._finalize_trace(
                        trace=trace,
                        response=response,
                        validation_status="not_aligned",
                        missing_input_detected=True,
                        compatibility_status=compatibility_status,
                    )
                    self._attach_meta(response, trace_meta=trace_meta, compatibility_status=compatibility_status)
                    return response

                tool_span = ""
                if trace and self.telemetry_bridge:
                    tool_span = self.telemetry_bridge.start_stage(trace, stage="tool_execution", attempt=attempt)

                result = self.skill_executor.execute(step.tool_name, step.provided_inputs)
                results.append(result)

                if trace:
                    trace.add_tool_observation(
                        tool_name=step.tool_name,
                        auth_route=result.auth_route or self.skill_executor.auth_route_for(step.tool_name),
                        input_summary=step.provided_inputs,
                        result_status=result.status,
                        duration_ms=result.duration_ms,
                        oci_request_id=result.oci_request_id,
                    )

                if trace and self.telemetry_bridge and tool_span:
                    self.telemetry_bridge.end_stage(
                        trace,
                        span_id=tool_span,
                        status=result.status,
                        error_class=result.error_code,
                    )

                if result.status == "needs_confirmation":
                    response = NormalizedResponse.needs_confirmation(
                        facts=["確認が必要なため処理を停止しました。"],
                        interpretation=[result.error_message or "対象の一意特定が必要です。"],
                        proposal=["対象を1件に絞って再実行してください。"],
                        data={"tool": step.tool_name, "result": result.normalized_data},
                        audit=AuditPayload(
                            target={"tool": step.tool_name},
                            input_summary={"provided_inputs": step.provided_inputs},
                            decision_reason=["needs_confirmation を受領"],
                            result="needs_confirmation",
                        ),
                    )
                    trace_meta = self._finalize_trace(
                        trace=trace,
                        response=response,
                        validation_status="not_aligned",
                        missing_input_detected=True,
                        compatibility_status=compatibility_status,
                    )
                    self._attach_meta(response, trace_meta=trace_meta, compatibility_status=compatibility_status)
                    return response

            summarize_span = ""
            if trace and self.telemetry_bridge:
                summarize_span = self.telemetry_bridge.start_stage(trace, stage="response_summarization", attempt=attempt)
            draft = self.response_summarizer.summarize(
                turn_id=turn.turn_id,
                user_input=turn.user_input,
                attempt=attempt,
                results=results,
            )
            if trace:
                self._add_prompt_observation(
                    trace,
                    operation="response_summarizer",
                    model_name=draft.generated_by_model or "genai",
                    input_summary=turn.user_input,
                    output_summary=" / ".join(draft.facts[:2] + draft.interpretation[:2]),
                )
            if summarize_span and trace and self.telemetry_bridge:
                self.telemetry_bridge.end_stage(trace, span_id=summarize_span, status="success")

            semantic_span = ""
            if trace and self.telemetry_bridge:
                semantic_span = self.telemetry_bridge.start_stage(trace, stage="semantic_validation", attempt=attempt)
            validation = self.semantic_validator.validate(
                turn_id=turn.turn_id,
                attempt=attempt,
                user_input=turn.user_input,
                draft=draft,
            )
            if trace:
                self._add_prompt_observation(
                    trace,
                    operation="semantic_validator",
                    model_name=validation.checked_by_model or "genai",
                    input_summary=turn.user_input,
                    output_summary=", ".join(validation.reason[:2]) or validation.status,
                )
            if semantic_span and trace and self.telemetry_bridge:
                self.telemetry_bridge.end_stage(
                    trace,
                    span_id=semantic_span,
                    status="success",
                )

            next_action = self.retry_controller.register(validation.status)

            if next_action == "respond":
                final_span = ""
                if trace and self.telemetry_bridge:
                    final_span = self.telemetry_bridge.start_stage(trace, stage="final_response", attempt=attempt)
                response = self.response_summarizer.to_normalized_response(draft, results)
                if final_span and trace and self.telemetry_bridge:
                    self.telemetry_bridge.end_stage(trace, span_id=final_span, status=response.status)

                trace_meta = self._finalize_trace(
                    trace=trace,
                    response=response,
                    validation_status=validation.status,
                    missing_input_detected=False,
                    compatibility_status=compatibility_status,
                )
                self._attach_meta(response, trace_meta=trace_meta, compatibility_status=compatibility_status)
                self.audit_logger.record(
                    event=self._build_orchestration_event(
                        turn_id=turn.turn_id,
                        response=response,
                        trace_meta=trace_meta,
                        compatibility_status=compatibility_status,
                    )
                )
                return response

            if next_action == "abort":
                response = NormalizedResponse.error(
                    message="回答作成を3回試行しましたが、入力意図に対応する回答を生成できませんでした。",
                    code="MAX_RETRY_EXCEEDED",
                    retryable=False,
                    proposal=["入力条件を具体化して再実行してください。"],
                    audit=AuditPayload(
                        target={"turn_id": turn.turn_id},
                        input_summary={"attempts": self.retry_controller.attempt_count},
                        decision_reason=validation.reason,
                        result="error",
                    ),
                )
                trace_meta = self._finalize_trace(
                    trace=trace,
                    response=response,
                    validation_status=validation.status,
                    missing_input_detected=False,
                    compatibility_status=compatibility_status,
                )
                self._attach_meta(response, trace_meta=trace_meta, compatibility_status=compatibility_status)
                return response

    def _build_orchestration_event(
        self,
        turn_id: str,
        response: NormalizedResponse,
        trace_meta: dict[str, Any],
        compatibility_status: str,
    ):
        from iam_agent.domain.models import AuditLogEvent

        return AuditLogEvent(
            request_id=f"orchestrator-{turn_id}",
            turn_id=turn_id,
            tool_name="orchestrator",
            target=response.audit.target or {"turn_id": turn_id},
            input_summary={
                **(response.audit.input_summary or {}),
                "status": response.status,
            },
            decision_reason=response.audit.decision_reason,
            result=response.status,
            retryable=False,
            correlation_id=str(response.audit.correlation_id or ""),
            peer_agent=str(response.audit.peer_agent or ""),
            delegation_outcome=str(response.audit.delegation_outcome or ""),
            trace_id=str(trace_meta.get("trace_id") or ""),
            compatibility_status=compatibility_status,
            telemetry_delivery_status=str(trace_meta.get("telemetry_delivery_status") or ""),
            telemetry_delivery_reason=str(trace_meta.get("telemetry_delivery_reason") or ""),
        )
