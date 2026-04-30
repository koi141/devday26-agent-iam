from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any
import uuid

from iam_agent.application.high_risk_guard import constrain_remediation_proposals
from iam_agent.application.permission_investigator import PermissionInvestigator
from iam_agent.domain.contracts import AuditPayload, NormalizedResponse
from iam_agent.domain.models import AccessDenialCase, RootCauseFinding


class AccessDiagnoser:
    def __init__(self, permission_investigator: PermissionInvestigator) -> None:
        self.permission_investigator = permission_investigator

    def diagnose(self, *, turn_id: str, user_input: str) -> NormalizedResponse:
        parsed = self._extract_case_inputs(user_input)
        missing = [key for key in ("user_hint", "target_resource", "requested_action") if not parsed.get(key)]
        if missing:
            return NormalizedResponse.needs_confirmation(
                facts=["アクセス拒否調査に必要な情報が不足しています。"],
                interpretation=[f"不足項目: {', '.join(missing)}"],
                proposal=["ユーザー・対象リソース・試行操作を含めて再入力してください。"],
                data={"missing_fields": missing},
                audit=AuditPayload(
                    target={"request_type": "access_denial_troubleshooting"},
                    input_summary={"turn_id": turn_id},
                    decision_reason=["必須情報不足"],
                    result="needs_confirmation",
                ),
            )

        permission_context = self.permission_investigator.investigate(turn_id=turn_id, user_input=user_input)
        if permission_context.status != "success":
            return permission_context

        ctx_data = permission_context.data or {}
        groups = ctx_data.get("group_names") if isinstance(ctx_data.get("group_names"), list) else []
        evidence = ctx_data.get("policy_evidence") if isinstance(ctx_data.get("policy_evidence"), list) else []

        case = AccessDenialCase(
            case_id=f"case-{uuid.uuid4()}",
            request_id=str(ctx_data.get("request_id") or f"request-{uuid.uuid4()}"),
            target_user_id=str(((ctx_data.get("user_resolution") or {}).get("selected_user") or {}).get("oci_user_id") or ""),
            target_resource=str(parsed.get("target_resource") or ""),
            requested_action=str(parsed.get("requested_action") or ""),
            reported_symptom=str(parsed.get("error_symptom") or "アクセス拒否"),
        )

        findings = self._analyze_root_causes(
            case=case,
            groups=[str(item) for item in groups],
            policy_evidence=[item for item in evidence if isinstance(item, dict)],
        )
        confirmed = [finding for finding in findings if finding.status == "confirmed"]
        hypotheses = [finding for finding in findings if finding.status == "hypothesis"]

        facts = [
            f"対象ユーザーID: {case.target_user_id or '未解決'}",
            f"対象リソース: {case.target_resource}",
            f"試行操作: {case.requested_action}",
            f"確認済み根拠: {len(confirmed)} 件、仮説: {len(hypotheses)} 件",
        ]
        interpretation = self._build_interpretation(findings)
        proposal = self._build_proposals(findings)
        proposal = constrain_remediation_proposals(proposal)

        return NormalizedResponse.success(
            facts=facts,
            interpretation=interpretation,
            proposal=proposal,
            data={
                "case": asdict(case),
                "findings": [asdict(finding) for finding in findings],
                "required_additional_inputs": self._collect_additional_inputs(findings),
            },
            audit=AuditPayload(
                target={"request_type": "access_denial_troubleshooting", "case_id": case.case_id},
                input_summary={"target_resource": case.target_resource, "requested_action": case.requested_action},
                decision_reason=["resolve_user", "collect_permission_evidence", "determine_root_cause", "produce_remediation"],
                result="success",
            ),
        )

    @staticmethod
    def _extract_case_inputs(user_input: str) -> dict[str, Any]:
        text = user_input.strip()
        payload: dict[str, Any] = {"user_hint": text if text else ""}
        lowered = text.lower()

        resource_match = re.search(r"[「\"']([^「」\"']{2,120})[」\"']", text)
        if resource_match:
            payload["target_resource"] = resource_match.group(1).strip()
        elif "autonomous database" in lowered:
            payload["target_resource"] = "Autonomous Database"
        elif "db" in lowered:
            payload["target_resource"] = "database"

        if "作成" in text or "create" in lowered:
            payload["requested_action"] = "create"
        elif "更新" in text or "update" in lowered:
            payload["requested_action"] = "update"
        elif "削除" in text or "delete" in lowered:
            payload["requested_action"] = "delete"
        elif "参照" in text or "read" in lowered or "アクセス" in text:
            payload["requested_action"] = "read"

        if "拒否" in text or "denied" in lowered or "not authorized" in lowered or "できない" in text:
            payload["error_symptom"] = "access_denied"
        return payload

    @staticmethod
    def _analyze_root_causes(
        *,
        case: AccessDenialCase,
        groups: list[str],
        policy_evidence: list[dict[str, Any]],
    ) -> list[RootCauseFinding]:
        findings: list[RootCauseFinding] = []
        if not groups:
            findings.append(
                RootCauseFinding(
                    case_id=case.case_id,
                    status="confirmed",
                    cause_category="group_mismatch",
                    description="対象ユーザーの所属グループが確認できません。",
                    evidence_links=["group_names"],
                    additional_inputs_required=[],
                )
            )

        action = case.requested_action.lower()
        matched_action_evidence = [
            item for item in policy_evidence if action in str(item.get("statement") or "").lower()
        ]
        if matched_action_evidence:
            constrained = [
                item for item in matched_action_evidence if "where " in str(item.get("statement") or "").lower()
            ]
            if constrained:
                findings.append(
                    RootCauseFinding(
                        case_id=case.case_id,
                        status="hypothesis",
                        cause_category="constraint_block",
                        description="一致するポリシーはありますが、条件式による制約で拒否されている可能性があります。",
                        evidence_links=[str(item.get("policy_id") or "") for item in constrained],
                        additional_inputs_required=["実行元ネットワーク情報", "対象リソースの完全修飾名"],
                    )
                )
            else:
                findings.append(
                    RootCauseFinding(
                        case_id=case.case_id,
                        status="hypothesis",
                        cause_category="permission_scope",
                        description="対象操作に近い権限は存在しますが、スコープ不一致の可能性があります。",
                        evidence_links=[str(item.get("policy_id") or "") for item in matched_action_evidence],
                        additional_inputs_required=["対象コンパートメント", "リソース存在場所"],
                    )
                )
        else:
            findings.append(
                RootCauseFinding(
                    case_id=case.case_id,
                    status="confirmed",
                    cause_category="missing_policy",
                    description="対象操作に対応するポリシー文が確認できませんでした。",
                    evidence_links=["policy_evidence"],
                    additional_inputs_required=[],
                )
            )

        return findings

    @staticmethod
    def _build_interpretation(findings: list[RootCauseFinding]) -> list[str]:
        lines: list[str] = []
        for finding in findings:
            prefix = "確定原因" if finding.status == "confirmed" else "仮説原因"
            lines.append(f"{prefix}: {finding.description}")
        if not lines:
            lines.append("原因を特定できませんでした。追加情報が必要です。")
        return lines

    @staticmethod
    def _build_proposals(findings: list[RootCauseFinding]) -> list[str]:
        proposals: list[str] = []
        for finding in findings:
            if finding.cause_category == "missing_policy":
                proposals.append("対象グループに必要な操作を許可するポリシー追加を検討してください。")
            elif finding.cause_category == "group_mismatch":
                proposals.append("対象ユーザーの所属グループを見直し、必要なグループに追加してください。")
            elif finding.cause_category == "constraint_block":
                proposals.append("実行元ネットワークや条件式に一致する実行条件かを確認してください。")
            elif finding.cause_category == "permission_scope":
                proposals.append("対象リソースのコンパートメントとポリシー適用範囲を照合してください。")
            if finding.additional_inputs_required:
                proposals.append("追加調査に必要な情報: " + ", ".join(finding.additional_inputs_required))
        return proposals or ["アクセス拒否時刻と対象操作を具体化して再調査してください。"]

    @staticmethod
    def _collect_additional_inputs(findings: list[RootCauseFinding]) -> list[str]:
        required: list[str] = []
        for finding in findings:
            for item in finding.additional_inputs_required:
                if item not in required:
                    required.append(item)
        return required
