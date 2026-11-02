"""Bounded log collection tool with prompt-injection and credential redaction."""

import re

from app.db.models import ServiceId
from app.integrations.telemetry import (
    LogEntry,
    LogQueryRequest,
    LogQueryResponse,
    MockTelemetryAdapter,
    TelemetryAdapter,
)

MAX_LOG_MESSAGE_CHARS = 500

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+authorized", re.IGNORECASE),
    re.compile(r"bypass\s+policy", re.IGNORECASE),
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(password|passwd|secret|api_key|token)\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE),
)


def sanitize_log_message(raw_message: str) -> str:
    """Redact credentials and neutralize prompt-injection attempts in untrusted logs."""
    cleaned = raw_message
    for secret_pat in _SECRET_PATTERNS:
        cleaned = secret_pat.sub("[REDACTED_CREDENTIAL]", cleaned)

    for inj_pat in _INJECTION_PATTERNS:
        cleaned = inj_pat.sub("[REDACTED_UNTRUSTED_INSTRUCTION]", cleaned)

    if len(cleaned) > MAX_LOG_MESSAGE_CHARS:
        return cleaned[:MAX_LOG_MESSAGE_CHARS] + "...[TRUNCATED]"
    return cleaned


def query_service_logs(
    service_id: ServiceId,
    limit: int = 20,
    adapter: TelemetryAdapter | None = None,
) -> LogQueryResponse:
    """Retrieve bounded service logs and sanitize all entries before LLM consumption."""
    request = LogQueryRequest(service_id=service_id, limit=limit)
    active_adapter = adapter or MockTelemetryAdapter()
    raw_response = active_adapter.query_logs(request)

    sanitized_entries = [
        LogEntry(
            timestamp_utc=entry.timestamp_utc,
            level=entry.level,
            service=entry.service,
            message=sanitize_log_message(entry.message),
        )
        for entry in raw_response.logs
    ]

    return LogQueryResponse(
        source=raw_response.source,
        service_id=raw_response.service_id,
        collected_at_utc=raw_response.collected_at_utc,
        truncated=raw_response.truncated,
        logs=sanitized_entries,
        error=raw_response.error,
    )