from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_order import WorkOrder
from tests.integration.work_order_helpers import (
    ASSIGNEE,
    REASON,
    RESOLUTION,
    advance_to,
    command,
    create_work_order,
)

pytestmark = pytest.mark.integration


async def test_full_legal_path_moves_status_and_counts_versions(client: AsyncClient) -> None:
    created = await create_work_order(client)
    work_order_id = created["id"]
    assert created["status"] == "NEW"
    assert created["version"] == 1

    assigned = await client.post(
        f"/work-orders/{work_order_id}/assign", json={"assignee_id": ASSIGNEE}
    )
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "ASSIGNED"
    assert assigned.json()["assignee_id"] == ASSIGNEE
    assert assigned.json()["version"] == 2

    started = await client.post(f"/work-orders/{work_order_id}/start", json={})
    assert started.status_code == 200
    assert started.json()["status"] == "IN_PROGRESS"
    assert started.json()["version"] == 3

    completed = await client.post(
        f"/work-orders/{work_order_id}/complete", json={"resolution": RESOLUTION}
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert completed.json()["resolution"] == RESOLUTION
    assert completed.json()["version"] == 4


async def test_response_carries_the_stored_timestamp_not_a_stale_one(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`updated_at` is written by SQLAlchemy when it compiles the UPDATE, so the
    response has to reflect what the database now holds rather than the value the
    row was loaded with. Fetching it back requires RETURNING on the UPDATE; without
    that the attribute is merely expired and reading it raises `MissingGreenlet`.

    This asserts equality with the stored row rather than that the timestamp moved
    forward: PostgreSQL's `now()` is the transaction start time, and every request
    in a test shares one transaction, so it cannot advance here.
    """
    created = await create_work_order(client)

    assigned = (
        await client.post(f"/work-orders/{created['id']}/assign", json={"assignee_id": ASSIGNEE})
    ).json()

    stored = (
        await db_session.execute(select(WorkOrder).where(WorkOrder.id == created["id"]))
    ).scalar_one()
    assert datetime.fromisoformat(assigned["updated_at"]) == stored.updated_at
    assert assigned["created_at"] == created["created_at"]


@pytest.mark.parametrize("from_status", ["NEW", "ASSIGNED", "IN_PROGRESS"])
async def test_cancel_is_allowed_from_every_non_terminal_status(
    client: AsyncClient, from_status: str
) -> None:
    work_order = await advance_to(client, from_status)

    response = await client.post(f"/work-orders/{work_order['id']}/cancel", json={"reason": REASON})

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert response.json()["cancellation_reason"] == REASON


@pytest.mark.parametrize(
    ("from_status", "command", "body"),
    [
        ("NEW", "start", {}),
        ("NEW", "complete", {"resolution": RESOLUTION}),
        ("NEW", "reassign", {"assignee_id": ASSIGNEE}),
        ("ASSIGNED", "assign", {"assignee_id": ASSIGNEE}),
        ("ASSIGNED", "complete", {"resolution": RESOLUTION}),
        ("IN_PROGRESS", "assign", {"assignee_id": ASSIGNEE}),
        ("IN_PROGRESS", "start", {}),
        ("COMPLETED", "start", {}),
        ("COMPLETED", "cancel", {"reason": REASON}),
        ("COMPLETED", "reassign", {"assignee_id": ASSIGNEE}),
        ("CANCELLED", "assign", {"assignee_id": ASSIGNEE}),
        ("CANCELLED", "complete", {"resolution": RESOLUTION}),
        ("CANCELLED", "reassign", {"assignee_id": ASSIGNEE}),
    ],
)
async def test_illegal_transition_returns_409(
    client: AsyncClient, from_status: str, command: str, body: dict[str, Any] | None
) -> None:
    work_order = await advance_to(client, from_status)

    response = await client.post(f"/work-orders/{work_order['id']}/{command}", json=body)

    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_STATE_TRANSITION"
    assert from_status in response.json()["message"]


async def test_rejected_command_leaves_the_row_untouched(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The 409 rolls back: no status change, and no half-applied version bump."""
    completed = await advance_to(client, "COMPLETED")

    response = await client.post(f"/work-orders/{completed['id']}/start", json={})
    assert response.status_code == 409

    stored = (
        await db_session.execute(select(WorkOrder).where(WorkOrder.id == completed["id"]))
    ).scalar_one()
    assert stored.status == "COMPLETED"
    assert stored.version == completed["version"]


async def test_completing_requires_a_resolution(client: AsyncClient) -> None:
    work_order = await advance_to(client, "IN_PROGRESS")

    assert (
        await client.post(f"/work-orders/{work_order['id']}/complete", json={})
    ).status_code == (422)


async def test_cancelling_requires_a_reason(client: AsyncClient) -> None:
    work_order = await advance_to(client, "NEW")

    assert (await client.post(f"/work-orders/{work_order['id']}/cancel", json={})).status_code == (
        422
    )


async def test_blank_resolution_is_rejected(client: AsyncClient) -> None:
    work_order = await advance_to(client, "IN_PROGRESS")

    response = await client.post(
        f"/work-orders/{work_order['id']}/complete", json={"resolution": "   "}
    )

    assert response.status_code == 422


async def test_command_on_unknown_work_order_returns_404(client: AsyncClient) -> None:
    response = await client.post(f"/work-orders/{uuid4()}/start", json={})

    assert response.status_code == 404
    assert response.json()["code"] == "WORK_ORDER_NOT_FOUND"


async def test_reassigning_changes_the_assignee_and_keeps_it_assigned(client: AsyncClient) -> None:
    work_order = await advance_to(client, "ASSIGNED")
    other_technician = str(uuid4())

    reassigned = await command(
        client, work_order["id"], "reassign", {"assignee_id": other_technician}
    )

    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["assignee_id"] == other_technician
    assert reassigned["version"] == work_order["version"] + 1


async def test_reassigning_in_progress_work_returns_it_to_assigned(client: AsyncClient) -> None:
    """The new assignee has not started the work, whoever else had."""
    work_order = await advance_to(client, "IN_PROGRESS")
    other_technician = str(uuid4())

    reassigned = await command(
        client, work_order["id"], "reassign", {"assignee_id": other_technician}
    )

    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["assignee_id"] == other_technician
    # ...and the new assignee has to start it themselves before completing.
    started = await command(client, work_order["id"], "start")
    assert started["status"] == "IN_PROGRESS"


async def test_start_rejects_an_unknown_field(client: AsyncClient) -> None:
    """`start` takes an empty body so that it refuses junk like every other command."""
    work_order = await advance_to(client, "ASSIGNED")

    response = await client.post(
        f"/work-orders/{work_order['id']}/start", json={"expected_version": 99}
    )

    assert response.status_code == 422
