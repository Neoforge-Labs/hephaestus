"""``idempotent`` for workers: the record store keyed on an event id, over a real Postgres."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from hephkit.errors import HephError
from hephkit.idempotency.adapters import (
    AsyncpgExecutor,
    asyncpg_event_executors,
    asyncpg_event_work_connection,
)
from hephkit.idempotency.ports import Executors
from hephkit.idempotency.store import IdempotencyStore
from hephkit.idempotency.worker import idempotent

SCOPE = "tenant-1"
EVENT = {"id": "evt-1", "amount": 5, "currency": "USD"}


class _Calls:
    def __init__(self) -> None:
        self.count = 0
        self.fail: BaseException | None = None
        self.block: asyncio.Event | None = None
        self.entered = asyncio.Event()


@pytest.fixture
def calls() -> _Calls:
    return _Calls()


@pytest.fixture
def handle(pg_conn: asyncpg.Connection, postgres_dsn: str, calls: _Calls) -> Any:
    # pg_conn is requested only to create and truncate the table before the test.
    @asynccontextmanager
    async def executors(event: Any) -> AsyncIterator[Executors]:
        claim_conn = await asyncpg.connect(postgres_dsn)
        work_conn = await asyncpg.connect(postgres_dsn)
        tx = work_conn.transaction()
        await tx.start()
        try:
            yield Executors(AsyncpgExecutor(claim_conn), AsyncpgExecutor(work_conn))
        except BaseException:
            await tx.rollback()
            raise
        else:
            await tx.commit()
        finally:
            await claim_conn.close()
            await work_conn.close()

    @idempotent(
        IdempotencyStore(),
        scope=lambda e: SCOPE,
        event_id=lambda e: e["id"],
        executors=executors,
    )
    async def handler(event: dict[str, Any]) -> str:
        calls.count += 1
        if calls.fail:
            raise calls.fail
        if calls.block is not None:
            calls.entered.set()
            await calls.block.wait()
        return "done"

    return handler


async def test_a_redelivered_event_does_not_run_the_handler_again(handle: Any, calls: _Calls) -> None:
    assert await handle(EVENT) == "done"
    assert await handle(EVENT) is None  # a replay is a no-op that returns normally
    assert calls.count == 1


async def test_the_same_event_id_with_a_different_payload_is_422(handle: Any, calls: _Calls) -> None:
    await handle(EVENT)
    with pytest.raises(HephError) as exc:
        await handle({**EVENT, "amount": 6})
    assert exc.value.code == "HEPH-IDEMP-422"
    assert calls.count == 1


async def test_key_order_does_not_change_the_fingerprint(handle: Any, calls: _Calls) -> None:
    await handle(EVENT)
    await handle(dict(reversed(list(EVENT.items()))))
    assert calls.count == 1


async def test_a_raising_handler_releases_so_the_broker_can_redeliver(
    handle: Any, calls: _Calls, pg_conn: asyncpg.Connection
) -> None:
    calls.fail = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        await handle(EVENT)
    assert await pg_conn.fetchval("SELECT count(*) FROM heph_idempotency") == 0
    calls.fail = None
    assert await handle(EVENT) == "done"
    assert calls.count == 2


async def test_an_event_record_stores_no_response_body(handle: Any, pg_conn: asyncpg.Connection) -> None:
    await handle(EVENT)
    row = await pg_conn.fetchrow(
        "SELECT * FROM heph_idempotency WHERE scope = $1 AND key = $2", SCOPE, "evt-1"
    )
    assert row is not None
    assert row["kind"] == "event"
    assert row["state"] == "completed"
    assert row["response_status"] == 204
    assert not row["response_body"]


async def test_a_sub_500_heph_error_releases_rather_than_storing_a_4xx(
    handle: Any, calls: _Calls, pg_conn: asyncpg.Connection
) -> None:
    """A broker is not a client: a stored 4xx would make the redelivery ack work never done."""
    calls.fail = HephError("HEPH-VAL-422", "bad event")
    with pytest.raises(HephError):
        await handle(EVENT)
    assert await pg_conn.fetchval("SELECT count(*) FROM heph_idempotency") == 0
    calls.fail = None
    assert await handle(EVENT) == "done"  # re-run, not a no-op replay
    assert calls.count == 2


async def test_a_concurrent_duplicate_delivery_is_409_and_does_not_run_the_handler(
    handle: Any, calls: _Calls
) -> None:
    calls.block = asyncio.Event()
    first = asyncio.create_task(handle(EVENT))
    await asyncio.wait_for(calls.entered.wait(), 5)
    with pytest.raises(HephError) as exc:
        await handle(EVENT)
    assert exc.value.code == "HEPH-IDEMP-409"
    calls.block.set()
    assert await first == "done"
    assert calls.count == 1


# --- the shipped factory: asyncpg_event_executors ---------------------------
#
# `asyncpg_executors` reaches `request.state`, which an event has none of, so
# the worker path had no shipped factory and the docs page carried a
# hand-written one that nothing ran. These are the route factory's tests, for
# the event twin: the claim commits outside the handler's transaction, the work
# connection is reachable while the handler runs and gone afterwards, and a
# handler that raises takes its own write back with the record.


@pytest_asyncio.fixture
async def work_table(pg_conn: asyncpg.Connection) -> AsyncIterator[str]:
    """A table of the handler's own, so a write can be looked for afterwards."""
    await pg_conn.execute("CREATE TABLE IF NOT EXISTS heph_test_events (note text PRIMARY KEY)")
    await pg_conn.execute("TRUNCATE heph_test_events")
    try:
        yield "heph_test_events"
    finally:
        await pg_conn.execute("DROP TABLE IF EXISTS heph_test_events")


