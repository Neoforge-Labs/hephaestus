"""``idempotent`` for workers: the record store keyed on an event id, over a real Postgres."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import pytest

from hephkit.errors import HephError
from hephkit.idempotency.adapters import AsyncpgExecutor
from hephkit.idempotency.ports import Executors
from hephkit.idempotency.store import IdempotencyStore
from hephkit.idempotency.worker import idempotent

SCOPE = "tenant-1"
EVENT = {"id": "evt-1", "amount": 5, "currency": "USD"}


class _Calls:
    def __init__(self) -> None:
        self.count = 0
        self.fail = False


@pytest.fixture
def calls() -> _Calls:
    return _Calls()


@pytest.fixture
def handle(pg_conn: asyncpg.Connection, postgres_dsn: str, calls: _Calls) -> Any:
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
            raise RuntimeError("boom")
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
    calls.fail = True
    with pytest.raises(RuntimeError):
        await handle(EVENT)
    assert await pg_conn.fetchval("SELECT count(*) FROM heph_idempotency") == 0
    calls.fail = False
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
