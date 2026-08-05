import uuid
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.work_order_status import Priority, WorkOrderStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


def _in_list(column: str, values: type[StrEnum]) -> str:
    """A CHECK expression built from the enum, so the two cannot drift apart.

    Note that Alembic's autogenerate does not compare CHECK constraints, so a
    change here still needs its own migration written by hand.
    """
    return f"{column} IN ({', '.join(repr(str(value)) for value in values)})"


class WorkOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A unit of maintenance work raised against an asset.

    `status` starts at NEW and is only ever changed through the explicit command
    endpoints, so it has no setter in the create schema. `version` counts changes
    and is incremented by each successful command; the stale-write check that
    reads it belongs with optimistic concurrency.

    `assignee_id` has no foreign key yet because there is no `users` table —
    authentication introduces one, and the constraint belongs with it.
    """

    __tablename__ = "work_orders"

    # The state machine is the only thing that may write `status`, but a CHECK
    # constraint keeps a seed script or a manual UPDATE from introducing a value
    # the application has never heard of. It constrains the value domain only;
    # which transitions are legal depends on the current row and the caller, so
    # that stays in the application.
    __table_args__ = (
        CheckConstraint(_in_list("status", WorkOrderStatus), name="ck_work_orders_status"),
        CheckConstraint(_in_list("priority", Priority), name="ck_work_orders_priority"),
    )

    # RESTRICT rather than CASCADE: an asset with history must not be deletable,
    # because deleting it would silently destroy the work order audit trail.
    # Named explicitly so the API layer matches a name we chose, rather than one
    # PostgreSQL invented; the name follows the convention the models will adopt.
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT", name="fk_work_orders_asset_id_assets"),
        index=True,
    )
    title: Mapped[str]
    description: Mapped[str | None]
    priority: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'NEW'"))
    version: Mapped[int] = mapped_column(server_default=text("1"))
    assignee_id: Mapped[uuid.UUID | None]
    # Required by their commands, so they are non-null exactly when the work order
    # reached the status that requires them; nothing else may write them.
    resolution: Mapped[str | None]
    cancellation_reason: Mapped[str | None]
