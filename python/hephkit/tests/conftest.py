"""Shared fixtures. The store tests need a real Postgres and fail without one.

Correctness modules are relational (CLAUDE.md rule 6), so there is no in-memory
stand-in, and a skipped test would still count against the coverage gate.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from hephkit.idempotency import _sql
from hephkit.idempotency.adapters import AsyncpgExecutor, SQLAlchemyExecutor
from hephkit.idempotency.ports import Executor

_DEFAULT_DSN = "postgresql://heph:heph@localhost:54320/heph"


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    return os.environ.get("HEPH_TEST_DATABASE_URL", _DEFAULT_DSN)


@pytest_asyncio.fixture
async def pg_conn(postgres_dsn: str) -> AsyncIterator[asyncpg.Connection]:
    """A raw connection with the table present and empty, so tests do not leak state."""
    conn = await asyncpg.connect(postgres_dsn)
    try:
        await conn.execute(_sql.DDL)
        await conn.execute("TRUNCATE heph_idempotency")
        yield conn
    finally:
        await conn.close()


class _Harness:
    """Test-only: opens a transaction on a driver stack and lets a test end it.

    ``count_keys`` and ``fetch_key`` read through ``pg_conn``, a separate
    connection, so they see only what has been committed.
    """

    def __init__(self, pg_conn: asyncpg.Connection) -> None:
        self._reader = pg_conn
        self._finish: str | None = None

    async def count_keys(self) -> int:
        return int(await self._reader.fetchval("SELECT count(*) FROM heph_idempotency"))

    async def fetch_key(self, scope: str, key: str) -> asyncpg.Record | None:
        return await self._reader.fetchrow(
            "SELECT * FROM heph_idempotency WHERE scope = $1 AND key = $2", scope, key
        )


class _AsyncpgHarness(_Harness):
    def __init__(self, pg_conn: asyncpg.Connection, dsn: str) -> None:
        super().__init__(pg_conn)
        self._dsn = dsn
        self._tx: asyncpg.transaction.Transaction | None = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Executor]:
        conn = await asyncpg.connect(self._dsn)
        self._tx = conn.transaction()
        await self._tx.start()
        self._finish = None
        try:
            yield AsyncpgExecutor(conn)
            if self._finish is None:
                await self.commit()
        finally:
            if self._finish is None:
                await self.rollback()
            await conn.close()

    async def rollback(self) -> None:
        assert self._tx is not None
        await self._tx.rollback()
        self._finish = "rollback"

    async def commit(self) -> None:
        assert self._tx is not None
        await self._tx.commit()
        self._finish = "commit"


class _SQLAlchemyHarness(_Harness):
    def __init__(self, pg_conn: asyncpg.Connection, dsn: str) -> None:
        super().__init__(pg_conn)
        self._url = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        self._conn: AsyncConnection | None = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Executor]:
        engine = create_async_engine(self._url)
        try:
            async with engine.connect() as conn:
                self._conn = conn
                self._finish = None
                yield SQLAlchemyExecutor(conn)
                if self._finish is None:
                    await self.commit()
        finally:
            await engine.dispose()

    async def rollback(self) -> None:
        assert self._conn is not None
        await self._conn.rollback()
        self._finish = "rollback"

    async def commit(self) -> None:
        assert self._conn is not None
        await self._conn.commit()
        self._finish = "commit"


@pytest.fixture(params=["asyncpg", "sqlalchemy"])
def adapter(request: pytest.FixtureRequest, pg_conn: asyncpg.Connection, postgres_dsn: str) -> _Harness:
    """Every store test runs once per driver stack."""
    cls = _AsyncpgHarness if request.param == "asyncpg" else _SQLAlchemyHarness
    return cls(pg_conn, postgres_dsn)
