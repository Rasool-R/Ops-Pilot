"""FastAPI application entrypoint for OpsPilot."""

from fastapi import FastAPI

from app import __version__
from app.api.health import router as health_router
from app.config import get_settings


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application instance."""
    settings = get_settings()
    application = FastAPI(
        title=settings.APP_NAME,
        version=__version__,
        description="Stateful Agentic AIOps Platform for RCA and Controlled Remediation",
    )
    application.include_router(health_router, prefix=settings.API_V1_STR)
    return application


app = create_app()