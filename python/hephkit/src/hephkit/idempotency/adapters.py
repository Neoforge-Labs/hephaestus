"""Executors for the two driver stacks consumers use.

Each takes an object the caller already has a transaction open on and never
begins, commits or rolls back itself. Drivers are imported lazily, so importing
this module costs nothing and a missing driver fails with the extra to install.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    import asyncpg
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from hephkit.idempotency.ports import Executor, Executors

__all__ = [
    "AsyncpgExecutor",
    "SQLAlchemyExecutor",
    "asyncpg_executors",
    "asyncpg_work_connection",
    "sqlalchemy_executors",
    "sqlalchemy_work_connection",
]

# Where the factories below leave the handler's own connection: `request.state.<this>`.
# Internal: applications use the typed accessors.
_WORK_CONNECTION_STATE: Final = "heph_work_connection"

# `$1` -> ` :p1 `, always padded with a space on both sides. SQLAlchemy's bind-name scanner
# reads `:p1::text` as the bind `:p` and `arr[:p1:p2]` likewise, so a placeholder
# must never touch a neighbouring colon (`$1:$2` would otherwise become `:p1::p2`); the space is harmless to Postgres.
#
# PRECONDITION: this is a plain regex over the statement. It is safe only
# because every statement is one of hephkit's own module constants. A `$n`
# inside a quoted string literal WOULD be rewritten (`WHERE note = 'owes $1'`
# becomes `'owes  :p1 '`, which `text()` then treats as a bind). Never pass a
# statement that contains `$n` in a literal, and never one built from input.
_PLACEHOLDER: Final = re.compile(r"\$(\d+)")
_AFFECTED: Final = re.compile(r"(\d+)\s*$")


def _rewrite(sql: str) -> str:
    return _PLACEHOLDER.sub(lambda m: f" :p{m.group(1)} ", sql)


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
        if match is None:
            raise ValueError(f"cannot read a row count from the command status {status!r}")
        return int(match.group(1))


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


def _expose(request: Any, conn: object) -> object:
    """Put the work connection on ``request.state``; return what was there before."""
    previous = getattr(request.state, _WORK_CONNECTION_STATE, None)
    setattr(request.state, _WORK_CONNECTION_STATE, conn)
    return previous


def _unexpose(request: Any, previous: object) -> None:
    """Remove it (or restore an outer decorated callable's), so a late user cannot
    reach a connection that has gone back to the pool and belongs to another request."""
    if previous is None:
        delattr(request.state, _WORK_CONNECTION_STATE)
    else:
        setattr(request.state, _WORK_CONNECTION_STATE, previous)


def _work_connection(request: Any, driver: str) -> Any:
    try:
        return getattr(request.state, _WORK_CONNECTION_STATE)
    except AttributeError:
        raise RuntimeError(
            f"no work connection on this request. Either the route is not decorated with "
            f"idempotent_route, the request carried no Idempotency-Key on a route that does not "
            f"require one (the executors are never entered), the handler is running after the "
            f"transaction ended (a BackgroundTask or a dependency's teardown), or the route's "
            f"executors= is not {driver}_executors(...)"
        ) from None


def asyncpg_work_connection(request: Any) -> asyncpg.Connection:
    """The handler's own connection, with its transaction open (usable as ``Depends``).

    Valid **only while the handler runs**: it goes back to the pool when the
    route finishes, before ``response.background`` and before a ``yield``
    dependency's teardown, so it is removed from ``request.state`` then and a
    late caller gets ``RuntimeError``, never another request's connection.
    """
    return _work_connection(request, "asyncpg")


def sqlalchemy_work_connection(request: Any) -> AsyncConnection:
    """The handler's own ``AsyncConnection``, with its transaction open (usable as
    ``Depends``). Valid only while the handler runs; see :func:`asyncpg_work_connection`."""
    return _work_connection(request, "sqlalchemy")  # type: ignore[no-any-return]


def asyncpg_executors(
    pool: asyncpg.Pool,
    *,
    claim_pool: asyncpg.Pool | None = None,
    acquire_timeout: float = 10.0,
) -> Callable[[Any], AbstractAsyncContextManager[Executors]]:
    """The ``executors=`` argument of ``idempotent_route`` for an asyncpg pool.

    Per request it takes **two connections**: ``claim`` (plain, no transaction;
    one connection would put the claim inside the handler's transaction, which is
    the forbidden shape) from ``claim_pool`` and ``work`` (a transaction begun,
    committed when the route finishes cleanly and rolled back when it raises)
    from ``pool``. Fetch the handler's connection with
    :func:`asyncpg_work_connection`, valid only while the handler runs.

    **Sizing.** With one pool (``claim_pool`` omitted) every in-flight request
    holds a claim connection while waiting for its work connection, so if the
    route's concurrency reaches the pool's ``max_size`` every request waits on
    another and none ever proceeds. The pool therefore needs **twice** the peak
    concurrency of the route, and ``acquire_timeout`` turns exhaustion into an
    error (``TimeoutError``) instead of a silent hang. Pass a separate
    ``claim_pool`` and the deadlock cannot happen: nothing holds a connection
    from one pool while waiting on that same pool.
    """
    claims = claim_pool if claim_pool is not None else pool

    @asynccontextmanager
    async def executors(request: Any) -> AsyncIterator[Executors]:
        async with (
            claims.acquire(timeout=acquire_timeout) as claim_conn,
            pool.acquire(timeout=acquire_timeout) as work_conn,
        ):
            tx = work_conn.transaction()
            await tx.start()
            previous = _expose(request, work_conn)
            try:
                try:
                    yield Executors(AsyncpgExecutor(claim_conn), AsyncpgExecutor(work_conn))
                except BaseException:
                    await tx.rollback()
                    raise
                else:
                    await tx.commit()
            finally:
                _unexpose(request, previous)

    return executors


def sqlalchemy_executors(
    engine: AsyncEngine,
) -> Callable[[Any], AbstractAsyncContextManager[Executors]]:
    """The ``executors=`` argument of ``idempotent_route`` for a SQLAlchemy async engine.

    Per request it opens **two connections**. ``claim`` is set to AUTOCOMMIT, which
    is how SQLAlchemy says "no outer transaction" (otherwise ``connect()`` begins
    one lazily and the claim stays invisible). ``work`` is an ordinary connection
    whose transaction is committed on a clean finish and rolled back on an error.
    Fetch the handler's connection with :func:`sqlalchemy_work_connection`, valid
    only while the handler runs.

    **Sizing.** Each in-flight request holds two pooled connections, one of them
    while waiting for the other, so the engine's pool needs twice the route's
    peak concurrency. Under-sizing stalls requests for the pool's ``pool_timeout``
    (30 s by default) and then raises, rather than hanging for good.
    """

    @asynccontextmanager
    async def executors(request: Any) -> AsyncIterator[Executors]:
        async with engine.connect() as claim_conn, engine.connect() as work_conn:
            await claim_conn.execution_options(isolation_level="AUTOCOMMIT")
            previous = _expose(request, work_conn)
            try:
                try:
                    yield Executors(SQLAlchemyExecutor(claim_conn), SQLAlchemyExecutor(work_conn))
                except BaseException:
                    await work_conn.rollback()
                    raise
                else:
                    await work_conn.commit()
            finally:
                _unexpose(request, previous)

    return executors


# Static check that both adapters satisfy the port; signature drift fails mypy.
_ASYNCPG_IS_AN_EXECUTOR: Final[type[Executor]] = AsyncpgExecutor
_SQLALCHEMY_IS_AN_EXECUTOR: Final[type[Executor]] = SQLAlchemyExecutor
