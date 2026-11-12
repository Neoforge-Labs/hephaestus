"""The far end of a record's life: ``complete()``, ``release()`` and the retention sweep.

``test_idempotency_store.py`` covers the table, the adapters and ``claim()``;
this file covers what happens once ``claim()`` has said ``Proceed``. The thing
under test is one guarantee: **a stored response always describes work that
committed.** ``complete()`` therefore runs in the caller's transaction, beside
the handler's own writes, and ``release()`` runs in a transaction of its own,
because the handler's has just been abandoned.

Aging a record means backdating ``created_at``. Retention cannot be shortened to
age one, because the store refuses anything under 24 hours (spec 2.7).
"""

# ruff: noqa: F811  (a fixture imported by name is redefined by the argument that uses it)
from __future__ import annotations

from datetime import timedelta

import asyncpg
import pytest

# The claimer machinery lives in the claim tests; importing it keeps one copy.
from test_idempotency_store import _SEED, FP, claimer  # noqa: F401

from hephkit.idempotency.adapters import AsyncpgExecutor
from hephkit.idempotency.ports import Proceed, Replay
from hephkit.idempotency.store import IdempotencyStore

STORE = IdempotencyStore()
DAY = timedelta(hours=24)


async def _seed(
    conn: asyncpg.Connection,
    key: str = "k",
    *,
    state: str = "in_flight",
    lease: timedelta | None = timedelta(seconds=60),
    status: int | None = None,
    body: bytes | None = None,
) -> None:
    await conn.execute(_SEED, "", key, FP, "http", state, timedelta(0), lease, status, body, None)


async def _claim(dsn: str) -> Proceed | Replay:
    """A claim on a connection of its own with no transaction open, as claim() requires."""
    conn = await asyncpg.connect(dsn)
    try:
        return await STORE.claim(AsyncpgExecutor(conn), scope="", key="k", fingerprint=FP)
    finally:
        await conn.close()


# complete(): in the caller's transaction.


async def test_completing_stores_the_response_and_a_claim_replays_it(
    adapter, pg_conn, postgres_dsn
):
    await _seed(pg_conn)
    async with adapter.transaction() as ex:
        await STORE.complete(
            ex, scope="", key="k", status=201, body=b'{"id":1}', media_type="application/json"
        )
    row = await adapter.fetch_key("", "k")
    assert row["state"] == "completed"
    assert (row["response_status"], bytes(row["response_body"])) == (201, b'{"id":1}')
    assert row["response_media_type"] == "application/json"
    assert row["lease_expires_at"] is None
    assert await _claim(postgres_dsn) == Replay(201, b'{"id":1}', "application/json")


async def test_a_4xx_is_stored_and_replayed_like_any_other_outcome(adapter, pg_conn, postgres_dsn):
    """Spec 2.8: a 4xx is a real result of the operation, not a failure to retry."""
    await _seed(pg_conn)
    async with adapter.transaction() as ex:
        await STORE.complete(ex, scope="", key="k", status=422, body=b'{"detail":"no"}')
    assert await _claim(postgres_dsn) == Replay(422, b'{"detail":"no"}', None)


async def test_an_event_completes_with_status_204_and_no_body(adapter, pg_conn, postgres_dsn):
    """The worker decorator has no response to store, so it stores 204 and nothing."""
    await _seed(pg_conn)
    async with adapter.transaction() as ex:
        await STORE.complete(ex, scope="", key="k", status=204, body=b"")
    assert await _claim(postgres_dsn) == Replay(204, b"", None)


async def test_completing_in_the_callers_transaction_rolls_back_with_it(adapter, pg_conn):
    """The guarantee worth having: a stored response describes committed work.

    ``claim()`` committed the record on its own, so after a rollback it must be
    exactly what claim left: ``in_flight``, nothing stored.
    """
    await _seed(pg_conn)
    async with adapter.transaction() as ex:
        await STORE.complete(ex, scope="", key="k", status=201, body=b"{}")
        await adapter.rollback()
    row = await adapter.fetch_key("", "k")
    assert row["state"] == "in_flight"
    assert row["response_status"] is None and row["response_body"] is None


async def test_a_completed_record_is_not_overwritten(adapter, pg_conn):
    """A second attempt that finishes late must not replace what the first one stored."""
    await _seed(pg_conn, state="completed", lease=None, status=200, body=b"first")
    async with adapter.transaction() as ex:
        await STORE.complete(ex, scope="", key="k", status=201, body=b"second")
    row = await adapter.fetch_key("", "k")
    assert (row["response_status"], bytes(row["response_body"])) == (200, b"first")


