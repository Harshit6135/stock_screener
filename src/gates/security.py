"""Logging filters configured at application startup."""

import logging
import traceback

from src.platform_kernel.security import sanitize_text


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
