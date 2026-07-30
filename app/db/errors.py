from sqlalchemy.exc import IntegrityError

# PostgreSQL SQLSTATEs.
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"


def _violated_constraint(exc: IntegrityError, sqlstate: str) -> str | None:
    """Name of the constraint behind `exc`, if it failed with `sqlstate`.

    Letting the database enforce a constraint is the only race-free option — a
    "does it already exist?" or "does the asset exist?" SELECT before the INSERT
    can always be overtaken by a concurrent request. That means the violation
    arrives as an `IntegrityError` after the fact, and the handler has to identify
    *which* constraint failed before deciding what it means to the client.

    The SQLSTATEs are standard; the constraint name comes from the asyncpg
    exception wrapped inside SQLAlchemy's DBAPI error.
    """
    orig = exc.orig
    if orig is None or getattr(orig, "sqlstate", None) != sqlstate:
        return None
    constraint = getattr(orig.__cause__, "constraint_name", None)
    return constraint if isinstance(constraint, str) else None


def unique_violation_constraint(exc: IntegrityError) -> str | None:
    """Name of the violated unique constraint, or None if that is not the cause."""
    return _violated_constraint(exc, UNIQUE_VIOLATION)


def foreign_key_violation_constraint(exc: IntegrityError) -> str | None:
    """Name of the violated foreign key, or None if that is not the cause."""
    return _violated_constraint(exc, FOREIGN_KEY_VIOLATION)
