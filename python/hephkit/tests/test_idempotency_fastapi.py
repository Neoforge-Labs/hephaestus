"""``idempotent_route``: per-route Idempotency-Key handling over a real Postgres.

The thing under test is that a replay is *the same response*, not an equivalent
one: the same status, the same bytes and the same content type (spec 2.4). The
4xx case is the easy one to get wrong, because the store builds no body of its
own and a renderer has to be handed to it.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import httpx
import pytest
import pytest_asyncio
from pydantic import BaseModel
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from hephkit.conventions import IDEMPOTENCY_KEY
from hephkit.errors import HephError
from hephkit.errors.fastapi import install_error_handlers
from hephkit.idempotency.adapters import (
    AsyncpgExecutor,
    asyncpg_executors,
    asyncpg_work_connection,
    sqlalchemy_executors,
    sqlalchemy_work_connection,
)
from hephkit.idempotency.fastapi import idempotent_route
from hephkit.idempotency.ports import Executors
from hephkit.idempotency.store import IdempotencyStore

KEY = {"Idempotency-Key": "key-0001"}
BODY = {"b": 1, "a": 2}


class _Calls:
    def __init__(self) -> None:
        self.count = 0
        self.fail_once = False


@pytest.fixture
def calls() -> _Calls:
    return _Calls()


@pytest.fixture
def app(pg_conn: asyncpg.Connection, postgres_dsn: str, calls: _Calls) -> FastAPI:
    store = IdempotencyStore()
    app = FastAPI()
    install_error_handlers(app)

    @asynccontextmanager
    async def executors(request: Request) -> AsyncIterator[Executors]:
        # The one place connection setup is decided: claim_ex plain, work_ex in a transaction.
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

    def route(**kw: Any) -> Any:
        return idempotent_route(store, scope=lambda r: "tenant-a", executors=executors, **kw)

    @app.post("/charges")
    @route()
    async def charge(request: Request) -> Response:
        calls.count += 1
        return JSONResponse(await request.json(), status_code=201)

    @app.post("/no-request-param")
    @route()
    async def bare() -> Response:
        calls.count += 1
        return JSONResponse({"ok": True}, status_code=201)

    @app.post("/optional")
    @route(required=False)
    async def optional() -> Response:
        calls.count += 1
        return JSONResponse({"ok": True})

    @app.post("/rejects")
    @route()
    async def rejects() -> Response:
        calls.count += 1
        raise HephError("HEPH-VAL-422", "that amount is not allowed", field="amount")

    @app.post("/flaky")
    @route()
    async def flaky() -> Response:
        calls.count += 1
        if calls.fail_once:
            calls.fail_once = False
            raise HephError("HEPH-GEN-500")
        return JSONResponse({"ok": True}, status_code=201)

    @app.post("/empty")
    @route()
    async def empty() -> Response:
        calls.count += 1
        return Response(status_code=204)

    @app.post("/plain")
    @route()
    async def plain() -> Any:
        calls.count += 1
        return {"ok": True}

    @app.post("/items/{name}")
    @route()
    async def item(name: str) -> Response:
        calls.count += 1
        return JSONResponse({"name": name})

    @app.post("/optional-conn")
    @route(required=False)
    async def optional_conn(request: Request) -> Response:
        asyncpg_work_connection(request)
        return JSONResponse({"ok": True})

    app.state.executors = executors

    @app.post("/conflict")
    @route()
    async def conflict() -> Response:
        calls.count += 1
        return JSONResponse({"error": "taken"}, status_code=409)

    @app.post("/returns-503")
    @route()
    async def returns_503() -> Response:
        calls.count += 1
        if calls.fail_once:
            calls.fail_once = False
            return JSONResponse({"error": "down"}, status_code=503)
        return JSONResponse({"ok": True}, status_code=201)

    return app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_a_repeat_replays_the_stored_bytes_verbatim(client, calls):
    """Byte-for-byte, not a re-serialised equivalent."""
    first = await client.post("/charges", json=BODY, headers=KEY)
    again = await client.post("/charges", json=BODY, headers=KEY)
    assert first.status_code == 201
    assert again.status_code == first.status_code
    assert again.content == first.content
    assert again.headers["idempotent-replayed"] == "true"
    assert again.headers["content-type"] == first.headers["content-type"]
    assert "idempotent-replayed" not in first.headers
    assert calls.count == 1


async def test_a_raised_4xx_replays_the_same_problem_body(client, calls):
    """2.4: a replay returns the stored status AND body. Without a renderer the
    store keeps an empty body and the replayed client gets a different response."""
    first = await client.post("/rejects", json=BODY, headers=KEY)
    again = await client.post("/rejects", json=BODY, headers=KEY)
    assert first.status_code == 422
    assert first.json()["code"] == "HEPH-VAL-422"
    assert first.content != b""
    assert again.status_code == 422
    assert again.content == first.content
    assert again.headers["content-type"] == first.headers["content-type"] == "application/problem+json"
    assert again.headers["idempotent-replayed"] == "true"
    assert calls.count == 1


async def test_the_same_key_with_a_different_body_is_422(client, calls):
    await client.post("/charges", json=BODY, headers=KEY)
    r = await client.post("/charges", json={"a": 3}, headers=KEY)
    assert r.status_code == 422
    assert r.json()["code"] == "HEPH-IDEMP-422"
    assert calls.count == 1


async def test_a_missing_key_on_a_required_route_is_400(client, calls):
    r = await client.post("/charges", json=BODY)
    assert r.status_code == 400
    assert r.json()["code"] == "HEPH-IDEMP-400"
    assert calls.count == 0


async def test_a_malformed_key_on_a_required_route_is_400(client, calls):
    r = await client.post("/charges", json=BODY, headers={"Idempotency-Key": "has space"})
    assert r.status_code == 400
    assert r.json()["code"] == "HEPH-IDEMP-400"
    assert calls.count == 0


async def test_a_malformed_key_on_an_optional_route_is_ignored_not_rejected(client, calls):
    """Spec 2.1: an endpoint that does not require a key MUST NOT fail over one."""
    for headers in ({"Idempotency-Key": "has space"}, {}):
        r = await client.post("/optional", headers=headers)
        assert r.status_code == 200
    assert calls.count == 2


async def test_a_valid_key_on_an_optional_route_still_dedupes(client, calls):
    await client.post("/optional", headers=KEY)
    again = await client.post("/optional", headers=KEY)
    assert again.headers["idempotent-replayed"] == "true"
    assert calls.count == 1


async def test_two_orderings_of_one_query_are_two_fingerprints(client):
    """Spec 2.2: the target is raw. ?a=1&b=2 and ?b=2&a=1 are different requests."""
    await client.post("/charges?a=1&b=2", json=BODY, headers=KEY)
    r = await client.post("/charges?b=2&a=1", json=BODY, headers=KEY)
    assert r.status_code == 422 and r.json()["code"] == "HEPH-IDEMP-422"


async def test_a_query_is_part_of_the_fingerprint(client):
    await client.post("/charges", json=BODY, headers=KEY)
    r = await client.post("/charges?a=1", json=BODY, headers=KEY)
    assert r.json()["code"] == "HEPH-IDEMP-422"


async def test_the_path_is_not_percent_decoded(client):
    """Spec 2.2: no percent-decoding. /items/%41 and /items/A reach the handler as
    the same value, but they are different request targets."""
    first = await client.post("/items/%41", headers=KEY)
    r = await client.post("/items/A", headers=KEY)
    assert first.status_code == 200
    assert r.status_code == 422 and r.json()["code"] == "HEPH-IDEMP-422"


async def test_a_5xx_is_released_so_a_retry_runs_again(client, calls):
    calls.fail_once = True
    first = await client.post("/flaky", headers=KEY)
    again = await client.post("/flaky", headers=KEY)
    assert first.status_code == 500
    assert again.status_code == 201
    assert "idempotent-replayed" not in again.headers
    assert calls.count == 2


async def test_a_handler_that_takes_no_request_still_works(client, calls):
    first = await client.post("/no-request-param", headers=KEY)
    again = await client.post("/no-request-param", headers=KEY)
    assert again.content == first.content
    assert calls.count == 1


async def test_the_key_is_recorded_as_the_idempotency_key_attribute(client):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("test").start_as_current_span("request"):
        await client.post("/charges", json=BODY, headers=KEY)
    (span,) = exporter.get_finished_spans()
    assert span.attributes[IDEMPOTENCY_KEY] == "key-0001"


def _store() -> IdempotencyStore:
    return IdempotencyStore()


def _unused(request: Request) -> Any:  # pragma: no cover - never entered
    raise AssertionError("not called at decoration")


async def _streams(request: Request) -> StreamingResponse:
    raise AssertionError


async def _serves_a_file(request: Request) -> FileResponse:
    raise AssertionError


@pytest.mark.parametrize("handler", [_streams, _serves_a_file])
def test_an_uncapturable_route_is_refused_at_decoration(handler):
    with pytest.raises(TypeError, match="cannot be captured"):
        idempotent_route(_store(), scope=lambda r: "t", executors=_unused)(handler)


def test_a_sync_handler_is_refused_at_decoration():
    def handler(request: Request) -> Response:
        raise AssertionError

    with pytest.raises(TypeError, match="async"):
        idempotent_route(_store(), scope=lambda r: "t", executors=_unused)(handler)


async def test_a_handler_returning_a_plain_value_is_refused_and_released(client, calls):
    """Its status would come from a decorator the wrapper cannot see, so a replay
    could differ from the first response. It fails loudly and the key is released."""
    for _ in range(2):
        with pytest.raises(TypeError, match="fully built Response"):
            await client.post("/plain", headers=KEY)
    assert calls.count == 2


async def test_a_response_with_no_content_type_replays_without_one(client, calls):
    first = await client.post("/empty", headers=KEY)
    again = await client.post("/empty", headers=KEY)
    assert (first.status_code, first.content) == (204, b"")
    assert "content-type" not in first.headers
    assert (again.status_code, again.content) == (204, b"")
    assert "content-type" not in again.headers
    assert again.headers["idempotent-replayed"] == "true"
    assert calls.count == 1


def test_an_annotation_that_cannot_be_resolved_is_left_to_the_per_response_check():
    async def handler(request: Request) -> NoSuchName:  # type: ignore[name-defined]  # noqa: F821
        raise AssertionError

    idempotent_route(_store(), scope=lambda r: "t", executors=_unused)(handler)


async def test_a_returned_409_is_stored_and_replayed(client, calls):
    first = await client.post("/conflict", headers=KEY)
    again = await client.post("/conflict", headers=KEY)
    assert first.status_code == again.status_code == 409
    assert again.content == first.content
    assert again.headers["idempotent-replayed"] == "true"
    assert calls.count == 1


async def test_a_returned_5xx_response_is_released_so_a_retry_runs_again(client, calls):
    """The store's rule keys on status, not on whether the 5xx was raised or returned."""
    calls.fail_once = True
    first = await client.post("/returns-503", headers=KEY)
    again = await client.post("/returns-503", headers=KEY)
    assert first.status_code == 503
    assert again.status_code == 201
    assert "idempotent-replayed" not in again.headers
    assert calls.count == 2


