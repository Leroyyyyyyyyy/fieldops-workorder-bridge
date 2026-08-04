from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_order import WorkOrder

pytestmark = pytest.mark.integration

ASSIGNEE = str(uuid4())
RESOLUTION = "Replaced the bearing and re-greased the housing."
REASON = "Raised in error; duplicate of an existing work order."


async def create_work_order(client: AsyncClient) -> dict[str, Any]:
    asset = (
        await client.post(
            "/assets",
            json={
                "external_id": f"VND-ASSET-{uuid4().hex[:12]}",
                "site": "North Yard",
                "name": "Crusher 1",
                "asset_type": "CRUSHER",
            },
        )
    ).json()
    response = await client.post(
        "/work-orders",
        json={
            "asset_id": asset["id"],
            "title": "Bearing running hot",
            "description": "Reported by night shift.",
            "priority": "HIGH",
        },
    )
    assert response.status_code == 201
    created: dict[str, Any] = response.json()
    return created


async def command(
    client: AsyncClient, work_order_id: str, name: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = await client.post(f"/work-orders/{work_order_id}/{name}", json=body)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


async def advance_to(client: AsyncClient, status_wanted: str) -> dict[str, Any]:
    """Drive a fresh work order along the legal path up to `status_wanted`."""
    work_order = await create_work_order(client)
    work_order_id = work_order["id"]
    if status_wanted == "NEW":
        return work_order
    if status_wanted == "CANCELLED":
        return await command(client, work_order_id, "cancel", {"reason": REASON})

    work_order = await command(client, work_order_id, "assign", {"assignee_id": ASSIGNEE})
    if status_wanted == "ASSIGNED":
        return work_order
    work_order = await command(client, work_order_id, "start")
    if status_wanted == "IN_PROGRESS":
        return work_order
    if status_wanted == "COMPLETED":
        return await command(client, work_order_id, "complete", {"resolution": RESOLUTION})
    raise AssertionError(f"unreachable status {status_wanted}")


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

    started = await client.post(f"/work-orders/{work_order_id}/start")
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
        ("NEW", "start", None),
        ("NEW", "complete", {"resolution": RESOLUTION}),
        ("ASSIGNED", "assign", {"assignee_id": ASSIGNEE}),
        ("ASSIGNED", "complete", {"resolution": RESOLUTION}),
        ("IN_PROGRESS", "assign", {"assignee_id": ASSIGNEE}),
        ("IN_PROGRESS", "start", None),
        ("COMPLETED", "start", None),
        ("COMPLETED", "cancel", {"reason": REASON}),
        ("CANCELLED", "assign", {"assignee_id": ASSIGNEE}),
        ("CANCELLED", "complete", {"resolution": RESOLUTION}),
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

    response = await client.post(f"/work-orders/{completed['id']}/start")
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
    response = await client.post(f"/work-orders/{uuid4()}/start")

    assert response.status_code == 404
    assert response.json()["code"] == "WORK_ORDER_NOT_FOUND"
