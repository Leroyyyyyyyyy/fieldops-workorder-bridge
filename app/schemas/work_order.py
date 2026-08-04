from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import RequestModel

Priority = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class WorkOrderCreate(RequestModel):
    """The client-supplied half of a work order.

    `status` and `version` are absent on purpose: a work order always starts at
    NEW, and status only ever changes through the explicit command endpoints. If
    a caller could set it here, the state machine would have a way around itself.
    Supplying them is rejected rather than ignored — see `RequestModel`.
    """

    asset_id: UUID
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: Priority


class WorkOrderRead(BaseModel):
    """What the API returns. Built from the ORM object via `from_attributes`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    title: str
    description: str | None
    # `str`, not `Priority`: the database has no CHECK constraint yet, so a row
    # written by a seed script or a manual fix could hold a value outside the
    # literal set. Reads must surface such a row, not fail on it.
    priority: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
