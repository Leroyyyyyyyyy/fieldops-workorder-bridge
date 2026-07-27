from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
async def db_connection() -> AsyncIterator[AsyncConnection]:
    """One connection per test, inside a transaction that is always rolled back.

    Everything in a test binds to this single connection, so the application and
    the test's own queries see the same data and nothing survives the test.
    Requires a running PostgreSQL (docker compose up db); these tests
    deliberately do not fall back to SQLite.
    """
    engine = create_async_engine(get_settings().database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        yield connection
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def build_test_sessionmaker(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Sessions that join the test's transaction instead of owning one.

    `join_transaction_mode="create_savepoint"` makes `commit()` release a
    SAVEPOINT rather than end the outer transaction. Request handlers therefore
    commit for real — the code under test is not special-cased — while the test
    can still roll the whole thing back afterwards.
    """
    return async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


@pytest.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """A session for the test itself to query with."""
    session = build_test_sessionmaker(db_connection)()
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture
async def client(
    db_connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """An HTTP client for the real application, wired to the test transaction.

    This replaces the app's sessionmaker rather than overriding the `get_session`
    dependency, so the real transaction boundaries (commit when a handler
    returns, rollback when it raises) are the ones being exercised.
    """
    monkeypatch.setattr(
        "app.db.session.get_sessionmaker",
        lambda: build_test_sessionmaker(db_connection),
    )
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