async def test_completing_a_key_that_has_no_record_creates_none(adapter):
    async with adapter.transaction() as ex:
        await STORE.complete(ex, scope="", key="gone", status=201, body=b"{}")
    assert await adapter.count_keys() == 0


@pytest.mark.parametrize("status", [99, 500, 503])
async def test_a_status_that_is_not_stored_is_refused(adapter, status):
    """Spec 2.8 stores below 500; at 500 and above the answer is release()."""
    async with adapter.transaction() as ex:
        with pytest.raises(ValueError, match="release"):
            await STORE.complete(ex, scope="", key="k", status=status, body=b"")


async def test_a_body_that_is_not_bytes_is_a_type_error(adapter):
    async with adapter.transaction() as ex:
        with pytest.raises(TypeError, match="body"):
            await STORE.complete(ex, scope="", key="k", status=200, body="text")  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["scope", "key"])
async def test_none_is_a_type_error_not_an_empty_string_on_complete_and_release(adapter, field):
    """As in claim(): a None scope coerced to "" would quietly merge every tenant's keys."""
    kwargs = {"scope": "", "key": "k", field: None}
    async with adapter.transaction() as ex:
        with pytest.raises(TypeError, match=field):
            await STORE.complete(ex, status=200, body=b"", **kwargs)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match=field):
            await STORE.release(ex, **kwargs)  # type: ignore[arg-type]


# release(): in its own transaction.


async def test_a_released_record_can_be_claimed_again(claimer):
    """A 5xx or a raised handler removes the record so the client can retry."""
    await claimer.seed()
    async with claimer.executor() as ex:
        await claimer.store.release(ex, scope="", key="k")
    assert await claimer.count_keys() == 0  # read from another connection: it committed
    assert await claimer.claim(scope="", key="k", fingerprint=FP) == Proceed(taken_over=False)


async def test_release_never_removes_a_completed_record(claimer):
    await claimer.seed(state="completed", lease=None, status=200, body=b"ok")
    async with claimer.executor() as ex:
        await claimer.store.release(ex, scope="", key="k")
    assert (await claimer.row())["state"] == "completed"


async def test_releasing_a_key_that_has_no_record_is_not_an_error(claimer):
    async with claimer.executor() as ex:
        await claimer.store.release(ex, scope="", key="gone")


# purge_expired(): the consumer schedules it; hephkit starts nothing.


async def test_purge_removes_only_rows_past_retention(claimer):
    await claimer.seed(key="old-done", state="completed", lease=None, status=200, age=DAY * 2)
    await claimer.seed(key="old-dead", lease=-timedelta(seconds=1), age=DAY * 2)
    await claimer.seed(key="new-done", state="completed", lease=None, status=200, age=DAY / 2)
    await claimer.seed(key="new-live")
    async with claimer.executor() as ex:
        removed = await claimer.store.purge_expired(ex)
    assert removed == 2
    assert await claimer.row(key="old-done") is None
    assert await claimer.row(key="old-dead") is None
    assert await claimer.row(key="new-done") is not None
    assert await claimer.row(key="new-live") is not None


async def test_purge_leaves_a_record_a_live_lease_still_holds(claimer):
    """2.7: retention expiry applies only when no attempt holds the key.

    2.8's takeover leaves created_at alone, so a record taken over near the
    retention boundary is past retention while its handler is running. Purging
    it would leave that handler's complete() writing to a row that is gone, and
    the sweep is a second route to the hole claim() already closes.
    """
    await claimer.seed(age=timedelta(hours=25), lease=timedelta(seconds=60))
    async with claimer.executor() as ex:
        removed = await claimer.store.purge_expired(ex)
    assert removed == 0
    assert (await claimer.row())["state"] == "in_flight"


async def test_purge_takes_a_past_retention_record_once_its_lease_has_lapsed(claimer):
    await claimer.seed(age=timedelta(hours=25), lease=timedelta(seconds=-1))
    async with claimer.executor() as ex:
        assert await claimer.store.purge_expired(ex) == 1
    assert await claimer.count_keys() == 0


async def test_purge_returns_zero_for_an_empty_table(claimer):
    async with claimer.executor() as ex:
        assert await claimer.store.purge_expired(ex) == 0


async def test_purge_honours_a_longer_retention(claimer):
    await claimer.seed(state="completed", lease=None, status=200, age=timedelta(hours=25))
    async with claimer.executor() as ex:
        assert await IdempotencyStore(retention=timedelta(days=2)).purge_expired(ex) == 0
    assert await claimer.count_keys() == 1
