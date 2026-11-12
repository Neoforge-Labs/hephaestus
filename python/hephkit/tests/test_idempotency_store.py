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
            "WHERE table_name = 'heph_idempotency'"
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
