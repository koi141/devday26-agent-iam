from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from iam_agent.config.settings import Settings

try:
    import oci
except Exception:  # pragma: no cover - optional in local unit tests
    oci = None


@dataclass(slots=True)
class OciAuthContext:
    config: dict[str, Any]
    signer: Any
    profile: str


class OciAuthResolver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve_workload_identity(self) -> OciAuthContext:
        if oci is None:
            raise RuntimeError("oci SDK がインストールされていません。")

        signer = None
        signer_errors: list[str] = []
        try:
            signer = oci.auth.signers.get_oke_workload_identity_resource_principal_signer()
        except Exception as exc:
            signer_errors.append(f"oke_workload_identity={type(exc).__name__}: {exc}")

        if signer is None:
            try:
                signer = oci.auth.signers.get_resource_principals_signer()
            except Exception as exc:
                signer_errors.append(f"resource_principals={type(exc).__name__}: {exc}")

        if signer is None:
            raise RuntimeError("Workload Identity signer を取得できませんでした: " + " / ".join(signer_errors))

        region = (
            getattr(signer, "region", None)
            or os.getenv("OCI_RESOURCE_PRINCIPAL_REGION")
            or os.getenv("OCI_REGION")
            or "ap-tokyo-1"
        )
        config = {"region": region}
        return OciAuthContext(config=config, signer=signer, profile="workload_identity")

    def resolve_local_profile(self) -> OciAuthContext:
        if oci is None:
            raise RuntimeError("oci SDK がインストールされていません。")

        profile = self.settings.oci_profile or "devdey-agent"
        config = oci.config.from_file(profile_name=profile)
        signer = None
        return OciAuthContext(config=config, signer=signer, profile=profile)
