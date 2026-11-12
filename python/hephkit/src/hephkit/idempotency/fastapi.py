"""Per-route ``Idempotency-Key`` handling for FastAPI (spec 2.1 to 2.8). Maturity: experimental.

``idempotent_route`` wraps one route handler. It is per route and never global:
2.1 distinguishes endpoints that require a key from endpoints that do not, and
only the application knows which is which. It goes under the route decorator::

    @app.post("/charges")
    @idempotent_route(store, scope=tenant_of, executors=db_executors)
    async def create_charge(request: Request) -> Response: ...

**The two executors, and why the application supplies them once.**
``executors`` is a factory for an async context manager that yields
``(claim_ex, work_ex)``. They are different connections in different states,
and the store cannot tell them apart:

* ``claim_ex`` has **no transaction open**. ``claim()`` commits on its own, so
  the ``in_flight`` record is visible to the next request (2.5's 409, 2.8's
  takeover). ``release()`` and the storing of a 4xx also go through it, because
  the handler's transaction is being abandoned and a write inside it would be
  abandoned with it.
* ``work_ex`` is the **handler's own connection, with its transaction still
  open** when the handler returns. ``complete()`` writes the stored response
  there, so the response and the work it describes commit together, or neither
  does.

Handing the store a ``claim_ex`` that already has a transaction open is
forbidden, cannot be detected through the port, and has no runtime check. That
is why connection setup is decided here, in one callable, instead of being
passed per call: open ``claim_ex``'s connection plain, open ``work_ex``'s and
begin its transaction, yield both, then commit or roll back the work
transaction after the ``yield``. Application code never builds an executor
pair by hand, so it cannot get the pair wrong.

``scope`` comes from the application (an authenticated tenant). hephkit never
infers one, and it is never a client-supplied header or body field (2.3).

The handler must return a ``Response``: its status, body and content type are
what is stored, so a replay is exactly what the first caller received. A plain
return value would take its status from the route decorator, which this
wrapper cannot see. A ``StreamingResponse`` (or ``FileResponse``) cannot be
captured and is refused when the route is decorated.

A raised ``HephError`` below 500 is a real outcome (2.8) and is stored with the
problem+json body ``problem_response`` renders for it, so a replaying client
gets the same bytes as the first. It still propagates to
``install_error_handlers`` for the first caller. 5xx and other exceptions
release the record.
"""

from __future__ import annotations

import functools
import inspect
import typing
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Final

from fastapi import Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from hephkit.conventions import IDEMPOTENCY_KEY
from hephkit.errors import HephError
from hephkit.errors.fastapi import problem_response
from hephkit.idempotency import fingerprint, validate_key
from hephkit.idempotency.ports import Executor
from hephkit.idempotency.store import IdempotencyStore

try:
    from opentelemetry import trace
except ImportError:  # pragma: no cover - opentelemetry is optional
    trace = None  # type: ignore[assignment]

__all__ = ["REPLAYED_HEADER", "idempotent_route"]

REPLAYED_HEADER: Final = "Idempotent-Replayed"
_KEY_HEADER: Final = "Idempotency-Key"
_UNCAPTURABLE: Final = (StreamingResponse, FileResponse)

Handler = Callable[..., Awaitable[Any]]


def _render_error(exc: HephError) -> tuple[bytes, str | None]:
    """The body stored with a 4xx, so a replay matches what the first caller got.

    It must not raise: the store releases the record if it does, and the
    renderer's error would surface instead of the 4xx. ``problem_response``
    falls back to ``HEPH-GEN-500`` for content it cannot serialise rather than
    raising.
    """
    response = problem_response(exc.code, exc.detail, exc.extensions)
    return bytes(response.body), response.headers.get("content-type")


def _raw_target(request: Request) -> str:
    """The request target exactly as received (2.2): never normalised.

    ``scope["path"]`` is percent-decoded by the server, so the raw path is read
    from ``raw_path`` when the server provides it. The query string is already
    raw. A bare ``?`` cannot be told from no query through ASGI, which hands
    over an empty query string either way.
    """
    raw = request.scope.get("raw_path")
    path = raw.decode("latin-1") if isinstance(raw, bytes) else request.url.path
    query = request.url.query
    return f"{path}?{query}" if query else path


