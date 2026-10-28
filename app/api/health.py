"""Health and readiness endpoints for service and infrastructure monitoring."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import __version__
from app.config import Settings, get_settings
from app.db.session import check_db_connectivity, get_db

router = APIRouter(tags=["health"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[Session, Depends(get_db)]


class LivenessResponse(BaseModel):
    """Schema for application liveness response."""

    status: Literal["ok"]
    service: str
    environment: str
    version: str


class ReadinessResponse(BaseModel):
    """Schema for application and database readiness response."""

    status: Literal["ready", "degraded"]
    database: str
    use_mock_telemetry: bool
    remediation_dry_run_only: bool


@router.get("/health", response_model=LivenessResponse, status_code=status.HTTP_200_OK)
def health_liveness(settings: SettingsDep) -> LivenessResponse:
    """Verify that the FastAPI application process is alive."""
    return LivenessResponse(
        status="ok",
        service=settings.APP_NAME,
        environment=settings.APP_ENV,
        version=__version__,
    )


@router.get("/health/ready", response_model=ReadinessResponse)
def health_readiness(
    response: Response,
    db: DbSessionDep,
    settings: SettingsDep,
) -> ReadinessResponse:
    """Verify that the application can communicate with PostgreSQL."""
    db_ok, db_detail = check_db_connectivity(db)
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="degraded",
            database=db_detail,
            use_mock_telemetry=settings.USE_MOCK_TELEMETRY,
            remediation_dry_run_only=settings.REMEDIATION_DRY_RUN_ONLY,
        )

    response.status_code = status.HTTP_200_OK
    return ReadinessResponse(
        status="ready",
        database="ok",
        use_mock_telemetry=settings.USE_MOCK_TELEMETRY,
        remediation_dry_run_only=settings.REMEDIATION_DRY_RUN_ONLY,
    )