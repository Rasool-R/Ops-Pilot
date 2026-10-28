"""Application configuration management and validation."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, bounded application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- Application Core ---
    APP_NAME: str = "OpsPilot"
    APP_ENV: Literal["development", "testing", "staging", "production"] = "development"
    APP_HOST: str = "0.0.0.0"  # noqa: S104
    APP_PORT: int = Field(default=8000, ge=1, le=65535)
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    API_V1_STR: str = "/api/v1"

    # --- PostgreSQL Persistence ---
    DATABASE_URL: SecretStr = Field(
        default=SecretStr(
            "postgresql+psycopg://opspilot_user:local_dev_password@localhost:5432/opspilot_db"
        ),
        description="SQLAlchemy PostgreSQL connection URI (masked in logs).",
    )
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=50)
    DB_POOL_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=60)

    # --- AI & LangGraph Bounded Execution ---
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: SecretStr = Field(default=SecretStr("unconfigured"))
    LLM_TIMEOUT_SECONDS: int = Field(default=30, ge=1, le=120)
    LLM_MAX_RETRIES: int = Field(default=2, ge=0, le=5)
    GRAPH_MAX_STEPS: int = Field(default=10, ge=1, le=25)

    # --- LangSmith Tracing ---
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_API_KEY: SecretStr = Field(default=SecretStr("unconfigured"))
    LANGCHAIN_PROJECT: str = "opspilot-dev"

    # --- Bounded Telemetry Contracts ---
    PROMETHEUS_BASE_URL: str = "http://localhost:9090"
    ALERTMANAGER_BASE_URL: str = "http://localhost:9093"
    LOG_BACKEND_BASE_URL: str = "http://localhost:3100"
    TELEMETRY_TIMEOUT_SECONDS: int = Field(default=5, ge=1, le=30)
    TELEMETRY_MAX_PAYLOAD_BYTES: int = Field(default=65536, ge=1024, le=524288)
    USE_MOCK_TELEMETRY: bool = True

    # --- Remediation & Security Policy ---
    REMEDIATION_DRY_RUN_ONLY: bool = True
    APPROVAL_EXPIRY_MINUTES: int = Field(default=30, ge=5, le=240)
    WEBHOOK_SHARED_SECRET: SecretStr = Field(default=SecretStr("unconfigured"))


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()