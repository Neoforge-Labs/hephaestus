"""The idempotency record store: the table of 2.3, the executor port, and ``claim()``.

The table's columns and the constraints rule 6 asks for come first, then the two
adapters against the port, then the decision table of 2.3 to 2.8.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from hephkit.errors import HephError
from hephkit.idempotency import _sql
from hephkit.idempotency.adapters import AsyncpgExecutor, SQLAlchemyExecutor
from hephkit.idempotency.ports import Executor, Proceed, Replay
from hephkit.idempotency.store import (
    IdempotencyStateError,
    IdempotencyStore,
    RecordReleased,
)


def _normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


async def test_ddl_creates_a_table_with_the_section_2_columns(pg_conn):
    await pg_conn.execute(_sql.DDL)
    cols = {
        r["column_name"]: r["data_type"]
        for r in await pg_conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'heph_idempotency' AND table_schema = current_schema()"
        )
    }
    assert cols["scope"] == "text" and cols["key"] == "text"
    assert cols["fingerprint"] == "text" and cols["kind"] == "text"
    assert cols["state"] == "text"
    assert cols["created_at"] == "timestamp with time zone"
    assert cols["lease_expires_at"] == "timestamp with time zone"
    assert cols["response_status"] == "integer"
    assert cols["response_body"] == "bytea"
    assert cols["response_media_type"] == "text"


async def test_ddl_is_idempotent(pg_conn):
    await pg_conn.execute(_sql.DDL)
    await pg_conn.execute(_sql.DDL)


async def test_the_primary_key_is_scope_and_key(pg_conn):
    insert = (
        "INSERT INTO heph_idempotency (scope, key, fingerprint, kind, state, lease_expires_at) "
        "VALUES ($1, $2, 'sha256:x', 'http', 'in_flight', now())"
    )
    await pg_conn.execute(insert, "", "k")
    await pg_conn.execute(insert, "other", "k")  # same key, different scope: fine
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await pg_conn.execute(insert, "", "k")


async def test_an_in_flight_row_without_a_lease_is_refused(pg_conn):
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pg_conn.execute(
            "INSERT INTO heph_idempotency (scope, key, fingerprint, kind, state) "
            "VALUES ('', 'k', 'sha256:x', 'http', 'in_flight')"
        )


async def test_a_completed_http_row_without_a_status_is_refused(pg_conn):
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pg_conn.execute(
            "INSERT INTO heph_idempotency (scope, key, fingerprint, kind, state) "
            "VALUES ('', 'k', 'sha256:x', 'http', 'completed')"
        )


async def test_a_completed_event_row_needs_no_response(pg_conn):
    await pg_conn.execute(
        "INSERT INTO heph_idempotency (scope, key, fingerprint, kind, state) "
        "VALUES ('', 'k', 'sha256:x', 'event', 'completed')"
    )


@pytest.mark.parametrize(
    ("kind", "state"), [("grpc", "completed"), ("event", "pending")], ids=["kind", "state"]
)
async def test_unknown_kind_or_state_is_refused(pg_conn, kind, state):
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pg_conn.execute(
            "INSERT INTO heph_idempotency "
            "(scope, key, fingerprint, kind, state, lease_expires_at, response_status) "
            "VALUES ('', 'k', 'sha256:x', $1, $2, now(), 200)",
            kind,
            state,
        )


async def test_the_retention_index_exists(pg_conn):
    row = await pg_conn.fetchrow(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'heph_idempotency_created_at_idx'"
    )
    assert row is not None and "(created_at)" in row["indexdef"]


def test_the_ddl_file_and_the_constant_are_the_same_sql():
    on_disk = (Path(_sql.__file__).parent / "schema.sql").read_text(encoding="utf-8")
    assert _normalise(_sql.DDL) == _normalise(on_disk)
    assert "CREATE TABLE IF NOT EXISTS heph_idempotency" in _sql.DDL


# --- the executor port: both adapters run the caller's SQL inside the caller's transaction ---

INSERT_SQL = (
    "INSERT INTO heph_idempotency (scope, key, fingerprint, kind, state, lease_expires_at) "
    "VALUES ($1, $2, $3, 'http', 'in_flight', now())"
)


async def test_a_rolled_back_transaction_takes_the_executors_writes_with_it(adapter):
    # Design finding 1: writes on the raw driver handle under SQLAlchemy commit
    # on their own and survive this rollback. Only the commit half of the
    # contract would have caught nothing.
    async with adapter.transaction() as ex:
        await ex.execute(INSERT_SQL, ["", "rolled-back", "sha256:x"])
        await adapter.rollback()
    assert await adapter.count_keys() == 0


async def test_a_committed_transaction_keeps_them(adapter):
    async with adapter.transaction() as ex:
        await ex.execute(INSERT_SQL, ["", "committed", "sha256:x"])
        await adapter.commit()
    assert await adapter.count_keys() == 1
    row = await adapter.fetch_key("", "committed")
    assert row is not None and row["fingerprint"] == "sha256:x"


async def test_the_executors_writes_are_invisible_to_others_until_commit(adapter):
    async with adapter.transaction() as ex:
        await ex.execute(INSERT_SQL, ["", "pending", "sha256:x"])
        assert await adapter.count_keys() == 0
        await adapter.commit()
    assert await adapter.count_keys() == 1


async def test_a_key_containing_a_colon_and_a_percent_is_a_value_not_a_template(adapter):
    key = "urn:uuid:7b%2Dff:name"  # every character is VCHAR, so 2.1 allows it
    async with adapter.transaction() as ex:
        await ex.execute(INSERT_SQL, ["", key, "sha256:x"])
    row = await adapter.fetch_key("", key)
    assert row is not None and row["key"] == key


async def test_execute_returns_the_number_of_rows_affected(adapter):
    async with adapter.transaction() as ex:
        assert await ex.execute(INSERT_SQL, ["", "a", "sha256:x"]) == 1
        assert await ex.execute(INSERT_SQL, ["", "b", "sha256:x"]) == 1
        n = await ex.execute("DELETE FROM heph_idempotency WHERE scope = $1", [""])
        assert n == 2
        assert await ex.execute("DELETE FROM heph_idempotency WHERE scope = $1", [""]) == 0


async def test_fetch_one_returns_a_mapping_or_none(adapter):
    async with adapter.transaction() as ex:
        await ex.execute(INSERT_SQL, ["s", "k", "sha256:x"])
        row = await ex.fetch_one(
            "SELECT scope, key, state FROM heph_idempotency WHERE scope = $1 AND key = $2",
            ["s", "k"],
        )
        assert row is not None
        assert (row["scope"], row["key"], row["state"]) == ("s", "k", "in_flight")
        missing = await ex.fetch_one(
            "SELECT key FROM heph_idempotency WHERE scope = $1 AND key = $2", ["s", "nope"]
        )
        assert missing is None


async def test_a_placeholder_reused_in_one_statement_binds_one_value(adapter):
    async with adapter.transaction() as ex:
        await ex.execute(INSERT_SQL, ["x", "x", "sha256:x"])
        row = await ex.fetch_one(
            "SELECT count(*) AS n FROM heph_idempotency WHERE scope = $1 AND key = $1", ["x"]
        )
        assert row is not None and row["n"] == 1


async def test_a_cast_directly_after_a_placeholder_survives_the_rewrite(adapter):
    async with adapter.transaction() as ex:
        row = await ex.fetch_one("SELECT $1::text AS v", ["a:b"])
        assert row is not None and row["v"] == "a:b"


async def test_a_colon_after_a_placeholder_is_not_read_as_a_bind(adapter):
    async with adapter.transaction() as ex:
        row = await ex.fetch_one("SELECT (ARRAY[10, 20, 30, 40])[$1:$2] AS v", [2, 3])
        assert row is not None and list(row["v"]) == [20, 30]


async def test_an_unreadable_command_status_is_an_error_not_zero_rows():
    from hephkit.idempotency.adapters import AsyncpgExecutor

    class Conn:
        async def execute(self, sql, *params):
            return "BOGUS"

    with pytest.raises(ValueError, match="BOGUS"):
        await AsyncpgExecutor(Conn()).execute("x", [])  # type: ignore[arg-type]


async def test_response_body_round_trips_bytes_that_are_not_utf8(adapter):
    body = bytes(range(256))  # not valid UTF-8, so jsonb or text would reject or alter it
    async with adapter.transaction() as ex:
        await ex.execute(
            "INSERT INTO heph_idempotency "
            "(scope, key, fingerprint, kind, state, response_status, response_body) "
            "VALUES ($1, $2, $3, 'http', 'completed', 200, $4)",
            ["", "bin", "sha256:x", body],
        )
        row = await ex.fetch_one(
            "SELECT response_body FROM heph_idempotency WHERE scope = $1 AND key = $2",
            ["", "bin"],
        )
        assert row is not None and bytes(row["response_body"]) == body
    stored = await adapter.fetch_key("", "bin")
    assert stored is not None and bytes(stored["response_body"]) == body


@pytest.mark.parametrize("module", ["asyncpg", "sqlalchemy"])
def test_a_missing_driver_names_the_extra(monkeypatch, module):
    import builtins

    from hephkit.idempotency import adapters

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == module or name.startswith(module + "."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    cls = adapters.AsyncpgExecutor if module == "asyncpg" else adapters.SQLAlchemyExecutor
    with pytest.raises(ImportError, match=r"hephkit\[(postgres|sqlalchemy)\]"):
        cls(object())


# --- claim(): the decision table of 2.3 to 2.8 ------------------------------
#
# `claim()` wants a connection with **no outer transaction**, because its
# statements commit as they run: that is the opposite of the `adapter` fixture's
# contract, so these tests open their own connections through `claimer`. A
# record that is still invisible protects nothing, and several tests below claim
# the same key from a second connection to prove the record is really there.

_UUID7 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


class a_proceed:  # noqa: N801  (reads as a constructor at the call site)
    """Equal to a ``Proceed`` whose ``attempt_id`` is a lowercase UUIDv7 string.

    ``attempt_id=ANY`` would also accept ``None`` or any string, and the id is
    the one thing complete() and release() are guarded on.
    """

    def __init__(self, *, taken_over: bool) -> None:
        self._taken_over = taken_over

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Proceed)
            and other.taken_over is self._taken_over
            and isinstance(other.attempt_id, str)
            and _UUID7.fullmatch(other.attempt_id) is not None
        )

    def __repr__(self) -> str:
        return f"Proceed(taken_over={self._taken_over}, attempt_id=<uuid7>)"


FP = "sha256:" + "a" * 64
OTHER_FP = "sha256:" + "b" * 64

_SEED = (
    "INSERT INTO heph_idempotency (scope, key, fingerprint, kind, state, created_at, "
    "lease_expires_at, response_status, response_body, response_media_type) "
    "VALUES ($1, $2, $3, $4, $5, now() - $6::interval, now() + $7::interval, $8, $9, $10)"
)


@asynccontextmanager
async def _asyncpg_executor(dsn: str) -> AsyncIterator[Executor]:
    conn = await asyncpg.connect(dsn)
    try:
        yield AsyncpgExecutor(conn)
    finally:
        await conn.close()


@asynccontextmanager
async def _sqlalchemy_executor(dsn: str) -> AsyncIterator[Executor]:
    # AUTOCOMMIT is how a SQLAlchemy caller says "no outer transaction": without
    # it `engine.connect()` begins one lazily, and claim's record would stay
    # invisible to everyone else until the caller committed.
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://", 1), isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as conn:
            yield SQLAlchemyExecutor(conn)
    finally:
        await engine.dispose()


class _Claimer:
    """Hands out executors on fresh connections with no transaction open.

    Each ``claim()`` gets a connection of its own, so two of them gathered are
    genuinely concurrent rather than two awaits on one connection. Reads and
    seeds go through ``pg_conn``, a connection of its own, so a read sees only
    what claim has committed.
    """

    def __init__(
        self,
        open_executor: Callable[[], AbstractAsyncContextManager[Executor]],
        reader: asyncpg.Connection,
        store: IdempotencyStore,
    ) -> None:
        self.executor = open_executor
        self.reader = reader
        self.store = store

    async def claim(
        self,
        *,
        store: IdempotencyStore | None = None,
        barrier: asyncio.Barrier | None = None,
        **kwargs: Any,
    ) -> Proceed | Replay:
        # A barrier held until every connection is open is what makes two
        # gathered claims overlap on purpose: without it a run where the first
        # finishes before the second connects passes just the same.
        async with self.executor() as ex:
            if barrier is not None:
                await barrier.wait()
            return await (store or self.store).claim(ex, **kwargs)

    async def seed(
        self,
        *,
        scope: str = "",
        key: str = "k",
        fingerprint: str = FP,
        kind: str = "http",
        state: str = "in_flight",
        age: timedelta = timedelta(0),
        lease: timedelta | None = timedelta(seconds=60),
        status: int | None = None,
        body: bytes | None = None,
        media_type: str | None = None,
    ) -> None:
        await self.reader.execute(
            _SEED, scope, key, fingerprint, kind, state, age, lease, status, body, media_type
        )

    async def count_keys(self) -> int:
        return int(await self.reader.fetchval("SELECT count(*) FROM heph_idempotency"))

    async def row(self, scope: str = "", key: str = "k") -> asyncpg.Record | None:
        return await self.reader.fetchrow(
            "SELECT *, lease_expires_at - now() AS lease_left, now() - created_at AS age "
            "FROM heph_idempotency WHERE scope = $1 AND key = $2",
            scope,
            key,
        )


@pytest.fixture(params=["asyncpg", "sqlalchemy"])
def claimer(request, pg_conn: asyncpg.Connection, postgres_dsn: str) -> _Claimer:
    """Every claim test runs once per driver stack."""
    opener = _asyncpg_executor if request.param == "asyncpg" else _sqlalchemy_executor
    return _Claimer(lambda: opener(postgres_dsn), pg_conn, IdempotencyStore())


# One test per row of the table.


@pytest.mark.parametrize("kind", ["http", "event"])
async def test_a_free_key_proceeds_and_leaves_a_leased_in_flight_record(claimer, kind):
    """Spec 2.3: no live record, so the operation runs."""
    assert await claimer.claim(scope="t1", key="k", fingerprint=FP, kind=kind) == a_proceed(taken_over=False)
    row = await claimer.row("t1", "k")
    assert row is not None
    assert (row["fingerprint"], row["kind"], row["state"]) == (FP, kind, "in_flight")
    assert timedelta(seconds=50) < row["lease_left"] <= timedelta(seconds=60)


@pytest.mark.parametrize(
    "seeded",
    [
        pytest.param({"state": "completed", "lease": None, "status": 201}, id="completed"),
        pytest.param({"lease": timedelta(seconds=-5)}, id="in-flight-lease-expired"),
    ],
)
async def test_a_differing_fingerprint_is_422_whatever_the_state(claimer, seeded):
    """Spec 2.6: one key means one payload, in flight or complete."""
    await claimer.seed(fingerprint=OTHER_FP, **seeded)
    with pytest.raises(HephError) as exc:
        await claimer.claim(scope="", key="k", fingerprint=FP)
    assert exc.value.code == "HEPH-IDEMP-422"
    row = await claimer.row()
    assert row is not None and row["fingerprint"] == OTHER_FP  # 2.8: never replaced


@pytest.mark.parametrize(
    ("status", "body", "media_type"),
    [(201, b'{"id":1}', "application/json"), (204, None, None)],
    ids=["with-a-body", "without-one"],
)
async def test_a_completed_record_replays_the_stored_response(claimer, status, body, media_type):
    """Spec 2.4: the operation MUST NOT run again."""
    await claimer.seed(
        state="completed", lease=None, status=status, body=body, media_type=media_type
    )
    assert await claimer.claim(scope="", key="k", fingerprint=FP) == Replay(
        status=status, body=body or b"", media_type=media_type
    )
    row = await claimer.row()
    assert row is not None and row["state"] == "completed"  # the replay changed nothing


async def test_a_live_lease_is_409(claimer):
    """Spec 2.5: the original is still being processed, so retry later."""
    await claimer.seed()
    with pytest.raises(HephError) as exc:
        await claimer.claim(scope="", key="k", fingerprint=FP)
    assert exc.value.code == "HEPH-IDEMP-409"


async def test_an_expired_lease_is_taken_over_with_a_new_lease(claimer):
    """Spec 2.8: a crashed worker must not wedge a key for the retention window."""
    await claimer.seed(age=timedelta(hours=1), lease=timedelta(seconds=-5))
    assert await claimer.claim(scope="", key="k", fingerprint=FP) == a_proceed(taken_over=True)
    row = await claimer.row()
    assert row is not None
    assert timedelta(seconds=50) < row["lease_left"] <= timedelta(seconds=60)
    assert row["fingerprint"] == FP  # 2.8's last sentence: never replaced
    # A takeover continues the record rather than starting a new one, so
    # retention keeps running from the original creation.
    assert row["age"] > timedelta(minutes=59)


async def test_a_record_past_retention_is_treated_as_new(claimer):
    """Spec 2.7: after expiry the key is new, so 2.6 does not apply to it either."""
    await claimer.seed(
        fingerprint=OTHER_FP,
        kind="event",
        state="completed",
        age=timedelta(hours=25),
        lease=None,
        status=201,
        body=b"old",
        media_type="application/json",
    )
    assert await claimer.claim(scope="", key="k", fingerprint=FP) == a_proceed(taken_over=False)
    row = await claimer.row()
    assert row is not None
    assert (row["fingerprint"], row["kind"], row["state"]) == (FP, "http", "in_flight")
    assert row["age"] < timedelta(minutes=1)  # the record restarted
    assert row["response_status"] is None  # and the aged-out response is gone
    assert row["response_body"] is None and row["response_media_type"] is None
    assert await claimer.count_keys() == 1


async def test_a_live_lease_past_retention_is_409_not_a_new_key(claimer):
    """Spec 2.7: retention expiry applies only when no attempt holds the key.

    2.8's takeover leaves created_at alone, so a record taken over just before
    the retention boundary is older than retention while a handler still holds
    a live lease. Treating it as new would hand the key to a second request and
    leave the first handler's complete() writing into a row it no longer owns.
    """
    await claimer.seed(age=timedelta(hours=25), state="in_flight", lease=timedelta(seconds=60))
    with pytest.raises(HephError) as exc:
        await claimer.claim(scope="", key="k", fingerprint=OTHER_FP)
    assert exc.value.code == "HEPH-IDEMP-422"  # 2.6 still comes first
    with pytest.raises(HephError) as exc:
        await claimer.claim(scope="", key="k", fingerprint=FP)
    assert exc.value.code == "HEPH-IDEMP-409"
    row = await claimer.row()
    assert row is not None
    assert row["fingerprint"] == FP  # the record was not reset
    assert row["age"] > timedelta(hours=24)  # created_at untouched
    assert timedelta(seconds=50) < row["lease_left"] <= timedelta(seconds=60)
    assert await claimer.count_keys() == 1


async def test_an_in_flight_record_past_retention_with_a_dead_lease_is_new(claimer):
    """And once no attempt holds the key, 2.7 applies to an in_flight record too.

    Not 2.8: an aged-out record is replaced rather than taken over, so the
    fingerprint is the new request's and the window starts again.
    """
    await claimer.seed(
        fingerprint=OTHER_FP, age=timedelta(hours=25), lease=timedelta(seconds=-5)
    )
    assert await claimer.claim(scope="", key="k", fingerprint=FP) == a_proceed(taken_over=False)
    row = await claimer.row()
    assert row is not None
    assert row["fingerprint"] == FP
    assert row["age"] < timedelta(minutes=1)


# The three that matter most, plus the empty scope.


async def test_exactly_one_of_two_concurrent_first_requests_proceeds(claimer):
    """Spec 2.3. Two genuinely concurrent transactions, not two awaits on one."""
    barrier = asyncio.Barrier(2)
    outcomes = await asyncio.gather(
        claimer.claim(barrier=barrier, scope="", key="k", fingerprint=FP),
        claimer.claim(barrier=barrier, scope="", key="k", fingerprint=FP),
        return_exceptions=True,
    )
    assert [o for o in outcomes if isinstance(o, Proceed)] == [a_proceed(taken_over=False)]
    assert [o.code for o in outcomes if isinstance(o, HephError)] == ["HEPH-IDEMP-409"]
    assert await claimer.count_keys() == 1


async def test_exactly_one_of_two_concurrent_takeovers_proceeds(claimer):
    """Spec 2.8: an expired lease is one record to win, not a free-for-all."""
    await claimer.seed(lease=timedelta(seconds=-5))
    barrier = asyncio.Barrier(2)
    outcomes = await asyncio.gather(
        claimer.claim(barrier=barrier, scope="", key="k", fingerprint=FP),
        claimer.claim(barrier=barrier, scope="", key="k", fingerprint=FP),
        return_exceptions=True,
    )
    assert [o for o in outcomes if isinstance(o, Proceed)] == [a_proceed(taken_over=True)]
    assert [o.code for o in outcomes if isinstance(o, HephError)] == ["HEPH-IDEMP-409"]


async def test_a_mismatched_fingerprint_beats_a_live_lease(claimer):
    """Spec 2.6 takes precedence over 2.5: a client bug, not a retry-later."""
    await claimer.seed(fingerprint=OTHER_FP, lease=timedelta(seconds=60))
    with pytest.raises(HephError) as exc:
        await claimer.claim(scope="", key="k", fingerprint=FP)
    assert exc.value.code == "HEPH-IDEMP-422"


async def test_the_empty_scope_is_a_scope(claimer):
    """Two untenanted principals sharing a key still collide."""
    assert isinstance(await claimer.claim(scope="", key="k", fingerprint=FP), Proceed)
    with pytest.raises(HephError) as exc:
        await claimer.claim(scope="", key="k", fingerprint=FP)
    assert exc.value.code == "HEPH-IDEMP-409"
    assert isinstance(await claimer.claim(scope="t1", key="k", fingerprint=FP), Proceed)
    assert await claimer.count_keys() == 2


@pytest.mark.parametrize("field", ["scope", "key", "fingerprint", "kind"])
async def test_none_is_a_type_error_not_an_empty_string(claimer, field):
    """One caller mistake, one answer: without the guard each column answers differently.

    ``scope`` is the one that matters most -- coerced to ``""`` it would collapse
    every tenant into one row -- but ``fingerprint=None`` is the nastiest,
    because it is a driver error on a free key and a client-blaming 422 on a
    taken one.
    """
    kwargs: dict[str, Any] = {"scope": "", "key": "k", "fingerprint": FP, field: None}
    with pytest.raises(TypeError, match=field):
        await claimer.claim(**kwargs)
    assert await claimer.count_keys() == 0


# Retention and lease are configuration (2.7).


async def test_the_configured_lease_is_the_one_stored(claimer):
    store = IdempotencyStore(lease=timedelta(minutes=10))
    outcome = await claimer.claim(scope="", key="k", fingerprint=FP, store=store)
    assert outcome == a_proceed(taken_over=False)
    row = await claimer.row()
    assert row is not None
    assert timedelta(minutes=9) < row["lease_left"] <= timedelta(minutes=10)


async def test_a_longer_retention_keeps_a_record_the_default_would_have_aged_out(claimer):
    await claimer.seed(state="completed", lease=None, status=201, age=timedelta(hours=25))
    store = IdempotencyStore(retention=timedelta(days=7))
    assert await claimer.claim(scope="", key="k", fingerprint=FP, store=store) == Replay(
        status=201, body=b"", media_type=None
    )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"retention": timedelta(hours=23)}, "retention"),
        ({"lease": timedelta(0)}, "lease"),
        ({"lease": timedelta(seconds=-1)}, "lease"),
    ],
)
def test_a_retention_or_lease_that_breaks_the_spec_is_refused(kwargs, match):
    # 2.7: retention MAY be configured longer, so a shorter one is not a
    # setting. A lease that has already expired makes 2.5 unreachable.
    with pytest.raises(ValueError, match=match):
        IdempotencyStore(**kwargs)


# The record vanishing between claim's two statements.


class _ChurnsTheRecord:
    """Re-creates the record before every insert, removing it before every read.

    A concurrent ``release()`` or retention purge is the one thing that can make
    claim's read find nothing, and this is that window held open. ``once`` lets
    the second pass through, so claim recovers; otherwise every pass is churned
    and claim has to give up rather than loop.
    """

    def __init__(self, inner: Executor, reader: asyncpg.Connection, *, once: bool) -> None:
        self._inner = inner
        self._reader = reader
        self._once = once
        self.churns = 0

    async def fetch_one(self, sql: str, params: Sequence[Any]) -> Mapping[str, Any] | None:
        if not (self._once and self.churns >= 2):
            self.churns += 1
            if "ON CONFLICT" in sql:
                await self._reader.execute(
                    _SEED, "", "k", FP, "http", "in_flight", timedelta(0),
                    timedelta(seconds=60), None, None, None,
                )
            else:
                await self._reader.execute("DELETE FROM heph_idempotency")
        return await self._inner.fetch_one(sql, params)

    async def execute(self, sql: str, params: Sequence[Any]) -> int:
        return await self._inner.execute(sql, params)


async def test_a_record_that_vanishes_before_the_read_is_claimed_again(claimer):
    async with claimer.executor() as inner:
        churn = _ChurnsTheRecord(inner, claimer.reader, once=True)
        outcome = await claimer.store.claim(churn, scope="", key="k", fingerprint=FP)
    assert outcome == a_proceed(taken_over=False)
    assert churn.churns == 2


async def test_a_key_that_keeps_vanishing_is_409_rather_than_a_loop(claimer):
    async with claimer.executor() as inner:
        churn = _ChurnsTheRecord(inner, claimer.reader, once=False)
        with pytest.raises(HephError) as exc:
            await claimer.store.claim(churn, scope="", key="k", fingerprint=FP)
    assert exc.value.code == "HEPH-IDEMP-409"
    assert churn.churns == 4  # two passes, and no more


# --- idempotent_record(): the default way out is release --------------------
#
# Two executors, because the boundaries differ: `claimer.executor()` has no
# transaction open (claim and release), `adapter.transaction()` is the handler's
# own, rolled back when an exception passes through it, as a real handler's is.


@asynccontextmanager
async def _record(
    claimer, adapter, *, key: str = "k", fingerprint: str = FP, kind: str = "http", **extra: Any
):
    async with claimer.executor() as claim_ex, adapter.transaction() as work_ex:
        async with claimer.store.idempotent_record(
            claim_ex=claim_ex, work_ex=work_ex, scope="", key=key, fingerprint=fingerprint, kind=kind, **extra
        ) as rec:
            yield rec


@pytest.mark.parametrize("kind", ["http", "event"])
async def test_a_finished_block_stores_its_response_with_the_work_and_replays_it(
    claimer, adapter, kind
):
    async with _record(claimer, adapter, kind=kind) as rec:
        assert rec.replay is None and rec.taken_over is False
        rec.finish(201, b'{"id":1}', "application/json")
    row = await claimer.row()
    assert row is not None and row["state"] == "completed"
    assert (row["response_status"], bytes(row["response_body"])) == (201, b'{"id":1}')
    assert row["response_media_type"] == "application/json"
    assert await claimer.claim(scope="", key="k", fingerprint=FP, kind=kind) == Replay(
        201, b'{"id":1}', "application/json"
    )


async def test_the_stored_response_commits_and_rolls_back_with_the_handlers_work(claimer, adapter):
    """finish() is written to work_ex: if the caller then rolls back, the record is not completed."""
    async with claimer.executor() as claim_ex, adapter.transaction() as work_ex:
        async with claimer.store.idempotent_record(
            claim_ex=claim_ex, work_ex=work_ex, scope="", key="k", fingerprint=FP
        ) as rec:
            rec.finish(201, b"{}")
        await adapter.rollback()
    row = await claimer.row()
    assert row is not None and row["state"] == "in_flight" and row["response_status"] is None


async def test_a_block_that_never_finishes_releases_rather_than_wedging(claimer, adapter):
    """An unknown outcome is a removed record (2.8), reported as RecordReleased.

    The report is not decoration: this exit must reach the caller's `executors`
    as an exception, or a factory that commits on a clean exit would commit the
    handler's work with nothing recording it.
    """
    with pytest.raises(RecordReleased, match="no outcome"):
        async with _record(claimer, adapter):
            pass
    assert await claimer.count_keys() == 0
    assert await claimer.claim(scope="", key="k", fingerprint=FP) == a_proceed(taken_over=False)


@pytest.mark.parametrize("status", [500, 503])
async def test_a_finish_at_500_or_above_releases(claimer, adapter, status):
    with pytest.raises(RecordReleased, match=str(status)):
        async with _record(claimer, adapter) as rec:
            rec.finish(status, b"boom")
    assert await claimer.count_keys() == 0


@pytest.mark.parametrize("outcome", [None, 503], ids=["no-finish", "finish-503"])
async def test_a_release_on_the_way_out_takes_the_handlers_write_with_it(
    claimer, adapter, outcome
):
    """Both driver stacks: the released record and the handler's row go together.

    The write goes through work_ex, the handler's own executor, so this is the
    guarantee from the other side of `complete()`: if the record is released,
    nothing it would have described may survive. `adapter.transaction()` commits
    on a clean exit, which is why the release has to raise.
    """
    # The raises sits outside the work transaction on purpose: it is the
    # exception passing through that context manager that rolls the write back.
    with pytest.raises(RecordReleased):
        async with claimer.executor() as claim_ex, adapter.transaction() as work_ex:
            async with claimer.store.idempotent_record(
                claim_ex=claim_ex, work_ex=work_ex, scope="", key="k", fingerprint=FP
            ) as rec:
                await work_ex.execute(INSERT_SQL, ["", "the-handlers-row", FP])
                if outcome is not None:
                    rec.finish(outcome, b"boom")
    assert await claimer.count_keys() == 0  # neither the record nor the row


async def test_an_exception_inside_the_block_releases_the_record(claimer, adapter):
    with pytest.raises(RuntimeError, match="boom"):
        async with _record(claimer, adapter):
            raise RuntimeError("boom")
    assert await claimer.count_keys() == 0


async def test_an_exception_after_finish_releases_rather_than_storing(claimer, adapter):
    """A stated outcome does not survive the handler failing afterwards."""
    with pytest.raises(RuntimeError):
        async with _record(claimer, adapter) as rec:
            rec.finish(201, b"{}")
            raise RuntimeError("failed after finishing")
    assert await claimer.count_keys() == 0


async def test_a_cancellation_releases_the_record(claimer, adapter):
    with pytest.raises(asyncio.CancelledError):
        async with _record(claimer, adapter):
            raise asyncio.CancelledError
    assert await claimer.count_keys() == 0


async def test_a_sub_500_HephError_is_stored_not_released(claimer, adapter):
    """Review Focus 2. A raised 422 is still a real outcome of the operation (2.8).

    `except Exception: release` is the obvious implementation and it is wrong.
    The exception also rolls the handler's transaction back, so the record has
    to reach the table through the executor that is not in it.
    """
    with pytest.raises(HephError) as exc:
        async with _record(claimer, adapter):
            raise HephError("HEPH-VAL-422", "bad field")
    assert exc.value.code == "HEPH-VAL-422"
    row = await claimer.row()
    assert row is not None
    assert (row["state"], row["response_status"]) == ("completed", 422)
    assert await claimer.claim(scope="", key="k", fingerprint=FP) == Replay(422, b"", None)


async def test_a_renderer_supplies_the_body_stored_with_a_raised_4xx(claimer, adapter):
    """The record is sealed on the way out, so the web layer's body must be handed in."""
    seen: list[str] = []

    def render(exc: HephError) -> tuple[bytes, str | None]:
        seen.append(exc.code)
        return b'{"title":"bad"}', "application/problem+json"

    with pytest.raises(HephError):
        async with _record(claimer, adapter, render_error=render):
            raise HephError("HEPH-VAL-422", "bad field")
    assert seen == ["HEPH-VAL-422"]
    row = await claimer.row()
    assert row is not None and bytes(row["response_body"]) == b'{"title":"bad"}'
    assert await claimer.claim(scope="", key="k", fingerprint=FP) == Replay(
        422, b'{"title":"bad"}', "application/problem+json"
    )


