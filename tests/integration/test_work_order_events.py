from typing import Any
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_order import WorkOrder
from app.models.work_order_event import WorkOrderEvent
from tests.integration.work_order_helpers import (
    ASSIGNEE,
    REASON,
    RESOLUTION,
    advance_to,
    command,
    create_work_order,
)

pytestmark = pytest.mark.integration


async def history(client: AsyncClient, work_order_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/work-orders/{work_order_id}/events")
    assert response.status_code == 200
    events: list[dict[str, Any]] = response.json()
    return events


async def test_creating_a_work_order_records_its_first_event(client: AsyncClient) -> None:
    created = await create_work_order(client)

    events = await history(client, created["id"])

    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "CREATE"
    assert event["old_status"] is None
    assert event["new_status"] == "NEW"
    assert event["work_order_version"] == 1
    assert event["source"] == "API"
    # Both wait on machinery that does not exist yet.
    assert event["actor_id"] is None
    assert event["correlation_id"] is None


async def test_history_is_ordered_and_complete(client: AsyncClient) -> None:
    """Every change appears exactly once, oldest first."""
    work_order = await create_work_order(client)
    work_order_id = work_order["id"]
    await command(client, work_order_id, "assign", {"assignee_id": ASSIGNEE})
    await command(client, work_order_id, "start")
    await command(client, work_order_id, "complete", {"resolution": RESOLUTION})

    events = await history(client, work_order_id)

    assert [event["event_type"] for event in events] == [
        "CREATE",
        "ASSIGN",
        "START",
        "COMPLETE",
    ]
    assert [event["work_order_version"] for event in events] == [1, 2, 3, 4]
    assert [(event["old_status"], event["new_status"]) for event in events] == [
        (None, "NEW"),
        ("NEW", "ASSIGNED"),
        ("ASSIGNED", "IN_PROGRESS"),
        ("IN_PROGRESS", "COMPLETED"),
    ]


async def test_reassignment_is_distinguishable_in_the_history(client: AsyncClient) -> None:
    """The reason REASSIGN is its own command: the history says what happened."""
    work_order = await advance_to(client, "ASSIGNED")
    await command(client, work_order["id"], "reassign", {"assignee_id": str(uuid4())})

    events = await history(client, work_order["id"])

    assert [event["event_type"] for event in events] == ["CREATE", "ASSIGN", "REASSIGN"]


async def test_free_text_is_carried_onto_the_event(client: AsyncClient) -> None:
    cancelled = await advance_to(client, "ASSIGNED")
    await command(client, cancelled["id"], "cancel", {"reason": REASON})

    events = await history(client, cancelled["id"])

    assert events[-1]["event_type"] == "CANCEL"
    assert events[-1]["reason"] == REASON
    # Commands that carry no free text record none rather than an empty string.
    assert events[1]["event_type"] == "ASSIGN"
    assert events[1]["reason"] is None


async def test_a_rejected_command_writes_no_event(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Atomicity, the half that is easy to get wrong: the 409 must leave nothing behind."""
    completed = await advance_to(client, "COMPLETED")
    before = await history(client, completed["id"])

    rejected = await client.post(f"/work-orders/{completed['id']}/start", json={})
    assert rejected.status_code == 409

    assert await history(client, completed["id"]) == before
    stored = (
        await db_session.execute(
            select(func.count())
            .select_from(WorkOrderEvent)
            .where(WorkOrderEvent.work_order_id == completed["id"])
        )
    ).scalar_one()
    assert stored == len(before)


async def test_a_failed_creation_writes_neither_work_order_nor_event(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The other half: no work order without its event, no event without its work order."""
    unknown_asset_id = uuid4()

    response = await client.post(
        "/work-orders",
        json={"asset_id": str(unknown_asset_id), "title": "t", "priority": "LOW"},
    )
    assert response.status_code == 404

    work_orders = (
        await db_session.execute(
            select(func.count())
            .select_from(WorkOrder)
            .where(WorkOrder.asset_id == unknown_asset_id)
        )
    ).scalar_one()
    assert work_orders == 0


async def test_every_work_order_has_at_least_one_event(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The invariant stated directly: no work order exists without a history."""
    await create_work_order(client)
    await advance_to(client, "IN_PROGRESS")
    await advance_to(client, "CANCELLED")

    orphans = (
        await db_session.execute(
            select(func.count())
            .select_from(WorkOrder)
            .outerjoin(WorkOrderEvent, WorkOrder.id == WorkOrderEvent.work_order_id)
            .where(WorkOrderEvent.id.is_(None))
        )
    ).scalar_one()
    assert orphans == 0


async def test_events_for_unknown_work_order_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/work-orders/{uuid4()}/events")

    assert response.status_code == 404
    assert response.json()["code"] == "WORK_ORDER_NOT_FOUND"
