"""Structured JSON logging with credential and secret redaction."""

import json
import logging
import re
from datetime import UTC, datetime

_LOG_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(password|passwd|secret|api_key|token)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"postgresql\+psycopg://[^:]+:[^@]+@", re.IGNORECASE),
)


def redact_sensitive_text(raw_text: str) -> str:
    """Scrub credentials, bearer tokens, and DB connection passwords from log text."""
    cleaned = raw_text
    for pattern in _LOG_SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED_SECRET]", cleaned)
    return cleaned


def build_structured_log_entry(
    level: str,
    event: str,
    message: str,
    incident_id: str | None = None,
    service_id: str | None = None,
) -> dict[str, str | None]:
    """Create a secret-scrubbed structured log dictionary ready for JSON serialization."""
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "level": level.upper(),
        "event": redact_sensitive_text(event),
        "message": redact_sensitive_text(message),
        "incident_id": incident_id,
        "service_id": service_id,
    }


class RedactingJsonFormatter(logging.Formatter):
    """Logging formatter emitting single-line JSON with automatic secret redaction."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a sanitized JSON string."""
        payload = build_structured_log_entry(
            level=record.levelname,
            event=record.name,
            message=record.getMessage(),
        )
        return json.dumps(payload, ensure_ascii=False)