async def test_a_returned_5xx_does_not_commit_the_handlers_work(pg_conn, postgres_dsn):
    """The invariant behind the rule: a released record means the work did not commit.

    `asyncpg_executors` commits when its block exits cleanly and rolls back when
    an exception passes through it, which is the shape of every executors
    factory. So a returned 5xx that released the record and then returned
    normally **committed the handler's rows while deleting the record**, and the
    client's retry ran the handler again over committed state -- the double
    execution this module exists to prevent. Deliberately not under a harness
    that commits on a clean exit by itself: this is the shipped factory, a real
    pool, and a real write on the work connection.
    """
    await pg_conn.execute("CREATE TABLE IF NOT EXISTS heph_test_work (note text PRIMARY KEY)")
    await pg_conn.execute("TRUNCATE heph_test_work")
    pool = await asyncpg.create_pool(postgres_dsn, min_size=2, max_size=4)
    runs = 0
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/w")
    @idempotent_route(IdempotencyStore(), scope=lambda r: "t", executors=asyncpg_executors(pool))
    async def handler(request: Request) -> Response:
        nonlocal runs
        runs += 1
        conn = asyncpg_work_connection(request)
        await conn.execute("INSERT INTO heph_test_work (note) VALUES ($1)", f"run-{runs}")
        if runs == 1:
            return JSONResponse({"error": "down"}, status_code=503)
        return JSONResponse({"ok": True}, status_code=201)

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            first = await c.post("/w", headers=KEY)
            assert first.status_code == 503
            assert first.json() == {"error": "down"}  # the handler's own response
            assert await pg_conn.fetchval("SELECT count(*) FROM heph_test_work") == 0
            assert await pg_conn.fetchval("SELECT count(*) FROM heph_idempotency") == 0
            # The key is free, so the retry really runs, and it commits.
            again = await c.post("/w", headers=KEY)
            assert again.status_code == 201
            assert [r["note"] for r in await pg_conn.fetch("SELECT note FROM heph_test_work")] == [
                "run-2"
            ]
    finally:
        await pool.close()
        await pg_conn.execute("DROP TABLE IF EXISTS heph_test_work")
    assert runs == 2


