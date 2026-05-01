from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
from typing import Any

from iam_agent.config.runtime_contract import (
    EXPECTED_GENAI_PROJECT_ID,
    EXPECTED_GENAI_PROJECT_NAME,
    EXPECTED_INGRESS_HOST,
    EXPECTED_NAMESPACE,
    REQUIRED_RUNTIME_SOURCES,
)
from iam_agent.config.settings import Settings
from iam_agent.domain.models import (
    DeploymentTarget,
    GenAIProjectBinding,
    RuntimeConfigSnapshot,
    RuntimePreflightResult,
    ValidationIssue,
)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _env_bool(name: str) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return False
    return raw in {"1", "true", "yes", "on", "enabled"}


def _issue(
    *,
    seq: int,
    category: str,
    target: str,
    impact: str,
    required_action: str,
    blocking: bool = True,
) -> ValidationIssue:
    return ValidationIssue(
        issue_id=f"issue-{seq:03d}",
        category=category,  # type: ignore[arg-type]
        target=target,
        impact=impact,
        required_action=required_action,
        blocking=blocking,
    )


class RuntimePreflight:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate(self) -> RuntimePreflightResult:
        target = DeploymentTarget(
            context_name=self.settings.runtime_context_name,
            namespace=self.settings.runtime_namespace,
            domain_host=self.settings.runtime_ingress_host,
            ingress_class="ic",
            certificate_ref="",
        )
        snapshot = RuntimeConfigSnapshot(
            resolved_keys=[],
            missing_keys=[],
            source_coverage={},
            dotenv_used=self._dotenv_used(),
        )
        issues: list[ValidationIssue] = []

        for source in REQUIRED_RUNTIME_SOURCES:
            source_name = str(source.get("source_name") or "")
            source_type = str(source.get("source_type") or "")
            source_label = f"{source_type}/{source_name}"
            required_entries = source.get("required_entries") or ()

            missing_entries: list[dict[str, Any]] = []
            resolved_count = 0

            for entry in required_entries:
                config_key = str(entry.get("config_key") or "")
                setting_attr = str(entry.get("setting_attr") or "")
                value = getattr(self.settings, setting_attr, "")
                if _is_missing(value):
                    missing_entries.append(entry)
                    snapshot.missing_keys.append(f"{source_name}.{config_key}")
                else:
                    resolved_count += 1
                    snapshot.resolved_keys.append(setting_attr)

            snapshot.source_coverage[source_label] = {
                "required": len(required_entries),
                "resolved": resolved_count,
                "missing": len(missing_entries),
            }

            if missing_entries and resolved_count == 0:
                issues.append(
                    _issue(
                        seq=len(issues) + 1,
                        category="missing_resource",
                        target=source_label,
                        impact=f"{source_name} を参照する機能が利用できません。",
                        required_action=f"{source_type} `{source_name}` を作成し、必須キーを設定してください。",
                    )
                )
                continue

            for missing in missing_entries:
                config_key = str(missing.get("config_key") or "")
                issues.append(
                    _issue(
                        seq=len(issues) + 1,
                        category="missing_key",
                        target=f"{source_label}:{config_key}",
                        impact=f"`{config_key}` を使う処理が停止します。",
                        required_action=f"`{source_name}` に `{config_key}` を追加してください。",
                    )
                )

        self._validate_fixed_values(issues)
        binding = self._build_binding(issues)

        return RuntimePreflightResult(
            target=target,
            snapshot=snapshot,
            issues=issues,
            binding=binding,
        )

    def _validate_fixed_values(self, issues: list[ValidationIssue]) -> None:
        if self.settings.runtime_namespace and self.settings.runtime_namespace != EXPECTED_NAMESPACE:
            issues.append(
                _issue(
                    seq=len(issues) + 1,
                    category="invalid_value",
                    target="runtime_namespace",
                    impact="誤った namespace へデプロイされる恐れがあります。",
                    required_action=f"`runtime_namespace` を `{EXPECTED_NAMESPACE}` に設定してください。",
                )
            )

        if self.settings.runtime_ingress_host and self.settings.runtime_ingress_host != EXPECTED_INGRESS_HOST:
            issues.append(
                _issue(
                    seq=len(issues) + 1,
                    category="invalid_value",
                    target="runtime_ingress_host",
                    impact="公開URLが契約値と不一致になります。",
                    required_action=f"`runtime_ingress_host` を `{EXPECTED_INGRESS_HOST}` に設定してください。",
                )
            )

        if self.settings.genai_project and self.settings.genai_project != EXPECTED_GENAI_PROJECT_NAME:
            issues.append(
                _issue(
                    seq=len(issues) + 1,
                    category="invalid_value",
                    target="genai_project",
                    impact="GenAI への接続先プロジェクトが不一致となります。",
                    required_action=f"`genai_project` を `{EXPECTED_GENAI_PROJECT_NAME}` に更新してください。",
                )
            )

        if self.settings.genai_project_id and self.settings.genai_project_id != EXPECTED_GENAI_PROJECT_ID:
            issues.append(
                _issue(
                    seq=len(issues) + 1,
                    category="invalid_value",
                    target="genai_project_id",
                    impact="GenAI への接続先プロジェクトIDが不一致となります。",
                    required_action=f"`genai_project_id` を `{EXPECTED_GENAI_PROJECT_ID}` に更新してください。",
                )
            )

        if bool(self.settings.genai_project) ^ bool(self.settings.genai_project_id):
            issues.append(
                _issue(
                    seq=len(issues) + 1,
                    category="inconsistent_pair",
                    target="genai_project+genai_project_id",
                    impact="GenAI プロジェクトの同定ができず推論処理を開始できません。",
                    required_action="`genai_project` と `genai_project_id` を両方設定してください。",
                )
            )

    def _build_binding(self, issues: list[ValidationIssue]) -> GenAIProjectBinding:
        status = "unknown"
        if self.settings.genai_project and self.settings.genai_project_id:
            if (
                self.settings.genai_project == EXPECTED_GENAI_PROJECT_NAME
                and self.settings.genai_project_id == EXPECTED_GENAI_PROJECT_ID
            ):
                status = "matched"
            else:
                status = "mismatched"
        return GenAIProjectBinding(
            project_name=self.settings.genai_project,
            project_id=self.settings.genai_project_id,
            base_url=self.settings.genai_baseurl,
            credential_source="oci-genai-key",
            consistency_status=status,  # type: ignore[arg-type]
        )

    @staticmethod
    def _dotenv_used() -> bool:
        env_file = Path(".env")
        if not env_file.exists():
            return False
        return _env_bool("ALLOW_DOTENV") or _env_bool("allow_dotenv")


def run_runtime_preflight(settings: Settings) -> RuntimePreflightResult:
    return RuntimePreflight(settings).validate()


def summarize_runtime_preflight(result: RuntimePreflightResult) -> dict[str, Any]:
    return {
        "target": asdict(result.target),
        "snapshot": asdict(result.snapshot),
        "issues": [asdict(issue) for issue in result.issues],
        "binding": asdict(result.binding) if result.binding else {},
        "ok": result.is_ok(),
    }
