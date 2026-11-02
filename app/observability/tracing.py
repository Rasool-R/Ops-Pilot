"""LangSmith trace correlation and safe observability metadata."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import Settings, get_settings


def utc_now() -> datetime:
    """Return current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def new_trace_id() -> str:
    """Generate a unique UUID4 string for trace correlation."""
    return str(uuid4())


class TraceContext(BaseModel):
    """Correlated trace metadata linking LangSmith runs to OpsPilot incidents."""

    trace_id: str = Field(default_factory=new_trace_id)
    incident_id: str
    alert_fingerprint: str
    service_id: str
    project_name: str
    environment: str
    tracing_enabled: bool
    started_at_utc: datetime = Field(default_factory=utc_now)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str | int | bool] = Field(default_factory=dict)


def create_trace_context(
    incident_id: str,
    alert_fingerprint: str,
    service_id: str,
    step_limit: int | None = None,
    settings: Settings | None = None,
) -> TraceContext:
    """Build a safe, secret-free trace context correlated to an incident lifecycle."""
    cfg = settings or get_settings()
    api_key_val = cfg.LANGCHAIN_API_KEY.get_secret_value()
    is_configured = (
        cfg.LANGCHAIN_TRACING_V2
        and bool(api_key_val)
        and api_key_val != "unconfigured"
    )
    bound_steps = step_limit if step_limit is not None else cfg.GRAPH_MAX_STEPS

    return TraceContext(
        incident_id=incident_id,
        alert_fingerprint=alert_fingerprint,
        service_id=service_id,
        project_name=cfg.LANGCHAIN_PROJECT,
        environment=cfg.APP_ENV,
        tracing_enabled=is_configured,
        tags=[
            f"env:{cfg.APP_ENV}",
            f"service:{service_id}",
            "component:investigation_graph",
        ],
        metadata={
            "incident_id": incident_id,
            "alert_fingerprint": alert_fingerprint,
            "service_id": service_id,
            "graph_max_steps": bound_steps,
            "use_mock_telemetry": cfg.USE_MOCK_TELEMETRY,
        },
    )