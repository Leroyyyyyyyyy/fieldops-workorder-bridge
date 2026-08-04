from typing import Any
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset

pytestmark = pytest.mark.integration


def new_asset(**overrides: Any) -> dict[str, Any]:
    """A create payload with a unique `external_id`.

    The test transaction is rolled back, but rows committed outside the suite (a
    manual curl against the same database) are visible to it, so a fixed
    `external_id` would eventually collide with one and fail for the wrong reason.
    """
    payload: dict[str, Any] = {
        "external_id": f"VND-ASSET-{uuid4().hex[:12]}",
        "site": "North Yard",
        "name": "Conveyor 3",
        "asset_type": "CONVEYOR",
    }
    return payload | overrides


async def test_create_asset_persists_and_returns_server_generated_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    asset = new_asset()

    response = await client.post("/assets", json=asset)

    assert response.status_code == 201
    body = response.json()
    assert body["external_id"] == asset["external_id"]
    # Fields the client never sent: the id and timestamps come from PostgreSQL,
    # and the status from the column default.
    assert body["id"]
    assert body["created_at"] and body["updated_at"]
    assert body["status"] == "ACTIVE"

    stored = (await db_session.execute(select(Asset).where(Asset.id == body["id"]))).scalar_one()
    assert stored.external_id == asset["external_id"]
    assert stored.name == asset["name"]


async def test_created_asset_can_be_fetched_by_id(client: AsyncClient) -> None:
    created = (await client.post("/assets", json=new_asset())).json()

    response = await client.get(f"/assets/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_duplicate_external_id_is_rejected_with_409(client: AsyncClient) -> None:
    asset = new_asset()
    assert (await client.post("/assets", json=asset)).status_code == 201

    response = await client.post("/assets", json={**asset, "name": "Different name"})

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "DUPLICATE_EXTERNAL_ID"
    assert asset["external_id"] in body["message"]
    assert body["correlation_id"] is None


async def test_rejected_duplicate_leaves_the_original_intact(client: AsyncClient) -> None:
    """The failed request rolls back without touching the row already committed."""
    asset = new_asset()
    created = (await client.post("/assets", json=asset)).json()

    await client.post("/assets", json={**asset, "name": "Different name"})

    response = await client.get(f"/assets/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == asset["name"]


async def test_list_returns_created_assets(client: AsyncClient) -> None:
    first = (await client.post("/assets", json=new_asset())).json()
    second = (await client.post("/assets", json=new_asset())).json()

    response = await client.get("/assets")

    assert response.status_code == 200
    ids = [asset["id"] for asset in response.json()]
    assert first["id"] in ids
    assert second["id"] in ids


async def test_unknown_asset_id_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/assets/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "ASSET_NOT_FOUND"


async def test_blank_external_id_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/assets", json=new_asset(external_id=""))

    assert response.status_code == 422


async def test_misspelled_field_is_rejected(client: AsyncClient) -> None:
    """Silently dropping an unknown field would lose the caller's data."""
    payload = new_asset()
    payload["nmae"] = payload.pop("name")

    response = await client.post("/assets", json=payload)

    assert response.status_code == 422
