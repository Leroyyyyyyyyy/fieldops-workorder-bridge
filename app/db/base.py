from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base. All ORM models inherit from this so that a single
    `Base.metadata` describes the whole schema for Alembic autogenerate."""
