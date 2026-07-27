from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.errors import unique_violation_constraint
from app.db.session import get_session
from app.models.asset import Asset
from app.schemas.asset import AssetCreate, AssetRead

router = APIRouter(prefix="/assets", tags=["assets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# The unique index behind `Asset.external_id`, created by the baseline migration.
EXTERNAL_ID_UNIQUE_INDEX = "ix_assets_external_id"


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def create_asset(payload: AssetCreate, session: SessionDep) -> Asset:
    """Register an asset. `external_id` is the vendor's identifier and is unique."""
    asset = Asset(**payload.model_dump())
    session.add(asset)
    try:
        # Flush here so PostgreSQL assigns the id and timestamps and returns them
        # before the response is built. The commit happens afterwards, in the
        # session dependency; without this flush the response would carry a null id.
        await session.flush()
    except IntegrityError as exc:
        if unique_violation_constraint(exc) != EXTERNAL_ID_UNIQUE_INDEX:
            raise
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="DUPLICATE_EXTERNAL_ID",
            message=f"An asset with external_id {payload.external_id!r} already exists.",
        ) from exc
    return asset


@router.get("", response_model=list[AssetRead])
async def list_assets(session: SessionDep) -> Sequence[Asset]:
    """All assets, newest first. Pagination and filtering are not in this slice."""
    # id is a tiebreaker so rows created in the same transaction (identical
    # created_at) still come back in a stable order.
    result = await session.execute(select(Asset).order_by(Asset.created_at.desc(), Asset.id.desc()))
    return result.scalars().all()


@router.get("/{asset_id}", response_model=AssetRead)
async def get_asset(asset_id: UUID, session: SessionDep) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="ASSET_NOT_FOUND",
            message=f"No asset with id {asset_id}.",
        )
    return asset
