"""Shared fixtures. The store tests need a real Postgres and fail without one.

Correctness modules are relational (CLAUDE.md rule 6), so there is no in-memory
stand-in, and a skipped test would still count against the coverage gate.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from hephkit.idempotency import _sql

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