async def test_a_server_without_raw_path_is_refused_not_fingerprinted_decoded(app, calls):
    """Spec 2.2: without raw_path the only path available is percent-decoded, which would
    make /items/%41 and /items/A one request. It must fail loudly, never fall back."""

    async def no_raw_path(scope, receive, send):
        scope.pop("raw_path", None)
        await app(scope, receive, send)

    transport = httpx.ASGITransport(app=no_raw_path)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        with pytest.raises(RuntimeError, match="raw_path"):
            await c.post("/items/%41", headers=KEY)
    assert calls.count == 0


async def test_a_raw_path_that_carries_the_query_does_not_count_it_twice(app, calls):
    """The ASGI spec does not say raw_path excludes the query, and some servers include it."""
    seen = []

    async def with_query_in_raw_path(scope, receive, send):
        if scope["type"] == "http" and scope["query_string"]:
            scope["raw_path"] = scope["raw_path"] + b"?" + scope["query_string"]
        seen.append(scope.get("raw_path"))
        await app(scope, receive, send)

    transport = httpx.ASGITransport(app=with_query_in_raw_path)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/charges?a=1", json=BODY, headers=KEY)
        # The same request through a server that strips it must be the same fingerprint.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        again = await c.post("/charges?a=1", json=BODY, headers=KEY)
    assert seen[0].endswith(b"?a=1")
    assert again.headers["idempotent-replayed"] == "true"