async def test_a_renderer_that_raises_releases_the_record_and_its_error_surfaces(claimer, adapter):
    """Raised inside the except arm, it would otherwise skip the release and wedge the key."""

    def render(exc: HephError) -> tuple[bytes, str | None]:
        raise KeyError("unexpected extension")

    with pytest.raises(KeyError) as raised:
        async with _record(claimer, adapter, render_error=render):
            raise HephError("HEPH-VAL-422", "bad field")
    assert isinstance(raised.value.__context__, HephError)
    assert await claimer.count_keys() == 0
    assert await claimer.claim(scope="", key="k", fingerprint=FP) == a_proceed(taken_over=False)


async def test_a_renderer_is_not_consulted_for_a_release(claimer, adapter):
    def render(exc: HephError) -> tuple[bytes, str | None]:
        raise AssertionError("a 5xx is released, not rendered")

    with pytest.raises(HephError):
        async with _record(claimer, adapter, render_error=render):
            raise HephError("HEPH-GEN-500")
    assert await claimer.count_keys() == 0


async def test_a_HephError_of_500_or_above_releases(claimer, adapter):
    with pytest.raises(HephError):
        async with _record(claimer, adapter):
            raise HephError("HEPH-GEN-500")
    assert await claimer.count_keys() == 0


async def test_a_replay_is_handed_to_the_caller_and_the_work_is_skipped(claimer, adapter):
    async with _record(claimer, adapter) as first:
        first.finish(201, b"{}", "application/json")
    ran: list[str] = []
    async with _record(claimer, adapter) as rec:
        ran.append("entered")
        assert rec.replay == Replay(201, b"{}", "application/json")
        if rec.replay is None:
            ran.append("work")
    assert ran == ["entered"]  # runs once, with replay set, and does no work
    with pytest.raises(RuntimeError, match="replay"):
        rec.finish(200, b"")
    row = await claimer.row()
    assert row is not None and row["state"] == "completed" and row["response_status"] == 201


