from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    retryable: bool = False
    layer: str = "tool"
    origin_name: str = ""

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class MissingCredentialError(AppError):
    def __init__(self, missing_items: list[str]):
        super().__init__(
            code="missing_credential",
            message=f"不足している資格情報: {', '.join(missing_items)}",
            retryable=False,
        )
        self.missing_items = missing_items


class MissingInputError(AppError):
    def __init__(self, message: str):
        super().__init__(code="missing_input", message=message, retryable=False)


class InvalidArgumentError(AppError):
    def __init__(self, message: str):
        super().__init__(code="invalid_argument", message=message, retryable=False)


class PermissionDeniedError(AppError):
    def __init__(self, message: str):
        super().__init__(code="permission_denied", message=message, retryable=False)


class InvalidFilterError(AppError):
    def __init__(self, message: str):
        super().__init__(code="invalid_filter", message=message, retryable=False)


class AmbiguousTargetError(AppError):
    def __init__(self, message: str):
        super().__init__(code="ambiguous_target", message=message, retryable=False)


class TemporaryUpstreamFailure(AppError):
    def __init__(self, message: str):
        super().__init__(code="temporary_upstream_failure", message=message, retryable=True)


class TransientFailureError(AppError):
    def __init__(self, message: str):
        super().__init__(code="transient_failure", message=message, retryable=True)


class SourceUnavailableError(AppError):
    def __init__(self, message: str):
        super().__init__(code="source_unavailable", message=message, retryable=True)


class BindingInvalidError(AppError):
    def __init__(self, message: str):
        super().__init__(code="binding_invalid", message=message, retryable=False)


class TelemetryDeliveryError(AppError):
    def __init__(self, message: str):
        super().__init__(code="telemetry_delivery_failed", message=message, retryable=True)


class SemanticValidationError(AppError):
    def __init__(self, message: str):
        super().__init__(code="semantic_validation_error", message=message, retryable=True)


class PeerUntrustedError(AppError):
    def __init__(self, message: str):
        super().__init__(code="peer_untrusted", message=message, retryable=False)


class LoopDetectedError(AppError):
    def __init__(self, message: str):
        super().__init__(code="loop_detected", message=message, retryable=False)


class IdempotencyConflictError(AppError):
    def __init__(self, message: str):
        super().__init__(code="idempotency_conflict", message=message, retryable=False)


class DelegationTimeoutError(AppError):
    def __init__(self, message: str):
        super().__init__(code="delegation_timeout", message=message, retryable=True)


def classify_exception(exc: Exception) -> AppError:
    if isinstance(exc, AppError):
        return exc
    message = str(exc)
    lowered = message.lower()
    if "missing_input" in lowered or "missing input" in lowered or "required input" in lowered:
        return MissingInputError(message)
    if "invalid argument" in lowered or "invalid_parameter" in lowered:
        return InvalidArgumentError(message)
    if (
        "permission" in lowered
        or "forbidden" in lowered
        or "notauthorized" in lowered
        or "not authorized" in lowered
        or "authorization failed" in lowered
    ):
        return PermissionDeniedError(message)
    if "filter" in lowered and "invalid" in lowered:
        return InvalidFilterError(message)
    if "binding_invalid" in lowered:
        return BindingInvalidError(message)
    if "peer_untrusted" in lowered or "untrusted peer" in lowered:
        return PeerUntrustedError(message)
    if "loop_detected" in lowered or "loop detected" in lowered or "circular delegation" in lowered:
        return LoopDetectedError(message)
    if "idempotency_conflict" in lowered or "idempotency conflict" in lowered:
        return IdempotencyConflictError(message)
    if "delegation_timeout" in lowered or "delegation timeout" in lowered:
        return DelegationTimeoutError(message)
    if "telemetry" in lowered and "failed" in lowered:
        return TelemetryDeliveryError(message)
    if (
        "unavailable" in lowered
        or "could not resolve" in lowered
        or "connection refused" in lowered
        or "host unreachable" in lowered
    ):
        return SourceUnavailableError(message)
    if "timeout" in lowered or "temporar" in lowered or "try again" in lowered:
        return TransientFailureError(message)
    return AppError(code="execution_error", message=message, retryable=False)
