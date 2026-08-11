"""The seed generator's correctness, checked on a small dataset.

Row counts are configurable so these run in a moment; what is being verified is
the shape of the data, which does not depend on how much of it there is.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.work_order_status import Priority, WorkOrderEventType, WorkOrderStatus
from app.models.asset import Asset
from app.models.work_order import WorkOrder
from app.models.work_order_event import WorkOrderEvent
from scripts.seed import seed

pytestmark = pytest.mark.integration

ASSETS = 40
WORK_ORDERS = 300


@pytest.fixture
async def seeded(db_session: AsyncSession) -> tuple[int, int, int]:
    return await seed(db_session, assets=ASSETS, work_orders=WORK_ORDERS)


async def test_writes_the_requested_number_of_rows(
    seeded: tuple[int, int, int], db_session: AsyncSession
) -> None:
    assert seeded[0] == ASSETS
    assert seeded[1] == WORK_ORDERS

    for model, expected in ((Asset, ASSETS), (WorkOrder, WORK_ORDERS)):
        stored = (await db_session.execute(select(func.count()).select_from(model))).scalar_one()
        assert stored == expected


async def test_every_work_order_has_a_complete_legal_history(db_session: AsyncSession) -> None:
    """The invariant the API guarantees must hold for generated data too, or the
    dataset everyone actually queries would contradict the system's main claim."""
    await seed(db_session, assets=ASSETS, work_orders=WORK_ORDERS)

    rows = (
        await db_session.execute(
            select(WorkOrder.id, WorkOrder.status, WorkOrder.version).order_by(WorkOrder.id)
        )
    ).all()
    events = (
        (
            await db_session.execute(
                select(WorkOrderEvent).order_by(
                    WorkOrderEvent.work_order_id, WorkOrderEvent.work_order_version
                )
            )
        )
        .scalars()
        .all()
    )

    by_work_order: dict[object, list[WorkOrderEvent]] = {}
    for event in events:
        by_work_order.setdefault(event.work_order_id, []).append(event)

    for work_order_id, status, version in rows:
        history = by_work_order.get(work_order_id, [])
        assert history, f"work order {work_order_id} has no history"
        # Starts at creation, and the chain is contiguous from version 1.
        assert history[0].event_type == WorkOrderEventType.CREATE
        assert history[0].old_status is None
        assert [event.work_order_version for event in history] == list(range(1, len(history) + 1))
        # Each event continues from where the previous one left off.
        for previous, current in zip(history, history[1:], strict=False):
            assert current.old_status == previous.new_status
        # And the row agrees with the end of its own history.
        assert history[-1].new_status == status
        assert history[-1].work_order_version == version


async def test_values_stay_inside_the_domain(
    seeded: tuple[int, int, int], db_session: AsyncSession
) -> None:
    statuses = set((await db_session.execute(select(WorkOrder.status).distinct())).scalars().all())
    priorities = set(
        (await db_session.execute(select(WorkOrder.priority).distinct())).scalars().all()
    )

    assert statuses <= {str(status) for status in WorkOrderStatus}
    assert priorities <= {str(priority) for priority in Priority}


async def test_the_distribution_is_skewed_not_uniform(
    seeded: tuple[int, int, int], db_session: AsyncSession
) -> None:
    """Uniform data produces query plans no real table would produce, which is the
    whole reason this generator exists."""
    completed = (
        await db_session.execute(
            select(func.count())
            .select_from(WorkOrder)
            .where(WorkOrder.status == WorkOrderStatus.COMPLETED)
        )
    ).scalar_one()
    assert completed > WORK_ORDERS * 0.5

    # A minority of the crew holds most of the work.
    per_technician = (
        (
            await db_session.execute(
                select(func.count())
                .select_from(WorkOrder)
                .where(WorkOrder.assignee_id.is_not(None))
                .group_by(WorkOrder.assignee_id)
                .order_by(func.count().desc())
            )
        )
        .scalars()
        .all()
    )
    assigned_total = sum(per_technician)
    busiest_quarter = per_technician[: max(1, len(per_technician) // 4)]
    assert sum(busiest_quarter) > assigned_total * 0.5


async def test_history_spans_many_months(
    seeded: tuple[int, int, int], db_session: AsyncSession
) -> None:
    oldest, newest = (
        await db_session.execute(
            select(func.min(WorkOrder.created_at), func.max(WorkOrder.created_at))
        )
    ).one()

    assert (newest - oldest).days > 300


async def test_seeding_twice_leaves_one_dataset(db_session: AsyncSession) -> None:
    """Re-running replaces rather than accumulates, and is deterministic."""
    await seed(db_session, assets=ASSETS, work_orders=WORK_ORDERS)
    first = (await db_session.execute(select(WorkOrder.id).order_by(WorkOrder.id))).scalars().all()

    await seed(db_session, assets=ASSETS, work_orders=WORK_ORDERS)
    second = (await db_session.execute(select(WorkOrder.id).order_by(WorkOrder.id))).scalars().all()

    assert len(second) == WORK_ORDERS
    assert first == second
