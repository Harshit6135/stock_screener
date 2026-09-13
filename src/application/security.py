"""Shared redaction for persisted provider, job, and operator-visible data."""

from collections.abc import Mapping, Sequence
from typing import Any

_SENSITIVE_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "token",
)
_REDACTED = "[REDACTED]"


def sanitize_sensitive(value: Any) -> Any:
    """Recursively redact values whose keys look credential-bearing."""
    if isinstance(value, Mapping):
        return {
            str(key): (
                _REDACTED
                if any(part in str(key).lower() for part in _SENSITIVE_PARTS)
                else sanitize_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_sensitive(item) for item in value]
    return value


def sanitize_error(error: BaseException) -> str:
    """Persist an error class without potentially credential-bearing details."""
    return type(error).__name__
