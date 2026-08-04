from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import RequestModel


class AssetCreate(RequestModel):
    """The client-supplied half of an asset.

    Deliberately excludes `id`, `status` and the timestamps: those are owned by
    the server, so accepting them from a request would let a caller invent them.
    """

    external_id: str = Field(min_length=1, max_length=100)
    site: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    asset_type: str = Field(min_length=1, max_length=50)


class AssetRead(BaseModel):
    """What the API returns. Built from the ORM object via `from_attributes`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_id: str
    site: str
    name: str
    asset_type: str
    status: str
    created_at: datetime
    updated_at: datetime
