from sqlalchemy.exc import IntegrityError

# PostgreSQL SQLSTATE for unique_violation.
UNIQUE_VIOLATION = "23505"


def unique_violation_constraint(exc: IntegrityError) -> str | None:
    """Name of the violated unique constraint, or None if that is not the cause.

    Letting the database enforce uniqueness is the only race-free option — a
    "does it already exist?" SELECT before the INSERT can always be overtaken by
    a concurrent request. That means the duplicate arrives as an `IntegrityError`
    after the fact, and the handler has to identify *which* constraint failed
    before deciding it is a duplicate rather than some other integrity problem.

    SQLSTATE 23505 is standard; the constraint name comes from the asyncpg
    exception wrapped inside SQLAlchemy's DBAPI error.
    """
    orig = exc.orig
    if orig is None or getattr(orig, "sqlstate", None) != UNIQUE_VIOLATION:
        return None
    constraint = getattr(orig.__cause__, "constraint_name", None)
    return constraint if isinstance(constraint, str) else None
