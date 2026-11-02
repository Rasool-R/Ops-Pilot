"""Database engine, session management, and connectivity verification."""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


def build_engine(settings: Settings | None = None) -> Engine:
    """Create a configured SQLAlchemy engine without exposing credentials in logs."""
    cfg = settings or get_settings()
    return create_engine(
        cfg.DATABASE_URL.get_secret_value(),
        pool_pre_ping=True,
        pool_size=cfg.DB_POOL_SIZE,
        max_overflow=cfg.DB_MAX_OVERFLOW,
        pool_timeout=cfg.DB_POOL_TIMEOUT_SECONDS,
        future=True,
    )


engine: Engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a transactional database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connectivity(db: Session) -> tuple[bool, str]:
    """Execute a lightweight read-only probe to verify PostgreSQL connectivity."""
    try:
        db.execute(text("SELECT 1"))
        return True, "ok"
    except SQLAlchemyError as exc:
        return False, f"database_unreachable: {exc.__class__.__name__}"