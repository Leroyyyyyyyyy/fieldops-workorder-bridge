from typing import Any
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset

pytestmark = pytest.mark.integration

NEW_ASSET: dict[str, Any] = {
    "external_id": "VND-ASSET-001",
    "site": "North Yard",
    "name": "Conveyor 3",
    "asset_type": "CONVEYOR",
}


async def test_create_asset_persists_and_returns_server_generated_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post("/assets", json=NEW_ASSET)

    assert response.status_code == 201
    body = response.json()
    assert body["external_id"] == NEW_ASSET["external_id"]
    # Fields the client never sent: the id and timestamps come from PostgreSQL,
    # and the status from the column default.
    assert body["id"]
    assert body["created_at"] and body["updated_at"]
    assert body["status"] == "ACTIVE"

    stored = (
        await db_session.execute(select(Asset).where(Asset.external_id == NEW_ASSET["external_id"]))
    ).scalar_one()
    assert str(stored.id) == body["id"]
    assert stored.name == NEW_ASSET["name"]


async def test_created_asset_can_be_fetched_by_id(client: AsyncClient) -> None:
    created = (await client.post("/assets", json=NEW_ASSET)).json()

    response = await client.get(f"/assets/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_duplicate_external_id_is_rejected_with_409(client: AsyncClient) -> None:
    assert (await client.post("/assets", json=NEW_ASSET)).status_code == 201

    response = await client.post("/assets", json={**NEW_ASSET, "name": "Different name"})

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "DUPLICATE_EXTERNAL_ID"
    assert NEW_ASSET["external_id"] in body["message"]
    assert body["correlation_id"] is None


async def test_rejected_duplicate_leaves_the_original_intact(client: AsyncClient) -> None:
    """The failed request rolls back without touching the row already committed."""
    created = (await client.post("/assets", json=NEW_ASSET)).json()

    await client.post("/assets", json={**NEW_ASSET, "name": "Different name"})

    response = await client.get(f"/assets/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == NEW_ASSET["name"]


async def test_list_returns_created_assets(client: AsyncClient) -> None:
    first = (await client.post("/assets", json=NEW_ASSET)).json()
    second = (
        await client.post("/assets", json={**NEW_ASSET, "external_id": "VND-ASSET-002"})
    ).json()

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
    response = await client.post("/assets", json={**NEW_ASSET, "external_id": ""})

    assert response.status_code == 422
