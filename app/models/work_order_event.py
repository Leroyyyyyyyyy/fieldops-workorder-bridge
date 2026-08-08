import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.work_order_status import EventSource, WorkOrderEventType, WorkOrderStatus
from app.models.mixins import UUIDPrimaryKeyMixin


def _in_list(column: str, values: type[StrEnum], *, nullable: bool = False) -> str:
    allowed = ", ".join(repr(str(value)) for value in values)
    check = f"{column} IN ({allowed})"
    return f"{column} IS NULL OR {check}" if nullable else check


class WorkOrderEvent(UUIDPrimaryKeyMixin, Base):
    """One row per change to a work order, written in the same transaction as it.

    Append-only: nothing updates or deletes these, which is why there is no
    `updated_at` and why the timestamp mixin is not used here. An audit row that
    can be edited is not evidence of anything.

    `work_order_version` is the version the change produced, and is what the
    history is ordered by. Ordering by `created_at` would be wrong: PostgreSQL's
    `now()` is the transaction start time, so two events written in one
    transaction carry identical timestamps and no tiebreaker. The version
    increments exactly once per change, so it orders the history exactly.
    """

    __tablename__ = "work_order_events"

    __table_args__ = (
        CheckConstraint(
            _in_list("event_type", WorkOrderEventType), name="ck_work_order_events_event_type"
        ),
        CheckConstraint(_in_list("source", EventSource), name="ck_work_order_events_source"),
        CheckConstraint(
            _in_list("old_status", WorkOrderStatus, nullable=True),
            name="ck_work_order_events_old_status",
        ),
        CheckConstraint(
            _in_list("new_status", WorkOrderStatus), name="ck_work_order_events_new_status"
        ),
    )

    work_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "work_orders.id", ondelete="RESTRICT", name="fk_work_order_events_work_order_id"
        ),
        index=True,
    )
    event_type: Mapped[str]
    # Null only for CREATE: before that event the work order had no status.
    old_status: Mapped[str | None]
    new_status: Mapped[str]
    work_order_version: Mapped[int]
    # Nullable until authentication exists; there is no users table to point at,
    # and inventing an actor would be worse than recording that we do not know.
    actor_id: Mapped[uuid.UUID | None]
    source: Mapped[str]
    # The command's free text: the reason for a cancellation, the resolution for a
    # completion. Null for commands that carry neither.
    reason: Mapped[str | None]
    # Filled by the correlation-ID middleware once it exists, so one request can be
    # followed from the log line to the row it wrote.
    correlation_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
