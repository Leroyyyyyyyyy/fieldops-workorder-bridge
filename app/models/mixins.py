import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    """UUID primary key generated in the database (gen_random_uuid)."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())


class TimestampMixin:
    """created_at / updated_at maintained by the database, in UTC.

    `eager_defaults` makes SQLAlchemy fetch these back with `RETURNING` on UPDATE
    as well as INSERT. Without it, `updated_at` is merely marked expired after a
    flush, and the next read of it attempts blocking IO — which under asyncio
    raises `MissingGreenlet` rather than quietly issuing a second query.
    """

    __mapper_args__ = {"eager_defaults": True}

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
