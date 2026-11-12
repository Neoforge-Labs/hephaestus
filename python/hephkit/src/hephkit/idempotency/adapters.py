"""Executors for the two driver stacks consumers use.

Each takes an object the caller already has a transaction open on and never
begins, commits or rolls back itself. Drivers are imported lazily, so importing
this module costs nothing and a missing driver fails with the extra to install.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    import asyncpg
    from starlette.requests import Request
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from hephkit.errors import DB_503, HephError
from hephkit.idempotency.ports import Executor, Executors

__all__ = [
    "AsyncpgExecutor",
    "SQLAlchemyExecutor",
    "asyncpg_event_executors",
    "asyncpg_event_work_connection",
    "asyncpg_executors",
    "asyncpg_work_connection",
    "sqlalchemy_executors",
    "sqlalchemy_work_connection",
]

# Where the factories below leave the handler's own connection: `request.state.<this>`.
# Internal: applications use the typed accessors.
_WORK_CONNECTION_STATE: Final = "heph_work_connection"

# The same thing for an event, which has no request to hang it on. A ContextVar
# because the only thing a message handler and its factory share is the task
# they run in: set around the handler, reset after it, read by the accessor.
_EVENT_WORK_CONNECTION: Final[ContextVar[Any]] = ContextVar("heph_event_work_connection")

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


def _pool_timeout(role: str) -> HephError:
    """The registry's 503 for an acquire that ran out of time.

    ``acquire_timeout`` already turns pool exhaustion into an error rather than
    a permanent stall, but a bare ``TimeoutError`` carries no code, so
    ``install_error_handlers`` renders it as ``HEPH-GEN-500`` and the operator
    woken by it learns nothing about connections. ADR 0020 calls this the thing
    an adopter is most likely to get wrong, so it gets a code of its own, and
    503 because the right answer is to retry once the pressure passes.

    **``detail`` is left ``None`` deliberately**, so the response body carries
    the registry's caller-facing hint. The sizing rule is developer guidance,
    which the registry publishes at ``/errors/HEPH-DB-503`` -- the problem
    ``type`` of this very response -- and never sends on the wire. The message
    the exception itself carries, which is what a log line and a traceback show,
    is the operator's half, and the original ``TimeoutError`` stays chained to
    it.
    """
    error = HephError(DB_503)
    error.args = (
        f"timed out acquiring the {role} connection: the pool had none free. Every idempotent "
        "request or delivery holds two connections and waits for the second while holding the "
        "first, so a single pool needs twice the peak concurrency of whatever uses it. Pass "
        "claim_pool= to take the claim connections from a pool of their own, or raise the "
        "pool's size.",
    )
    return error


@asynccontextmanager
async def _acquired(pool: Any, role: str, timeout: float | None) -> AsyncIterator[Any]:
    """``pool.acquire(timeout=...)``, with a timeout on the *acquire* named as HEPH-DB-503.

    The flag keeps the translation to the acquire itself. A ``TimeoutError`` the
    handler raises inside the block, or one raised while the connection goes
    back to the pool, is not pool exhaustion and must pass through with its own
    meaning intact.
    """
    acquiring = True
    try:
        async with pool.acquire(timeout=timeout) as conn:
            acquiring = False
            yield conn
    except TimeoutError as exc:
        if acquiring:
            raise _pool_timeout(role) from exc
        raise


@asynccontextmanager
async def _connected(engine: Any, role: str) -> AsyncIterator[Any]:
    """``engine.connect()``, with SQLAlchemy's own pool wait named as HEPH-DB-503.

    The wait itself stays SQLAlchemy's (``pool_timeout``, 30 seconds by
    default); only the name of the error it ends in changes, and only for the
    connect. SQLAlchemy raises its own ``sqlalchemy.exc.TimeoutError`` there,
    which is not the builtin, so the two factories cannot share one arm.
    """
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    connecting = True
    try:
        async with engine.connect() as conn:
            connecting = False
            yield conn
    except PoolTimeout as exc:
        if connecting:
            raise _pool_timeout(role) from exc
        raise


def _expose(request: Any, conn: object) -> object:
    """Put the work connection on ``request.state``; return what was there before."""
    previous = getattr(request.state, _WORK_CONNECTION_STATE, None)
    setattr(request.state, _WORK_CONNECTION_STATE, conn)
    return previous


def _unexpose(request: Any, previous: object) -> None:
    """Remove it (or restore an outer decorated callable's), so a late user cannot
    reach a connection that has gone back to the pool and belongs to another request.

    Save and restore is a stack discipline: correct for **nested** use only. Two
    decorated callables running concurrently in one request (``asyncio.gather``)
    can exit out of order and leave a released connection behind.
    """
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
            f"transaction ended (a BackgroundTask or a dependency's teardown), this was called "
            f"from a Depends(...) (dependencies resolve before the handler, so before the "
            f"connection exists; call it inside the handler body), or the route's "
            f"executors= is not {driver}_executors(...)"
        ) from None


def asyncpg_work_connection(request: Request) -> asyncpg.Connection:
    """The handler's own connection, with its transaction open.

    **Call it inside the handler body, not as a ``Depends(...)``.** FastAPI
    resolves every dependency before it calls the endpoint, which is before
    ``idempotent_route`` enters ``executors``, so the connection does not exist
    yet and a dependency would fail on every request.

    Valid **only while the handler runs**: it goes back to the pool when the
    route finishes, before ``response.background`` and before a ``yield``
    dependency's teardown, so it is removed from ``request.state`` then and a
    late caller gets ``RuntimeError``, never another request's connection.
    """
    return _work_connection(request, "asyncpg")


def sqlalchemy_work_connection(request: Request) -> AsyncConnection:
    """The handler's own ``AsyncConnection``, with its transaction open.

    Call it inside the handler body, never as a ``Depends(...)`` (dependencies
    resolve before ``executors`` is entered). Valid only while the handler runs;
    see :func:`asyncpg_work_connection`."""
    return _work_connection(request, "sqlalchemy")  # type: ignore[no-any-return]


def asyncpg_event_work_connection() -> asyncpg.Connection:
    """The handler's own connection, inside a handler decorated with ``@idempotent``.

    The event path's :func:`asyncpg_work_connection`. An event carries no
    request, so there is no ``request.state`` to read it off and no argument the
    decorator could add without changing how every handler is called; the
    connection travels in a ``ContextVar`` that
    :func:`asyncpg_event_executors` sets around the handler, and this returns
    it.

    Valid **only while the handler runs**. Afterwards the connection is back in
    the pool and belongs to whatever event took it next, so a late caller gets
    ``RuntimeError`` rather than someone else's connection. Concurrent events
    are separate tasks with separate contexts, so they do not see each other's;
    a task the handler starts inherits a copy of the value, which means a task
    it does not await can outlive the handler holding a connection that has
    been released. Await what you start.
    """
    try:
        return _EVENT_WORK_CONNECTION.get()
    except LookupError:
        raise RuntimeError(
            "no work connection for this event. Either the handler is not decorated with "
            "idempotent, its executors= is not asyncpg_event_executors(...), or this was "
            "called after the handler returned (the connection goes back to the pool then, "
            "so it is removed) or from a task the handler started and did not await"
        ) from None


def asyncpg_event_executors(
    pool: asyncpg.Pool,
    *,
    claim_pool: asyncpg.Pool | None = None,
    acquire_timeout: float = 10.0,
) -> Callable[[Any], AbstractAsyncContextManager[Executors]]:
    """The ``executors=`` argument of ``idempotent`` for an asyncpg pool.

    :func:`asyncpg_executors` for the worker path, and the same arrangement:
    ``claim`` plain, from ``claim_pool`` when one is given, ``work`` with a
    transaction begun, committed when the handler finishes cleanly and rolled
    back when anything passes through. The sizing rule and ``acquire_timeout``
    are the route factory's -- two connections per event in flight, one held
    while waiting for the other, so a single pool needs twice the worker's
    concurrency, and an acquire that runs out of time is ``HEPH-DB-503``.

    It takes the event rather than a request, and hands the work connection to
    the handler through :func:`asyncpg_event_work_connection` instead of
    ``request.state``. **Write through that connection**: it is the one whose
    transaction holds the stored record, so the work and the record commit
    together or neither does. A write on any other connection commits on its
    own and outlives a rolled-back delivery.

    The route factory's body is not shared with this one: the two differ in
    where the work connection goes, and this one must not touch
    ``request.state``, which an event has none of.
    """
    claims = claim_pool if claim_pool is not None else pool

    @asynccontextmanager
    async def executors(event: Any) -> AsyncIterator[Executors]:
        async with (
            _acquired(claims, "claim", acquire_timeout) as claim_conn,
            _acquired(pool, "work", acquire_timeout) as work_conn,
        ):
            tx = work_conn.transaction()
            await tx.start()
            token = _EVENT_WORK_CONNECTION.set(work_conn)
            try:
                try:
                    yield Executors(AsyncpgExecutor(claim_conn), AsyncpgExecutor(work_conn))
                except BaseException:
                    await tx.rollback()
                    raise
                else:
                    await tx.commit()
            finally:
                _EVENT_WORK_CONNECTION.reset(token)

    return executors


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
    concurrency of the route, and ``acquire_timeout`` turns exhaustion into
    ``HEPH-DB-503`` instead of a silent hang. Pass a separate ``claim_pool`` and
    the deadlock cannot happen: nothing holds a connection from one pool while
    waiting on that same pool.

    ``acquire_timeout`` defaults to **10.0 seconds** and applies to each acquire.
    It also bounds opening a new connection when the pool grows, so a slow
    database now fails where an unbounded wait would have succeeded eventually.
    ``None`` restores the unbounded wait, and with it the permanent hang
    described above if the pool is under-sized.

    An acquire that runs out of time raises ``HephError`` with ``HEPH-DB-503``,
    so the response is a 503 the client can retry and the log line names the
    pool rather than reading as a generic 500. The exception's message carries the sizing rule above; the
    body the client gets carries the registry's hint and nothing about
    connection pools.
    """
    claims = claim_pool if claim_pool is not None else pool

    @asynccontextmanager
    async def executors(request: Any) -> AsyncIterator[Executors]:
        async with (
            _acquired(claims, "claim", acquire_timeout) as claim_conn,
            _acquired(pool, "work", acquire_timeout) as work_conn,
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
    (30 s by default) and then raises, rather than hanging for good. The wait is
    SQLAlchemy's own and is configured on the engine; what hephkit adds is the
    name, ``HEPH-DB-503``, so that exhaustion reads as exhaustion in the response
    and in the log rather than as a generic 500.
    """

    @asynccontextmanager
    async def executors(request: Any) -> AsyncIterator[Executors]:
        async with (
            _connected(engine, "claim") as claim_conn,
            _connected(engine, "work") as work_conn,
        ):
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
