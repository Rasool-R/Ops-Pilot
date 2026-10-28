"""SQLAlchemy declarative base for OpsPilot persistence models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all PostgreSQL ORM entities."""

    pass