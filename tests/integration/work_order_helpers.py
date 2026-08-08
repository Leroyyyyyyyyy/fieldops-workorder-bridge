"""Shared helpers for driving work orders through their lifecycle in tests."""

from typing import Any
from uuid import uuid4

from httpx2 import AsyncClient

ASSIGNEE = str(uuid4())
RESOLUTION = "Replaced the bearing and re-greased the housing."
REASON = "Raised in error; duplicate of an existing work order."


async def create_work_order(client: AsyncClient) -> dict[str, Any]:
    asset = (
        await client.post(
            "/assets",
            json={
                "external_id": f"VND-ASSET-{uuid4().hex[:12]}",
                "site": "Paraburdoo",
                "name": "Primary crusher CR-03",
                "asset_type": "CRUSHER",
            },
        )
    ).json()
    response = await client.post(
        "/work-orders",
        json={
            "asset_id": asset["id"],
            "title": "Drive end bearing over temperature",
            "description": "Flagged by condition monitoring on night shift.",
            "priority": "HIGH",
        },
    )
    assert response.status_code == 201
    created: dict[str, Any] = response.json()
    return created


async def command(
    client: AsyncClient, work_order_id: str, name: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Every command takes a body, `start`'s being an empty one."""
    body = {} if body is None else body
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