def _refuse_uncapturable(handler: Handler) -> None:
    if not inspect.iscoroutinefunction(handler):
        raise TypeError(f"idempotent_route needs an async handler, got {handler!r}")
    try:
        returns = typing.get_type_hints(handler).get("return")
    except Exception:  # noqa: BLE001 - unresolvable annotations are checked per response instead
        returns = None
    if isinstance(returns, type) and issubclass(returns, _UNCAPTURABLE):
        raise TypeError(
            f"{handler.__qualname__} returns {returns.__name__}, whose body cannot be captured "
            "for replay; an idempotent route must return a fully built Response"
        )


def _capture(result: Any) -> tuple[int, bytes, str | None]:
    if not isinstance(result, Response) or isinstance(result, _UNCAPTURABLE):
        raise TypeError(
            "an idempotent route must return a fully built Response so its status, body and "
            f"content type can be stored; got {type(result).__name__}"
        )
    return result.status_code, bytes(result.body), result.headers.get("content-type")


def idempotent_route(
    store: IdempotencyStore,
    *,
    required: bool = True,
    scope: Callable[[Request], str],
    executors: Callable[[Request], AbstractAsyncContextManager[tuple[Executor, Executor]]],
) -> Callable[[Handler], Handler]:
    """Make one route idempotent on its ``Idempotency-Key`` header.

    ``required`` is this endpoint's setting (2.1). When true a missing or
    malformed key is ``HEPH-IDEMP-400``; when false such a key is ignored and
    the handler just runs, without touching the store or ``executors``.

    ``scope`` maps the request to the tenant the key belongs to (2.3).

    ``executors`` returns an async context manager yielding
    ``(claim_ex, work_ex)``; the module docstring says what each is and why
    they differ. The handler runs inside it, so ``work_ex``'s transaction is
    open while the handler works.
    """

    def decorate(handler: Handler) -> Handler:
        _refuse_uncapturable(handler)
        signature = inspect.signature(handler)
        request_name = next(
            (n for n, p in signature.parameters.items() if p.annotation in (Request, "Request")),
            None,
        )
        injected = request_name is None
        if injected:
            request_name = "_heph_request"
            signature = signature.replace(
                parameters=[
                    *signature.parameters.values(),
                    inspect.Parameter(request_name, inspect.Parameter.KEYWORD_ONLY, annotation=Request),
                ]
            )

        @functools.wraps(handler)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            assert request_name is not None
            request: Request = kwargs.pop(request_name) if injected else kwargs[request_name]
            key = validate_key(request.headers.get(_KEY_HEADER), required=required)
            if key is None:
                return await handler(*args, **kwargs)
            if trace is not None:  # pragma: no branch - opentelemetry is optional
                trace.get_current_span().set_attribute(IDEMPOTENCY_KEY, key)
            # Reading consumes the stream; Starlette caches it for the handler.
            body = await request.body()
            fp = fingerprint(
                request.method, _raw_target(request), body, request.headers.get("content-type")
            )
            async with (
                executors(request) as (claim_ex, work_ex),
                store.idempotent_record(
                    claim_ex=claim_ex,
                    work_ex=work_ex,
                    scope=scope(request),
                    key=key,
                    fingerprint=fp,
                    render_error=_render_error,
                ) as record,
            ):
                if record.replay is not None:
                    replay = record.replay
                    headers = {REPLAYED_HEADER: "true"}
                    if replay.media_type is not None:
                        headers["content-type"] = replay.media_type
                    return Response(replay.body, status_code=replay.status, headers=headers)
                result = await handler(*args, **kwargs)
                record.finish(*_capture(result))
                return result

        wrapper.__signature__ = signature  # type: ignore[attr-defined]
        return wrapper

    return decorate
