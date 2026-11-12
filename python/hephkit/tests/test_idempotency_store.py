"""The record table of spec section 2.3: its columns and the constraints rule 6 asks for."""

from __future__ import annotations

import re
from pathlib import Path

import asyncpg
import pytest

from hephkit.idempotency import _sql


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
    assert (await adapter.fetch_key("", "committed"))["fingerprint"] == "sha256:x"


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
    assert (await adapter.fetch_key("", key))["key"] == key


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
    assert bytes((await adapter.fetch_key("", "bin"))["response_body"]) == body


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
