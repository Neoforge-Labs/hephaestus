"""The port the idempotency store runs its SQL through.

This module imports no driver, so ``hephkit.idempotency`` stays dependency-free.
hephkit never opens a connection, owns a pool or runs a background task: the
caller hands the store an executor that **already has a transaction open**, and
the store's statements commit or roll back with the caller's own work. That is
the whole point of the module (design finding 1).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

__all__ = ["Executor"]


class Executor(Protocol):
    """Runs one statement inside the caller's open transaction.

    ``sql`` is always written with ``$1``-style placeholders, asyncpg's native
    form, and values travel only in ``params``. No caller formats a value into
    a statement. An adapter for a driver with another placeholder style
    rewrites the statement, never the values.
    """

    async def fetch_one(self, sql: str, params: Sequence[Any]) -> Mapping[str, Any] | None:
        """The first row as a mapping, or ``None`` when there is none."""
        ...

    async def execute(self, sql: str, params: Sequence[Any]) -> int:
        """Run an INSERT, UPDATE or DELETE and return the number of rows it affected.

        DML only. On a SELECT the adapters disagree (asyncpg's status yields the
        row count, SQLAlchemy's ``rowcount`` is typically -1); use ``fetch_one``.
        """
        ...
