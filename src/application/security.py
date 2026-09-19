"""Shared redaction for persisted provider, job, and operator-visible data."""

from collections.abc import Mapping, Sequence
from typing import Any

from src.platform_kernel import DomainValidationError

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "token",
    }
)
_SENSITIVE_SUFFIXES = ("_cookie", "_credential", "_password", "_secret", "_token")
_REDACTED = "[REDACTED]"


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def sanitize_sensitive(value: Any) -> Any:
    """Recursively redact values whose keys look credential-bearing."""
    if isinstance(value, Mapping):
        return {
            str(key): (_REDACTED if _is_sensitive_key(key) else sanitize_sensitive(item))
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_sensitive(item) for item in value]
    return value


def sanitize_error(error: BaseException) -> str:
    """Persist an error class without potentially credential-bearing details."""
    if isinstance(error, DomainValidationError):
        return str(error)
    return type(error).__name__
