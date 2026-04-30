from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


SENSITIVE_KEYS = {
    "password",
    "pass",
    "secret",
    "client_secret",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "privatekey",
    "private_key",
    "apikey",
    "api_key",
    "tls.key",
    "credential",
    "credentials",
    "auth",
    "authorization_header",
    "peer_auth_token",
    "id_token",
}


def _looks_sensitive(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in SENSITIVE_KEYS:
        return True
    return any(pattern in normalized for pattern in SENSITIVE_KEYS)


def redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if _looks_sensitive(key):
            redacted[key] = "***REDACTED***"
            continue
        redacted[key] = redact_value(value)
    return redacted


def redact_resource_summaries(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [redact_mapping(item) for item in items]


def redact_a2a_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return redact_mapping(payload)


def redact_for_telemetry(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    masked_fields: list[str] = []

    def _redact(obj: Any, prefix: str = "") -> Any:
        if isinstance(obj, Mapping):
            result: dict[str, Any] = {}
            for key, value in obj.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                if _looks_sensitive(str(key)):
                    result[str(key)] = "***REDACTED***"
                    masked_fields.append(path)
                else:
                    result[str(key)] = _redact(value, path)
            return result
        if isinstance(obj, list):
            return [_redact(item, f"{prefix}[]") for item in obj]
        return obj

    return _redact(payload), masked_fields


def redact_text(text: str) -> str:
    if not text:
        return text
    redacted = re.sub(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer ***REDACTED***", text)
    redacted = re.sub(r"(?i)(client_secret=)[^&\s]+", r"\1***REDACTED***", redacted)
    redacted = re.sub(r"(?i)(access_token=)[^&\s]+", r"\1***REDACTED***", redacted)
    return redacted