async def test_the_shipped_event_factory_commits_the_work_with_the_record(
    pg_conn: asyncpg.Connection, postgres_dsn: str, work_table: str
) -> None:
    """While the handler runs, another connection already sees the in_flight record.

    That is the claim committing on its own, which is what 2.5 and 2.8 need. The
    handler writes through the connection the factory hands it, so the row and
    the completed record commit together, and the redelivery replays without
    running the handler again.
    """
    pool = await asyncpg.create_pool(postgres_dsn, min_size=2, max_size=4)
    seen: list[Any] = []
    calls = 0

    @idempotent(
        IdempotencyStore(),
        scope=lambda e: SCOPE,
        event_id=lambda e: e["id"],
        executors=asyncpg_event_executors(pool),
    )
    async def handle(event: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        seen.append(await pg_conn.fetchval("SELECT state FROM heph_idempotency"))
        conn = asyncpg_event_work_connection()
        await conn.execute("INSERT INTO heph_test_events (note) VALUES ($1)", event["id"])

    try:
        await handle(EVENT)
        assert await handle(EVENT) is None  # a redelivery is a no-op
    finally:
        await pool.close()
    assert seen == ["in_flight"]
    assert calls == 1
    assert await pg_conn.fetchval("SELECT count(*) FROM heph_test_events") == 1
    row = await pg_conn.fetchrow("SELECT * FROM heph_idempotency")
    assert row is not None and (row["kind"], row["state"]) == ("event", "completed")
    # The connection went back to the pool; a late caller must not reach it.
    with pytest.raises(RuntimeError, match="no work connection"):
        asyncpg_event_work_connection()


async def test_a_raising_event_handler_takes_its_own_write_back_with_the_record(
    pg_conn: asyncpg.Connection, postgres_dsn: str, work_table: str
) -> None:
    """The release and the rollback are one outcome, as they are on a route.

    A row the broker's redelivery would find already there is the duplicate this
    module exists to prevent, so a released record must leave nothing behind.
    """
    pool = await asyncpg.create_pool(postgres_dsn, min_size=2, max_size=4)
    fail = True

    @idempotent(
        IdempotencyStore(),
        scope=lambda e: SCOPE,
        event_id=lambda e: e["id"],
        executors=asyncpg_event_executors(pool),
    )
    async def handle(event: dict[str, Any]) -> str:
        conn = asyncpg_event_work_connection()
        await conn.execute("INSERT INTO heph_test_events (note) VALUES ($1)", event["id"])
        if fail:
            raise RuntimeError("boom")
        return "done"

    try:
        with pytest.raises(RuntimeError, match="boom"):
            await handle(EVENT)
        assert await pg_conn.fetchval("SELECT count(*) FROM heph_test_events") == 0
        assert await pg_conn.fetchval("SELECT count(*) FROM heph_idempotency") == 0
        fail = False
        assert await handle(EVENT) == "done"  # the redelivery really runs
        assert await pg_conn.fetchval("SELECT count(*) FROM heph_test_events") == 1
    finally:
        await pool.close()


async def test_a_second_pool_is_used_for_the_claim_when_one_is_given(
    pg_conn: asyncpg.Connection, postgres_dsn: str
) -> None:
    """claim_pool= is the route factory's escape from the deadlock, and it is here too.

    One connection in each pool is enough for an event only if the claim comes
    out of the other one; from a single pool of one this would wait for a
    connection nobody can release and end in HEPH-DB-503.
    """
    work = await asyncpg.create_pool(postgres_dsn, min_size=1, max_size=1)
    claim = await asyncpg.create_pool(postgres_dsn, min_size=1, max_size=1)

    @idempotent(
        IdempotencyStore(),
        scope=lambda e: SCOPE,
        event_id=lambda e: e["id"],
        executors=asyncpg_event_executors(work, claim_pool=claim, acquire_timeout=1.0),
    )
    async def handle(event: dict[str, Any]) -> str:
        return "done"

    try:
        assert await handle(EVENT) == "done"
    finally:
        await work.close()
        await claim.close()
    assert await pg_conn.fetchval("SELECT state FROM heph_idempotency") == "completed"
