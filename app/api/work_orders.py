from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.errors import foreign_key_violation_constraint
from app.db.session import get_session
from app.domain.work_order_status import Command, InvalidTransition, WorkOrderStatus, next_status
from app.models.work_order import WorkOrder
from app.schemas.work_order import (
    AssignRequest,
    CancelRequest,
    CompleteRequest,
    WorkOrderCreate,
    WorkOrderRead,
)

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
    return await _get_or_404(session, work_order_id)


async def _get_or_404(session: AsyncSession, work_order_id: UUID) -> WorkOrder:
    work_order = await session.get(WorkOrder, work_order_id)
    if work_order is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="WORK_ORDER_NOT_FOUND",
            message=f"No work order with id {work_order_id}.",
        )
    return work_order


def _apply(work_order: WorkOrder, command: Command) -> None:
    """Move the work order, or reject the command as an illegal transition.

    The rules live in the domain module, so this only translates a refusal into
    the HTTP contract. `version` counts changes and is incremented here, once per
    successful command.
    """
    try:
        target = next_status(command, WorkOrderStatus(work_order.status))
    except InvalidTransition as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="INVALID_STATE_TRANSITION",
            message=str(exc),
        ) from exc
    work_order.status = target
    work_order.version += 1


@router.post("/{work_order_id}/assign", response_model=WorkOrderRead)
async def assign_work_order(
    work_order_id: UUID, payload: AssignRequest, session: SessionDep
) -> WorkOrder:
    """NEW -> ASSIGNED."""
    work_order = await _get_or_404(session, work_order_id)
    _apply(work_order, Command.ASSIGN)
    work_order.assignee_id = payload.assignee_id
    await session.flush()
    return work_order


@router.post("/{work_order_id}/start", response_model=WorkOrderRead)
async def start_work_order(work_order_id: UUID, session: SessionDep) -> WorkOrder:
    """ASSIGNED -> IN_PROGRESS. Carries no body: starting work adds no new facts."""
    work_order = await _get_or_404(session, work_order_id)
    _apply(work_order, Command.START)
    await session.flush()
    return work_order


@router.post("/{work_order_id}/complete", response_model=WorkOrderRead)
async def complete_work_order(
    work_order_id: UUID, payload: CompleteRequest, session: SessionDep
) -> WorkOrder:
    """IN_PROGRESS -> COMPLETED. A resolution is required."""
    work_order = await _get_or_404(session, work_order_id)
    _apply(work_order, Command.COMPLETE)
    work_order.resolution = payload.resolution
    await session.flush()
    return work_order


@router.post("/{work_order_id}/cancel", response_model=WorkOrderRead)
async def cancel_work_order(
    work_order_id: UUID, payload: CancelRequest, session: SessionDep
) -> WorkOrder:
    """NEW / ASSIGNED / IN_PROGRESS -> CANCELLED. A reason is required."""
    work_order = await _get_or_404(session, work_order_id)
    _apply(work_order, Command.CANCEL)
    work_order.cancellation_reason = payload.reason
    await session.flush()
    return work_order