async def _returns_a_dict(request: Request) -> dict[str, Any]:
    raise AssertionError


class _Out(BaseModel):
    ok: bool


async def _returns_a_model(request: Request) -> _Out:
    raise AssertionError


async def _returns_a_response_union(request: Request) -> JSONResponse | Response:
    return Response()


@pytest.mark.parametrize("handler", [_returns_a_dict, _returns_a_model])
def test_a_return_annotation_that_is_not_a_response_is_refused_at_decoration(handler):
    with pytest.raises(TypeError, match="fully built Response"):
        idempotent_route(_store(), scope=lambda r: "t", executors=_unused)(handler)


async def _returns_an_uncapturable_union(request: Request) -> StreamingResponse | Response:
    raise AssertionError


def test_a_union_with_an_uncapturable_member_is_refused_at_decoration():
    with pytest.raises(TypeError, match="fully built Response"):
        idempotent_route(_store(), scope=lambda r: "t", executors=_unused)(
            _returns_an_uncapturable_union
        )


async def test_a_union_of_response_types_is_accepted_and_works(app, client, calls):
    """FastAPI itself needs response_model=None on a union of response classes."""
    idempotent = idempotent_route(
        IdempotencyStore(), scope=lambda r: "t", executors=app.state.executors
    )

    async def union(request: Request) -> JSONResponse | Response:
        calls.count += 1
        return JSONResponse({"ok": True}, status_code=201)

    app.post("/union", response_model=None)(idempotent(union))
    first = await client.post("/union", headers=KEY)
    again = await client.post("/union", headers=KEY)
    assert again.content == first.content and again.headers["idempotent-replayed"] == "true"
    assert calls.count == 1


