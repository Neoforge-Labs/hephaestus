"""Executors for the two driver stacks consumers use.

Each takes an object the caller already has a transaction open on and never
begins, commits or rolls back itself. Drivers are imported lazily, so importing
this module costs nothing and a missing driver fails with the extra to install.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    import asyncpg
    from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = ["AsyncpgExecutor", "SQLAlchemyExecutor"]

# `$1` -> `:p1`. A `::` cast straight after a placeholder gets a space first,
# because SQLAlchemy's bind-name scanner would otherwise read `:p1::text` as
# the bind `:p` followed by `1::text`.
_PLACEHOLDER: Final = re.compile(r"\$(\d+)(::)?")
_AFFECTED: Final = re.compile(r"(\d+)\s*$")


def _rewrite(sql: str) -> str:
    return _PLACEHOLDER.sub(lambda m: f":p{m.group(1)}" + (" ::" if m.group(2) else ""), sql)


class AsyncpgExecutor:
    """Runs statements on an asyncpg connection the caller has a transaction open on."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        try:
            import asyncpg  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                'AsyncpgExecutor needs asyncpg: pip install "hephkit[postgres]"'
            ) from exc
        self._conn = conn

    async def fetch_one(self, sql: str, params: Sequence[Any]) -> Mapping[str, Any] | None:
        row = await self._conn.fetchrow(sql, *params)
        return None if row is None else dict(row)

    async def execute(self, sql: str, params: Sequence[Any]) -> int:
        status = await self._conn.execute(sql, *params)
        match = _AFFECTED.search(status)
        return int(match.group(1)) if match else 0


class SQLAlchemyExecutor:
    """Runs statements on a SQLAlchemy ``AsyncConnection`` the caller has a transaction open on.

    **It goes through ``conn.execute(text(...))`` and never touches the raw
    driver handle** (``get_raw_connection().driver_connection``). Statements sent
    to that handle do not join SQLAlchemy's transaction: they commit on their
    own, and survive the caller's rollback. Every happy-path test still passes;
    only the rollback case, the one this module exists for, breaks. See
    finding 1 in ``docs/superpowers/specs/2026-11-11-idempotency-store-design.md``.

    Statements arrive with asyncpg's ``$1`` placeholders and are rewritten to
    ``:p1`` bind parameters here. The rewrite touches the statement only; a
    value such as ``urn:uuid:7b%2Dff:name`` is passed through as data.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        try:
            from sqlalchemy import text
        except ImportError as exc:
            raise ImportError(
                'SQLAlchemyExecutor needs SQLAlchemy: pip install "hephkit[sqlalchemy]"'
            ) from exc
        self._conn = conn
        self._text = text

    async def fetch_one(self, sql: str, params: Sequence[Any]) -> Mapping[str, Any] | None:
        result = await self._conn.execute(self._text(_rewrite(sql)), self._bind(params))
        row = result.mappings().first()
        return None if row is None else dict(row)

    async def execute(self, sql: str, params: Sequence[Any]) -> int:
        result = await self._conn.execute(self._text(_rewrite(sql)), self._bind(params))
        return int(result.rowcount)

    @staticmethod
    def _bind(params: Sequence[Any]) -> dict[str, Any]:
        return {f"p{i}": v for i, v in enumerate(params, start=1)}
