from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.errors import foreign_key_violation_constraint
from app.db.session import get_session
from app.domain.work_order_status import (
    Command,
    EventSource,
    InvalidTransition,
    WorkOrderEventType,
    WorkOrderStatus,
    next_status,
)
from app.models.work_order import WorkOrder
from app.models.work_order_event import WorkOrderEvent
from app.schemas.work_order import (
    AssignRequest,
    CancelRequest,
    CompleteRequest,
    ReassignRequest,
    StartRequest,
    WorkOrderCreate,
    WorkOrderEventRead,
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
    # The work order's first moment belongs in its history too, so the event
    # stream is the whole life of the row rather than everything after it.
    _record(session, work_order, WorkOrderEventType.CREATE, old_status=None)
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


def _record(
    session: AsyncSession,
    work_order: WorkOrder,
    event_type: WorkOrderEventType,
    old_status: str | None,
    reason: str | None = None,
) -> None:
    """Append the audit row for a change that has just been made to `work_order`.

    Added to the same session as the change itself, so the two are one unit of
    work: the dependency commits both or rolls back both. There is no code path
    that writes a state change without coming through here.
    """
    session.add(
        WorkOrderEvent(
            work_order_id=work_order.id,
            event_type=event_type,
            old_status=old_status,
            new_status=work_order.status,
            work_order_version=work_order.version,
            # Both filled in by machinery that does not exist yet: authentication
            # knows the actor, the correlation-ID middleware knows the request.
            actor_id=None,
            source=EventSource.API,
            reason=reason,
            correlation_id=None,
        )
    )


def _apply(
    session: AsyncSession, work_order: WorkOrder, command: Command, reason: str | None = None
) -> None:
    """Move the work order and record it, or reject the command as illegal.

    The rules live in the domain module, so this only translates a refusal into
    the HTTP contract. `version` counts changes and is incremented here, once per
    successful command; the audit row records the version it produced.
    """
    old_status = work_order.status
    try:
        target = next_status(command, WorkOrderStatus(old_status))
    except InvalidTransition as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="INVALID_STATE_TRANSITION",
            message=str(exc),
        ) from exc
    work_order.status = target
    work_order.version += 1
    _record(session, work_order, WorkOrderEventType(command), old_status, reason)


@router.post("/{work_order_id}/assign", response_model=WorkOrderRead)
async def assign_work_order(
    work_order_id: UUID, payload: AssignRequest, session: SessionDep
) -> WorkOrder:
    """NEW -> ASSIGNED."""
    work_order = await _get_or_404(session, work_order_id)
    _apply(session, work_order, Command.ASSIGN)
    work_order.assignee_id = payload.assignee_id
    await session.flush()
    return work_order


@router.post("/{work_order_id}/reassign", response_model=WorkOrderRead)
async def reassign_work_order(
    work_order_id: UUID, payload: ReassignRequest, session: SessionDep
) -> WorkOrder:
    """ASSIGNED / IN_PROGRESS -> ASSIGNED, with a different assignee.

    Its own command rather than a second ASSIGN, so the audit trail records that
    the work changed hands instead of showing two identical events.
    """
    work_order = await _get_or_404(session, work_order_id)
    _apply(session, work_order, Command.REASSIGN)
    work_order.assignee_id = payload.assignee_id
    await session.flush()
    return work_order


@router.post("/{work_order_id}/start", response_model=WorkOrderRead)
async def start_work_order(
    work_order_id: UUID, payload: StartRequest, session: SessionDep
) -> WorkOrder:
    """ASSIGNED -> IN_PROGRESS. The body is empty; see `StartRequest` for why it exists."""
    work_order = await _get_or_404(session, work_order_id)
    _apply(session, work_order, Command.START)
    await session.flush()
    return work_order


@router.post("/{work_order_id}/complete", response_model=WorkOrderRead)
async def complete_work_order(
    work_order_id: UUID, payload: CompleteRequest, session: SessionDep
) -> WorkOrder:
    """IN_PROGRESS -> COMPLETED. A resolution is required."""
    work_order = await _get_or_404(session, work_order_id)
    _apply(session, work_order, Command.COMPLETE, payload.resolution)
    work_order.resolution = payload.resolution
    await session.flush()
    return work_order


@router.post("/{work_order_id}/cancel", response_model=WorkOrderRead)
async def cancel_work_order(
    work_order_id: UUID, payload: CancelRequest, session: SessionDep
) -> WorkOrder:
    """NEW / ASSIGNED / IN_PROGRESS -> CANCELLED. A reason is required."""
    work_order = await _get_or_404(session, work_order_id)
    _apply(session, work_order, Command.CANCEL, payload.reason)
    work_order.cancellation_reason = payload.reason
    await session.flush()
    return work_order


@router.get("/{work_order_id}/events", response_model=list[WorkOrderEventRead])
async def list_work_order_events(
    work_order_id: UUID, session: SessionDep
) -> Sequence[WorkOrderEvent]:
    """The work order's history, oldest first.

    Ordered by the version each change produced rather than by `created_at`:
    `now()` is the transaction start time, so events written in one transaction
    share a timestamp and could not be ordered by it.
    """
    await _get_or_404(session, work_order_id)
    result = await session.execute(
        select(WorkOrderEvent)
        .where(WorkOrderEvent.work_order_id == work_order_id)
        .order_by(WorkOrderEvent.work_order_version)
    )
    return result.scalars().all()
