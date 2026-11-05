"""FastAPI integration: exceptions become RFC 9457 problem+json (spec section 1).

Every exception is mapped by its ``.code``: ``HephError``, ``MoneyError``,
``SignatureError`` and ``HashingError`` all carry a registry code, and the
registry gives the status, so no per-class table exists. An exception without a
registered code is ``HEPH-GEN-500``. Only the registry title is ever sent for an
exception that is not a ``HephError``; its message may hold internals.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace

from hephkit.errors import REGISTRY, TYPE_BASE_URL, HephError

__all__ = ["install_error_handlers", "problem_response"]

PROBLEM_JSON = "application/problem+json"
_GENERIC = "HEPH-GEN-500"


def _trace_id() -> str | None:
    """Trace id of the active span, or ``None`` when no valid span is active."""
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


def problem_response(
    code: str, detail: str | None = None, extensions: dict[str, Any] | None = None
) -> JSONResponse:
    """A problem+json response for a registry ``code``.

    ``detail`` defaults to the registry title. ``trace_id`` is a member only
    when a span is active.
    """
    status, title = REGISTRY[code]
    body: dict[str, Any] = {
        **(extensions or {}),
        "type": TYPE_BASE_URL + code,
        "title": title,
        "status": status,
        "detail": detail or title,
        "code": code,
    }
    trace_id = _trace_id()
    if trace_id is not None:
        body["trace_id"] = trace_id
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


async def _handle_exception(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HephError):
        return problem_response(exc.code, exc.detail, exc.extensions)
    code = getattr(exc, "code", None)
    return problem_response(code if isinstance(code, str) and code in REGISTRY else _GENERIC)


async def _handle_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # loc/msg/type only: `input` and `ctx` can echo the submitted value.
    fields = [
        {"loc": list(e["loc"]), "msg": str(e["msg"]), "type": str(e["type"])} for e in exc.errors()
    ]
    return problem_response("HEPH-VAL-422", extensions={"errors": fields})


def install_error_handlers(app: FastAPI) -> None:
    """Route validation errors, ``HephError`` and any other exception to problem+json."""
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(Exception, _handle_exception)
