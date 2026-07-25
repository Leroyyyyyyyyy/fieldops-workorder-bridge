import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
