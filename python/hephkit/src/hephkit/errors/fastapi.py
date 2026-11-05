"""FastAPI integration: exceptions become RFC 9457 problem+json (spec section 1).

Every exception is mapped by its ``.code``: ``HephError``, ``MoneyError``,
``SignatureError`` and ``HashingError`` all carry a registry code, and the
registry gives the status, so no per-class table exists. An exception without a
registered code is ``HEPH-GEN-500``. For an exception that is not a ``HephError``
the message is never sent (it may hold internals); ``detail`` is the registry
``detail_hint`` for its code.

Known gap: Starlette ``HTTPException`` with status 404 (unknown route) becomes
``HEPH-NF-404``. Other statuses, such as 405, pass through unchanged in this
phase: the registry has no code for them, adding codes is out of scope here, and
the response shape for uncovered statuses is better decided alongside the auth
and idempotency middleware in a later phase. A 405 is not a server error, so it
is deliberately not mapped to ``HEPH-GEN-500``.

``opentelemetry-api`` is optional: without it ``trace_id`` is omitted, exactly as
when no span is active.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from hephkit.errors import DETAIL_HINTS, REGISTRY, TYPE_BASE_URL, HephError
from hephkit.hashing import HashingError
from hephkit.money import MoneyError
from hephkit.signatures import SignatureError

try:
    from opentelemetry import trace
except ImportError:  # pragma: no cover - exercised by simulating absence in tests
    trace = None  # type: ignore[assignment]

__all__ = ["install_error_handlers", "problem_response"]

PROBLEM_JSON = "application/problem+json"
_GENERIC = "HEPH-GEN-500"


def _trace_id() -> str | None:
    """Trace id of the active span, or ``None`` when no valid span is active."""
    if trace is None:
        return None
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


def _render(code: str, detail: str | None, extensions: dict[str, Any] | None) -> JSONResponse:
    status, title = REGISTRY[code]
    body: dict[str, Any] = {
        **(extensions or {}),
        "type": TYPE_BASE_URL + code,
        "title": title,
        "status": status,
        "detail": detail or DETAIL_HINTS.get(code) or title,
        "code": code,
    }
    trace_id = _trace_id()
    if trace_id is not None:
        body["trace_id"] = trace_id
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def problem_response(
    code: str, detail: str | None = None, extensions: dict[str, Any] | None = None
) -> JSONResponse:
    """A problem+json response for a registry ``code``.

    ``detail`` defaults to the registry ``detail_hint`` (the title if absent).
    ``trace_id`` is a member only when a span is active. If the caller-supplied
    ``detail`` or ``extensions`` cannot be serialised (including a nesting so
    deep it raises ``RecursionError``), the response is the ``HEPH-GEN-500``
    problem built from registry strings alone, with nothing caller-supplied.
    """
    try:
        return _render(code, detail, extensions)
    except (TypeError, ValueError, RecursionError):
        return _render(_GENERIC, None, None)


async def _handle_exception(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HephError):
        return problem_response(exc.code, exc.detail, exc.extensions)
    code = getattr(exc, "code", None)
    return problem_response(code if isinstance(code, str) and code in REGISTRY else _GENERIC)


async def _handle_http(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code == 404:
        return problem_response("HEPH-NF-404")
    # No registry code for other statuses (see module docstring): unchanged.
    return await http_exception_handler(request, exc)


async def _handle_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # loc/msg/type only: `input` and `ctx` can echo the submitted value.
    fields = [
        {"loc": list(e["loc"]), "msg": str(e["msg"]), "type": str(e["type"])} for e in exc.errors()
    ]
    return problem_response("HEPH-VAL-422", extensions={"errors": fields})


def install_error_handlers(app: FastAPI) -> None:
    """Route validation errors, our coded exceptions and any other exception to problem+json.

    Our four coded classes are registered by class, so Starlette dispatches them
    through ``ExceptionMiddleware`` and they are not re-raised (an expected client
    error must not be logged as a server crash). The bare ``Exception`` handler
    sits on ``ServerErrorMiddleware``, which re-raises after responding, and that
    is correct for a true 500. Mapping is still by ``.code`` in one function.
    """
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http)
    for cls in (HephError, MoneyError, SignatureError, HashingError):
        app.add_exception_handler(cls, _handle_exception)
    app.add_exception_handler(Exception, _handle_exception)
