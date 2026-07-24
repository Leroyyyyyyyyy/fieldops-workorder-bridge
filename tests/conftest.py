from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session bound to the real test database.

    Each test runs inside a transaction that is rolled back at the end, so tests
    never see each other's writes and the database is left clean. Requires a
    running PostgreSQL (docker compose up db); these tests deliberately do not
    fall back to SQLite.
    """
    engine = create_async_engine(get_settings().database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = async_sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()