@pytest.mark.parametrize("factory", ["asyncpg", "sqlalchemy"])
async def test_the_shipped_factories_claim_outside_the_handlers_transaction(
    factory, pg_conn, postgres_dsn
):
    """While the handler runs in its open transaction, another connection already sees the
    in_flight record: the claim committed on its own. Then the 4xx commits and replays. The
    work connection is reachable while the handler runs and gone after the route ends."""
    if factory == "asyncpg":
        pool = await asyncpg.create_pool(postgres_dsn, min_size=2, max_size=4)
        make = asyncpg_executors(pool)
        closer = pool.close
        accessor = asyncpg_work_connection
    else:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(postgres_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
        make = sqlalchemy_executors(engine)
        closer = engine.dispose
        accessor = sqlalchemy_work_connection
    states: list[Any] = []
    requests: list[Request] = []
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/c")
    @idempotent_route(IdempotencyStore(), scope=lambda r: "t", executors=make)
    async def handler(request: Request) -> Response:
        requests.append(request)
        states.append(await pg_conn.fetchval("SELECT state FROM heph_idempotency"))
        states.append(accessor(request) is not None)
        raise HephError("HEPH-VAL-422", "no")

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            first = await c.post("/c", headers=KEY)
            again = await c.post("/c", headers=KEY)
    finally:
        await closer()
    assert states == ["in_flight", True]
    assert first.status_code == again.status_code == 422
    assert again.content == first.content
    assert await pg_conn.fetchval("SELECT state FROM heph_idempotency") == "completed"
    # The connection went back to the pool: a late user (a BackgroundTask, a dependency's
    # teardown) must not be able to reach it.
    with pytest.raises(RuntimeError, match="no work connection"):
        accessor(requests[0])


@asynccontextmanager
async def _yielding(inner):
    """Acquire, then let the other requests run: how several requests each end up holding
    one connection while waiting for another."""
    async with inner as conn:
        await asyncio.sleep(0.05)
        yield conn


class _YieldingPool:
    def __init__(self, pool):
        self._pool = pool

    def acquire(self, **kw):
        return _yielding(self._pool.acquire(**kw))


async def _burst(make, n=4, hold=0.05):
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/c")
    @idempotent_route(IdempotencyStore(), scope=lambda r: "t", executors=make)
    async def handler(request: Request) -> Response:
        await asyncio.sleep(hold)
        return JSONResponse({"ok": True}, status_code=201)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        return await asyncio.wait_for(
            asyncio.gather(
                *(c.post("/c", headers={"Idempotency-Key": f"k{i}"}) for i in range(n)),
                return_exceptions=True,
            ),
            timeout=3,
        )


def _is_pool_exhaustion(result: Any) -> bool:
    """A 503 carrying the registry code, which is what the client actually gets.

    The acquire still ends in a TimeoutError; HEPH-DB-503 is the name it is
    reported under, so asserting on the response rather than on the exception
    also pins the rendering an operator reads at 03:00.
    """
    return (
        getattr(result, "status_code", None) == 503
        and result.json()["code"] == "HEPH-DB-503"
        and result.headers["content-type"] == "application/problem+json"
    )


async def test_an_exhausted_single_pool_raises_instead_of_hanging(pg_conn, postgres_dsn):
    """max_size=2 and four concurrent requests: each takes a claim connection and then waits
    for a work connection nobody can release. Without acquire_timeout this never returns."""
    pool = await asyncpg.create_pool(postgres_dsn, min_size=2, max_size=2)
    try:
        results = await _burst(asyncpg_executors(_YieldingPool(pool), acquire_timeout=0.5))
        assert any(_is_pool_exhaustion(r) for r in results)
        # and the pool is not wedged afterwards
        (ok,) = await _burst(asyncpg_executors(pool, acquire_timeout=5), n=1)
        assert ok.status_code == 201
    finally:
        await pool.close()


@pytest.mark.parametrize("factory", ["asyncpg", "sqlalchemy"])
async def test_a_pool_that_cannot_hand_out_two_connections_is_a_registry_coded_503(
    factory, pg_conn, postgres_dsn
):
    """One connection, and a request needs two: the second acquire times out.

    A bare TimeoutError renders as HEPH-GEN-500, which tells the operator
    nothing about connections -- and ADR 0020 calls pool exhaustion the thing an
    adopter is most likely to get wrong. The caller-facing body stays the
    registry's hint; the sizing rule is on the exception and at
    /errors/HEPH-DB-503, never on the wire.
    """
    if factory == "asyncpg":
        pool = await asyncpg.create_pool(postgres_dsn, min_size=1, max_size=1)
        make = asyncpg_executors(pool, acquire_timeout=0.3)
        closer = pool.close
    else:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(
            postgres_dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.3,
        )
        make = sqlalchemy_executors(engine)
        closer = engine.dispose

    app = FastAPI()
    install_error_handlers(app)

    @app.post("/c")
    @idempotent_route(IdempotencyStore(), scope=lambda r: "t", executors=make)
    async def handler(request: Request) -> Response:  # pragma: no cover - never reached
        raise AssertionError("the executors never opened")

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post("/c", headers=KEY)
    finally:
        await closer()
    assert _is_pool_exhaustion(r)
    assert "pool" not in r.json()["detail"]  # the sizing rule is not caller copy
    assert await pg_conn.fetchval("SELECT count(*) FROM heph_idempotency") == 0


async def test_a_separate_claim_pool_cannot_deadlock(pg_conn, postgres_dsn):
    """The same burst, with claim connections from a pool of their own and a timeout too long
    to rescue it: every request completes, by queueing."""
    work = await asyncpg.create_pool(postgres_dsn, min_size=2, max_size=2)
    claim = await asyncpg.create_pool(postgres_dsn, min_size=2, max_size=2)
    try:
        results = await _burst(
            asyncpg_executors(
                _YieldingPool(work), claim_pool=_YieldingPool(claim), acquire_timeout=30
            )
        )
        assert [r.status_code for r in results] == [201] * 4
    finally:
        await work.close()
        await claim.close()


@pytest.mark.parametrize("factory", ["asyncpg", "sqlalchemy"])
async def test_a_timeout_the_handler_raises_is_not_renamed_pool_exhaustion(
    factory, pg_conn, postgres_dsn
):
    """Only the acquire is translated, which is what the flag in the helper is for.

    A handler that times out talking to something else is not an exhausted pool,
    and reporting it as HEPH-DB-503 would send an operator to the wrong place.
    It keeps its own type on the way out, and the record is still released.
    """
    if factory == "asyncpg":
        pool = await asyncpg.create_pool(postgres_dsn, min_size=2, max_size=4)
        make = asyncpg_executors(pool)
        closer = pool.close
        boom: BaseException = TimeoutError("the handler's own")
    else:
        from sqlalchemy.exc import TimeoutError as PoolTimeout
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(
            postgres_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        )
        make = sqlalchemy_executors(engine)
        closer = engine.dispose
        boom = PoolTimeout("the handler's own")

    app = FastAPI()
    install_error_handlers(app)

    @app.post("/c")
    @idempotent_route(IdempotencyStore(), scope=lambda r: "t", executors=make)
    async def handler(request: Request) -> Response:
        raise boom

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            with pytest.raises(type(boom)) as raised:
                await c.post("/c", headers=KEY)
    finally:
        await closer()
    assert raised.value is boom
    assert not isinstance(raised.value, HephError)
    assert await pg_conn.fetchval("SELECT count(*) FROM heph_idempotency") == 0


async def test_nested_executors_restore_the_outer_connection_and_clear_on_exit(pg_conn, postgres_dsn):
    from types import SimpleNamespace

    from starlette.datastructures import State

    pool = await asyncpg.create_pool(postgres_dsn, min_size=2, max_size=6)
    request = SimpleNamespace(state=State())
    make = asyncpg_executors(pool)
    try:
        async with make(request):
            outer = asyncpg_work_connection(request)
            async with make(request):
                assert asyncpg_work_connection(request) is not outer
            assert asyncpg_work_connection(request) is outer
        with pytest.raises(RuntimeError, match="no work connection"):
            asyncpg_work_connection(request)
    finally:
        await pool.close()


async def test_an_optional_route_with_no_key_has_no_work_connection(app, client):
    with pytest.raises(RuntimeError, match="no work connection"):
        await client.post("/optional-conn")


def test_executors_roles_are_named():
    ex = Executors(claim="a", work="b")  # type: ignore[arg-type]
    assert (ex.claim, ex.work) == ("a", "b")


async def _warm(pool) -> None:
    """Exercise every pooled connection before a timed section.

    `create_pool` opens `min_size` connections but does not make them do any
    work, so the first statement on each can pay for a cold server: plan
    construction, catalog reads, a cold page cache. That cost lands inside the
    measurement and has nothing to do with what the test is asserting.
    """
    async with pool.acquire() as a, pool.acquire() as b:
        await a.fetchval("SELECT 1")
        await b.fetchval("SELECT 1")


class _RecordingPool:
    """A pool that records the ``timeout`` each acquire was given.

    The wall-clock test below cannot tell which of the two acquires timed out:
    with two requests against two connections, an interleaving where both take
    a claim connection first makes the *work* acquire raise, and the claim
    acquire is never exercised. That was verified by mutation — unbinding the
    claim acquire leaves the wall-clock test green. So the bound on each
    acquire is pinned here instead, where no interleaving can hide it.
    """

    def __init__(self, pool) -> None:
        self._pool = pool
        self.timeouts: list[float | None] = []

    def acquire(self, **kw):
        self.timeouts.append(kw.get("timeout"))
        return self._pool.acquire(**kw)


async def test_both_acquires_are_bounded(pg_conn, postgres_dsn):
    """Every acquire carries the configured timeout — claim as well as work.

    An unbounded claim acquire is the permanent hang this parameter exists to
    prevent, and it is invisible to a timing assertion.
    """
    pool = await asyncpg.create_pool(postgres_dsn, min_size=1, max_size=2)
    spy = _RecordingPool(pool)
    try:
        (ok,) = await _burst(asyncpg_executors(spy, acquire_timeout=7.5), n=1)
        assert ok.status_code == 201
        assert spy.timeouts == [7.5, 7.5], spy.timeouts
    finally:
        await pool.close()


async def test_an_exhausted_pool_fails_fast_rather_than_waiting_out_the_holder(
    pg_conn, postgres_dsn
):
    """A pool held by a slow request makes the next one raise rather than wait as long as
    the slow one takes. Which acquire raises depends on interleaving — that both are
    bounded is pinned by test_both_acquires_are_bounded."""
    pool = await asyncpg.create_pool(postgres_dsn, min_size=2, max_size=2)
    try:
        # Both connections do a statement first, so a cold server is not timed.
        await _warm(pool)
        started = time.monotonic()
        results = await _burst(asyncpg_executors(pool, acquire_timeout=0.3), n=2, hold=1.5)
        assert any(_is_pool_exhaustion(r) for r in results)
        # The waiter gave up on its own timeout; only the holder takes as long as `hold`.
        #
        # The margin is deliberately loose. Each request needs two of the two
        # connections, so without the claim timeout the waiter serialises behind
        # the holder and the burst takes about 2 * hold = 3.0s. Anything under
        # that discriminates; 1.0s of headroom over `hold` keeps a shared runner
        # or a cold container from reddening a correct result, which a 0.5s
        # margin did not. The assertion that carries the finding is the
        # pool-exhaustion check above — this one only says it failed fast.
        assert time.monotonic() - started < 1.5 + 1.0
    finally:
        await pool.close()


def test_the_default_acquire_timeout_is_bounded():
    """Both burst tests pass a timeout explicitly; this pins what a caller who does not gets.
    None would restore the permanent hang on an under-sized pool."""
    default = inspect.signature(asyncpg_executors).parameters["acquire_timeout"].default
    assert default == 10.0
