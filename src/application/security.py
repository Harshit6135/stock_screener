"""Shared redaction for persisted provider, job, and operator-visible data."""

import logging
import re
import traceback
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
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key)).lower().replace("-", "_")
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
    return sanitize_text(value) if isinstance(value, str) else value


def sanitize_error(error: BaseException) -> str:
    """Persist an error class without potentially credential-bearing details."""
    if isinstance(error, DomainValidationError):
        return sanitize_text(str(error))
    return type(error).__name__


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:[a-z0-9_-]*[_-](?:cookie|credential|password|secret|token)|"
    r"api[_-]?key|authorization|cookie|credential|password|secret|token)"
    r"[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|(?:Bearer\s+|token\s+)?[^\s,;&}\]]+)"
)


def sanitize_text(value: str) -> str:
    """Redact credential assignments embedded in messages and provider URLs."""
    return _SECRET_ASSIGNMENT.sub(lambda match: match.group(1) + _REDACTED, value)


class RedactingLogFilter(logging.Filter):
    """Sanitize rendered messages and tracebacks at the application handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize_text(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = sanitize_text("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = sanitize_text(record.exc_text)
        return True
