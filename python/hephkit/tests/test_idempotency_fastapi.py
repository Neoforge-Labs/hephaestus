"""``idempotent_route``: per-route Idempotency-Key handling over a real Postgres.

The thing under test is that a replay is *the same response*, not an equivalent
one: the same status, the same bytes and the same content type (spec 2.4). The
4xx case is the easy one to get wrong, because the store builds no body of its
own and a renderer has to be handed to it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from hephkit.conventions import IDEMPOTENCY_KEY
from hephkit.errors import HephError
from hephkit.errors.fastapi import install_error_handlers
from hephkit.idempotency.adapters import AsyncpgExecutor
from hephkit.idempotency.fastapi import idempotent_route
from hephkit.idempotency.ports import Executor
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


@pytest_asyncio.fixture
async def client(
    pg_conn: asyncpg.Connection, postgres_dsn: str, calls: _Calls
) -> AsyncIterator[httpx.AsyncClient]:
    store = IdempotencyStore()
    app = FastAPI()
    install_error_handlers(app)

    @asynccontextmanager
    async def executors(request: Request) -> AsyncIterator[tuple[Executor, Executor]]:
        # The one place connection setup is decided: claim_ex plain, work_ex in a transaction.
        claim_conn = await asyncpg.connect(postgres_dsn)
        work_conn = await asyncpg.connect(postgres_dsn)
        tx = work_conn.transaction()
        await tx.start()
        try:
            yield AsyncpgExecutor(claim_conn), AsyncpgExecutor(work_conn)
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