async def test_a_block_over_a_replay_that_raises_leaves_the_stored_record(claimer, adapter):
    await claimer.seed(state="completed", lease=None, status=200, body=b"ok")
    with pytest.raises(RuntimeError):
        async with _record(claimer, adapter) as rec:
            assert rec.replay is not None
            raise RuntimeError("after replay")
    row = await claimer.row()
    assert row is not None and row["state"] == "completed"


async def test_a_claim_that_refuses_raises_from_the_context_and_the_block_never_runs(claimer, adapter):
    await claimer.seed()  # a live lease
    ran = False
    with pytest.raises(HephError) as exc:
        async with _record(claimer, adapter):
            ran = True
    assert exc.value.code == "HEPH-IDEMP-409" and ran is False
    row = await claimer.row()
    assert row is not None and row["state"] == "in_flight"  # the owner's record, untouched

    with pytest.raises(HephError) as exc:
        async with _record(claimer, adapter, fingerprint=OTHER_FP):
            ran = True
    assert exc.value.code == "HEPH-IDEMP-422" and ran is False


async def test_a_takeover_is_reported_and_the_superseded_attempt_cannot_finish(claimer, adapter):
    """The attempt token flows through the context, so callers never see it."""
    await claimer.seed(age=timedelta(hours=1), lease=timedelta(seconds=-5))
    with pytest.raises(IdempotencyStateError):
        async with _record(claimer, adapter) as a:
            assert a.taken_over is True
            # A's lease lapses while it works, and B takes the record over.
            await claimer.reader.execute(
                "UPDATE heph_idempotency SET lease_expires_at = now() - interval '1 second'"
            )
            assert await claimer.claim(scope="", key="k", fingerprint=FP) == a_proceed(taken_over=True)
            a.finish(201, b"from A")
    row = await claimer.row()
    # B's record is neither completed with A's response nor released by A.
    assert row is not None and row["state"] == "in_flight" and row["response_body"] is None


class _Fails:
    """An executor whose every write fails, standing in for a broken work connection."""

    async def fetch_one(self, sql, params):
        raise AssertionError("not used")

    async def execute(self, sql, params):
        raise ConnectionError("work connection lost")


async def test_a_record_that_cannot_be_written_is_released_and_the_error_propagates(claimer):
    with pytest.raises(ConnectionError):
        async with claimer.executor() as claim_ex:
            async with claimer.store.idempotent_record(
                claim_ex=claim_ex, work_ex=_Fails(), scope="", key="k", fingerprint=FP
            ) as rec:
                rec.finish(201, b"{}")
    assert await claimer.count_keys() == 0
