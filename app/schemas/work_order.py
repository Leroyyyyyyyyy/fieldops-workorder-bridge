from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Priority = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class WorkOrderCreate(BaseModel):
    """The client-supplied half of a work order.

    `status` and `version` are absent on purpose: a work order always starts at
    NEW, and status only ever changes through the explicit command endpoints. If
    a caller could set it here, the state machine would have a way around itself.
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
    priority: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
