from typing import Any
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work_order import WorkOrder

pytestmark = pytest.mark.integration

TITLE = "Front left brake pack over temperature"


async def create_asset(client: AsyncClient) -> str:
    """A work order needs an asset to point at, so every test starts with one.

    `external_id` is unique per call: the test transaction is rolled back, but
    rows committed outside the suite (a manual curl against the same database)
    are visible to it, and a fixed value would collide with one.
    """
    response = await client.post(
        "/assets",
        json={
            "external_id": f"VND-ASSET-{uuid4().hex[:12]}",
            "site": "Newman",
            "name": "Haul truck HT-417",
            "asset_type": "HAUL_TRUCK",
        },
    )
    assert response.status_code == 201
    asset_id: str = response.json()["id"]
    return asset_id


def work_order_payload(asset_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "asset_id": asset_id,
        "title": TITLE,
        "description": "Flagged by onboard monitoring; temperature above threshold.",
        "priority": "HIGH",
    }
    return payload | overrides


async def test_create_work_order_persists_and_returns_server_generated_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    asset_id = await create_asset(client)

    response = await client.post("/work-orders", json=work_order_payload(asset_id))

    assert response.status_code == 201
    body = response.json()
    assert body["asset_id"] == asset_id
    assert body["title"] == TITLE
    # Fields the client never sent, all owned by the server.
    assert body["status"] == "NEW"
    assert body["version"] == 1
    assert body["id"]
    assert body["created_at"] and body["updated_at"]

    stored = (
        await db_session.execute(select(WorkOrder).where(WorkOrder.id == body["id"]))
    ).scalar_one()
    assert str(stored.asset_id) == asset_id
    assert stored.title == TITLE


async def test_created_work_order_can_be_fetched_by_id(client: AsyncClient) -> None:
    asset_id = await create_asset(client)
    created = (await client.post("/work-orders", json=work_order_payload(asset_id))).json()

    response = await client.get(f"/work-orders/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_work_order_for_unknown_asset_returns_404(client: AsyncClient) -> None:
    """A bad asset reference is a client mistake, not a server fault."""
    unknown_asset_id = str(uuid4())

    response = await client.post("/work-orders", json=work_order_payload(unknown_asset_id))

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "ASSET_NOT_FOUND"
    assert unknown_asset_id in body["message"]


async def test_rejected_work_order_leaves_no_partial_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    unknown_asset_id = uuid4()

    response = await client.post("/work-orders", json=work_order_payload(str(unknown_asset_id)))
    assert response.status_code == 404

    # Scoped to the row this request would have written. Counting the whole table
    # would make the test depend on the database being empty, which it is not
    # required to be — only the test's own transaction is rolled back.
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(WorkOrder)
            .where(WorkOrder.asset_id == unknown_asset_id)
        )
    ).scalar_one()
    assert count == 0


async def test_unknown_work_order_id_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/work-orders/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "WORK_ORDER_NOT_FOUND"


async def test_supplying_status_or_version_is_rejected(client: AsyncClient) -> None:
    """Status is owned by the state machine, so naming it is a client error."""
    asset_id = await create_asset(client)

    response = await client.post(
        "/work-orders",
        json=work_order_payload(asset_id, status="COMPLETED", version=99),
    )

    assert response.status_code == 422


async def test_misspelled_field_is_rejected(client: AsyncClient) -> None:
    """Silently dropping an unknown field would lose the caller's data."""
    asset_id = await create_asset(client)
    payload = work_order_payload(asset_id)
    payload["descriptoin"] = payload.pop("description")

    response = await client.post("/work-orders", json=payload)

    assert response.status_code == 422


async def test_unknown_priority_is_rejected(client: AsyncClient) -> None:
    asset_id = await create_asset(client)

    response = await client.post(
        "/work-orders", json=work_order_payload(asset_id, priority="WHENEVER")
    )

    assert response.status_code == 422
