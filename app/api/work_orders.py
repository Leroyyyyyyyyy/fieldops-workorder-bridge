from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.errors import foreign_key_violation_constraint
from app.db.session import get_session
from app.models.work_order import WorkOrder
from app.schemas.work_order import WorkOrderCreate, WorkOrderRead

router = APIRouter(prefix="/work-orders", tags=["work-orders"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# The foreign key from work_orders.asset_id to assets.id, named in the model so
# this constant matches a name we chose rather than one PostgreSQL generated.
ASSET_FOREIGN_KEY = "fk_work_orders_asset_id_assets"


@router.post("", response_model=WorkOrderRead, status_code=status.HTTP_201_CREATED)
async def create_work_order(payload: WorkOrderCreate, session: SessionDep) -> WorkOrder:
    """Raise a work order against an asset. It always starts at status NEW."""
    work_order = WorkOrder(**payload.model_dump())
    session.add(work_order)
    try:
        # Flush so PostgreSQL assigns the id, status, version and timestamps and
        # returns them before the response is built. The commit happens afterwards,
        # in the session dependency.
        await session.flush()
    except IntegrityError as exc:
        if foreign_key_violation_constraint(exc) != ASSET_FOREIGN_KEY:
            raise
        # The asset the caller named does not exist. That is a bad reference in
        # the request, not a server fault, so it is a 404 rather than a 500.
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="ASSET_NOT_FOUND",
            message=f"No asset with id {payload.asset_id}.",
        ) from exc
    return work_order


@router.get("/{work_order_id}", response_model=WorkOrderRead)
async def get_work_order(work_order_id: UUID, session: SessionDep) -> WorkOrder:
    work_order = await session.get(WorkOrder, work_order_id)
    if work_order is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="WORK_ORDER_NOT_FOUND",
            message=f"No work order with id {work_order_id}.",
        )
    return work_order
