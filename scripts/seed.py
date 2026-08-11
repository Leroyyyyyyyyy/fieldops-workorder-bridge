"""Generate a realistically shaped dataset for query and index work.

Run with:

    uv run python -m scripts.seed --yes

**This deletes every asset, work order and event first.** It is a development
tool; the `--yes` flag exists so that pointing it at the wrong `DATABASE_URL`
takes a deliberate act. The random seed is fixed, so the same command always
produces the same dataset.

Two properties matter more than the row counts:

*The history is legal.* Every work order's events are produced by walking the
real state machine in `app.domain.work_order_status`, one `next_status()` call
per step, so an invalid sequence cannot be generated even by accident. The
generator is a second consumer of those rules rather than a copy of them.

*The distribution is skewed.* Uniform random data is worse than useless for
index work: it produces query plans that no real table would produce. Statuses
lean heavily on COMPLETED, a handful of tradespeople hold most of the work, some
plant fails far more than the rest, and timestamps spread across 18 months.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_sessionmaker
from app.domain.work_order_status import (
    Command,
    EventSource,
    Priority,
    WorkOrderEventType,
    WorkOrderStatus,
    next_status,
)
from app.models.asset import Asset
from app.models.work_order import WorkOrder
from app.models.work_order_event import WorkOrderEvent

DEFAULT_ASSETS = 2_000
DEFAULT_WORK_ORDERS = 50_000
MONTHS_OF_HISTORY = 18
BATCH = 5_000
RANDOM_SEED = 20260808

SITES = (
    "Tom Price",
    "Paraburdoo",
    "Newman",
    "Marandoo",
    "Yandicoogina",
    "Cape Lambert",
    "Port Hedland",
    "Karratha",
)
ASSET_TYPES = ("HAUL_TRUCK", "CONVEYOR", "CRUSHER", "PUMP", "SCREEN", "EXCAVATOR")
ASSET_PREFIX = {
    "HAUL_TRUCK": "HT",
    "CONVEYOR": "CV",
    "CRUSHER": "CR",
    "PUMP": "PU",
    "SCREEN": "SC",
    "EXCAVATOR": "EX",
}
FAULTS = {
    "HAUL_TRUCK": ("Front left brake pack over temperature", "Steering accumulator pressure low"),
    "CONVEYOR": ("Drive end bearing over temperature", "Belt tracking off centre at tail pulley"),
    "CRUSHER": ("Mantle wear beyond limit", "Lube return temperature high"),
    "PUMP": ("Gland seal leaking", "Discharge pressure below setpoint"),
    "SCREEN": ("Deck panel cracked", "Exciter oil level low"),
    "EXCAVATOR": ("Swing motor noise under load", "Bucket tooth missing"),
}
RESOLUTIONS = (
    "Replaced the bearing and re-greased the housing.",
    "Adjusted tracking and re-tensioned the belt.",
    "Replaced seal kit; pressure tested and returned to service.",
    "Replaced worn liners and confirmed clearances.",
    "Topped up and corrected the leak at the fitting.",
)
CANCELLATION_REASONS = (
    "Duplicate of an existing work order for the same fault.",
    "Fault cleared on inspection; no work required.",
    "Superseded by the scheduled shutdown scope.",
)

#: Roughly what a maintenance backlog looks like: most work is finished, a small
#: tail is open, and a few jobs were raised in error.
STATUS_WEIGHTS = {
    WorkOrderStatus.COMPLETED: 0.66,
    WorkOrderStatus.CANCELLED: 0.07,
    WorkOrderStatus.IN_PROGRESS: 0.07,
    WorkOrderStatus.ASSIGNED: 0.10,
    WorkOrderStatus.NEW: 0.10,
}
PRIORITY_WEIGHTS = {
    Priority.LOW: 0.34,
    Priority.MEDIUM: 0.42,
    Priority.HIGH: 0.19,
    Priority.CRITICAL: 0.05,
}
TECHNICIANS = 40
#: Fraction of work held by the busiest quarter of the crew.
BUSY_CREW_SHARE = 0.72


def _uuid(rng: random.Random) -> uuid.UUID:
    """A UUID drawn from the seeded generator, so re-seeding reproduces the same
    dataset exactly — ids included, which makes a demo query written against it
    keep working. `uuid4()` reads from the OS entropy pool and would ignore the
    seed. Predictable ids are fine for generated data and would not be for real
    ones, which the database still creates with `gen_random_uuid()`.
    """
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def _weighted(rng: random.Random, weights: dict[Any, float]) -> Any:
    return rng.choices(list(weights), weights=list(weights.values()), k=1)[0]


def build_assets(rng: random.Random, count: int) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    assets = []
    for index in range(count):
        asset_type = rng.choice(ASSET_TYPES)
        commissioned = now - timedelta(days=rng.randint(400, 4000))
        assets.append(
            {
                "id": _uuid(rng),
                "external_id": f"PLT-{index + 1:06d}",
                "site": rng.choice(SITES),
                "name": f"{ASSET_PREFIX[asset_type]}-{rng.randint(100, 999)}",
                "asset_type": asset_type,
                "status": "ACTIVE" if rng.random() > 0.04 else "RETIRED",
                "created_at": commissioned,
                "updated_at": commissioned,
            }
        )
    return assets


def _technician_pool(rng: random.Random) -> tuple[list[uuid.UUID], list[float]]:
    """A crew where a quarter of the tradespeople hold most of the work orders."""
    crew = [_uuid(rng) for _ in range(TECHNICIANS)]
    busy = max(1, TECHNICIANS // 4)
    weights = [BUSY_CREW_SHARE / busy] * busy
    weights += [(1 - BUSY_CREW_SHARE) / (TECHNICIANS - busy)] * (TECHNICIANS - busy)
    rng.shuffle(crew)
    return crew, weights


def _started_path(rng: random.Random) -> list[Command]:
    """Assign, then start, with reassignment possible on either side of starting.

    Reassigning work that is already under way is the case the REASSIGN command
    exists for — a tradesperson goes off shift mid-job — so the dataset has to
    contain it. It sends the work order back to ASSIGNED, which means the new
    assignee starts it again, hence the paired START.
    """
    before_start = rng.choices([0, 1, 2], weights=[0.82, 0.15, 0.03], k=1)[0]
    mid_job = rng.choices([0, 1, 2], weights=[0.90, 0.08, 0.02], k=1)[0]
    path = [Command.ASSIGN] + [Command.REASSIGN] * before_start + [Command.START]
    for _ in range(mid_job):
        path += [Command.REASSIGN, Command.START]
    return path


def _command_path(rng: random.Random, target: WorkOrderStatus) -> list[Command]:
    """Commands that lead to `target`, with reassignment mixed in where legal."""
    if target is WorkOrderStatus.NEW:
        return []

    if target is WorkOrderStatus.CANCELLED:
        # Cancelled work is abandoned at different points in its life.
        stage = rng.choices(["new", "assigned", "in_progress"], weights=[0.4, 0.35, 0.25], k=1)[0]
        if stage == "new":
            return [Command.CANCEL]
        if stage == "in_progress":
            return [*_started_path(rng), Command.CANCEL]
        reassignments = rng.choices([0, 1, 2], weights=[0.82, 0.15, 0.03], k=1)[0]
        return [Command.ASSIGN, *[Command.REASSIGN] * reassignments, Command.CANCEL]

    if target is WorkOrderStatus.ASSIGNED:
        reassignments = rng.choices([0, 1, 2], weights=[0.82, 0.15, 0.03], k=1)[0]
        return [Command.ASSIGN, *[Command.REASSIGN] * reassignments]

    path = _started_path(rng)
    if target is WorkOrderStatus.IN_PROGRESS:
        return path
    return [*path, Command.COMPLETE]


def build_work_orders(
    rng: random.Random, assets: Sequence[dict[str, Any]], count: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Work orders and the event history that produced them.

    Every step goes through `next_status`, so a history that the API would have
    refused to create cannot be generated here either.
    """
    crew, crew_weights = _technician_pool(rng)
    now = datetime.now(UTC)
    earliest = now - timedelta(days=MONTHS_OF_HISTORY * 30)
    # A few pieces of plant are responsible for a lot of the backlog.
    trouble = rng.sample(range(len(assets)), k=max(1, len(assets) // 20))
    asset_weights = [5.0 if index in set(trouble) else 1.0 for index in range(len(assets))]

    work_orders: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    for _ in range(count):
        asset = rng.choices(assets, weights=asset_weights, k=1)[0]
        target = _weighted(rng, STATUS_WEIGHTS)
        raised_at = earliest + timedelta(seconds=rng.randint(0, MONTHS_OF_HISTORY * 30 * 86_400))
        work_order_id = _uuid(rng)
        asset_type = str(asset["asset_type"])

        status = WorkOrderStatus.NEW
        version = 1
        at = raised_at
        assignee: uuid.UUID | None = None
        resolution: str | None = None
        cancellation_reason: str | None = None

        events.append(
            _event(
                _uuid(rng),
                work_order_id,
                WorkOrderEventType.CREATE,
                None,
                status,
                version,
                at,
                None,
            )
        )

        for command in _command_path(rng, target):
            previous = status
            status = next_status(command, status)  # refuses an illegal path outright
            version += 1
            at += timedelta(minutes=rng.randint(20, 60 * 72))
            reason = None
            if command is Command.ASSIGN or command is Command.REASSIGN:
                assignee = rng.choices(crew, weights=crew_weights, k=1)[0]
            elif command is Command.COMPLETE:
                reason = resolution = rng.choice(RESOLUTIONS)
            elif command is Command.CANCEL:
                reason = cancellation_reason = rng.choice(CANCELLATION_REASONS)
            events.append(
                _event(
                    _uuid(rng),
                    work_order_id,
                    WorkOrderEventType(command),
                    previous,
                    status,
                    version,
                    at,
                    reason,
                )
            )

        work_orders.append(
            {
                "id": work_order_id,
                "asset_id": asset["id"],
                "title": rng.choice(FAULTS[asset_type]),
                "description": None,
                "priority": str(_weighted(rng, PRIORITY_WEIGHTS)),
                "status": str(status),
                "version": version,
                "assignee_id": assignee,
                "resolution": resolution,
                "cancellation_reason": cancellation_reason,
                "created_at": raised_at,
                "updated_at": at,
            }
        )

    return work_orders, events


def _event(
    event_id: uuid.UUID,
    work_order_id: uuid.UUID,
    event_type: WorkOrderEventType,
    old_status: WorkOrderStatus | None,
    new_status: WorkOrderStatus,
    version: int,
    at: datetime,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "work_order_id": work_order_id,
        "event_type": str(event_type),
        "old_status": str(old_status) if old_status is not None else None,
        "new_status": str(new_status),
        "work_order_version": version,
        "actor_id": None,
        "source": str(EventSource.API),
        "reason": reason,
        "correlation_id": None,
        "created_at": at,
    }


async def _insert_all(session: AsyncSession, model: Any, rows: list[dict[str, Any]]) -> None:
    """Core executemany rather than ORM objects: 200k mapped instances would be
    slow to build and would buy nothing, since nothing here needs identity."""
    for start in range(0, len(rows), BATCH):
        await session.execute(insert(model), rows[start : start + BATCH])


async def seed(
    session: AsyncSession, assets: int = DEFAULT_ASSETS, work_orders: int = DEFAULT_WORK_ORDERS
) -> tuple[int, int, int]:
    """Replace the contents of the three tables. Returns the row counts written."""
    rng = random.Random(RANDOM_SEED)
    await session.execute(
        text("TRUNCATE work_order_events, work_orders, assets RESTART IDENTITY CASCADE")
    )
    asset_rows = build_assets(rng, assets)
    await _insert_all(session, Asset, asset_rows)
    work_order_rows, event_rows = build_work_orders(rng, asset_rows, work_orders)
    await _insert_all(session, WorkOrder, work_order_rows)
    await _insert_all(session, WorkOrderEvent, event_rows)
    return len(asset_rows), len(work_order_rows), len(event_rows)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=int, default=DEFAULT_ASSETS)
    parser.add_argument("--work-orders", type=int, default=DEFAULT_WORK_ORDERS)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="required: confirms deleting every asset, work order and event first",
    )
    args = parser.parse_args()
    if not args.yes:
        parser.error("this deletes all existing data; pass --yes to confirm")

    async with get_sessionmaker()() as session:
        counts = await seed(session, assets=args.assets, work_orders=args.work_orders)
        await session.commit()
    print(f"seeded {counts[0]:,} assets, {counts[1]:,} work orders, {counts[2]:,} events")


if __name__ == "__main__":
    asyncio.run(main())
