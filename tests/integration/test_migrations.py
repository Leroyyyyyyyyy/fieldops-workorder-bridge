import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.work_orders import ASSET_FOREIGN_KEY

pytestmark = pytest.mark.integration


async def test_assets_table_exists_after_migration(db_session: AsyncSession) -> None:
    """The migration smoke test in CI runs `alembic upgrade head` on an empty
    database before pytest; this asserts the expected schema is actually there.
    """
    result = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'assets' ORDER BY column_name"
        )
    )
    columns = {row[0] for row in result.all()}

    assert {
        "id",
        "external_id",
        "site",
        "name",
        "asset_type",
        "status",
        "created_at",
        "updated_at",
    } <= columns


async def test_external_id_unique_index_exists(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text("SELECT indexname FROM pg_indexes WHERE tablename = 'assets'")
    )
    index_names = {row[0] for row in result.all()}

    assert "ix_assets_external_id" in index_names


async def test_work_orders_table_exists_after_migration(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'work_orders' ORDER BY column_name"
        )
    )
    columns = {row[0] for row in result.all()}

    assert {
        "id",
        "asset_id",
        "title",
        "description",
        "priority",
        "status",
        "version",
        "created_at",
        "updated_at",
    } <= columns


async def test_asset_foreign_key_is_named_as_the_api_expects(db_session: AsyncSession) -> None:
    """`POST /work-orders` decides 404-vs-500 by comparing the violated constraint
    name against `ASSET_FOREIGN_KEY`. Renaming the constraint would silently turn
    a 404 into a 500, so the name is pinned here rather than only in a comment.
    """
    result = await db_session.execute(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'work_orders'::regclass AND contype = 'f'"
        )
    )
    foreign_keys = {row[0] for row in result.all()}

    assert ASSET_FOREIGN_KEY in foreign_keys
