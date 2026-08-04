import uuid

from sqlalchemy import ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class WorkOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A unit of maintenance work raised against an asset.

    `status` starts at NEW and is only ever changed through the explicit command
    endpoints, so it has no setter in the create schema. `version` exists for the
    optimistic concurrency checks that the command endpoints will need; nothing
    increments it yet.
    """

    __tablename__ = "work_orders"

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
