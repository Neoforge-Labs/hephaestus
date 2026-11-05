"""One-call OpenTelemetry tracing and structured, redacted logging. Experimental.

``setup_observability(settings, app)`` builds a tracer provider whose resource
carries ``service.name`` and ``deployment.environment``, exports spans over OTLP
HTTP to ``settings.otlp_endpoint`` (or to an injected ``span_exporter``),
instruments the FastAPI ``app`` if given, and configures structlog to emit JSON
lines through this chain: contextvars -> trace ids -> redaction -> JSON.

Redaction (decisions, each pinned by a test):

* A key is redacted when, lower-cased with ``.`` and ``-`` turned into ``_``, it
  *equals* a redacted name. ``user.id``, ``user_id`` and ``USER_ID`` are one key.
* Matching is exact, not substring: ``amount`` and ``my_token_count`` are kept,
  and so is ``password_hint``. Substring matching would blank innocent fields
  and make the boundary unpredictable; callers name secrets precisely.
* It recurses into dicts, lists and tuples. Whatever the value's type, a
  redacted key's value becomes ``"[REDACTED]"``.
* Only keys are inspected. Secrets embedded inside free-text values are not found.

Starting never needs the collector: spans are exported from a background batch
thread, so an unreachable endpoint cannot block or fail ``setup_observability``.

Needs the ``observability`` extra: ``pip install "hephkit[observability]"``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from structlog.typing import EventDict, FilteringBoundLogger, WrappedLogger

from hephkit.conventions import PII_ATTRIBUTES

if TYPE_CHECKING:
    from fastapi import FastAPI

    from hephkit.settings import HephSettings

__all__ = ["Observability", "get_logger", "setup_observability"]

REDACTED: Final = "[REDACTED]"
_TRUNCATED: Final = "[TRUNCATED]"
_MAX_DEPTH: Final = 16


def _normalise(key: str) -> str:
    return key.lower().replace(".", "_").replace("-", "_")


REDACTED_KEYS: Final[frozenset[str]] = frozenset(
    {"password", "secret", "token", "authorization", "api_key", "card_number", "cookie"}
    | {_normalise(name) for name in PII_ATTRIBUTES}
)


def _redact_value(value: object, depth: int) -> object:
    if depth > _MAX_DEPTH:
        return _TRUNCATED
    if isinstance(value, Mapping):
        return {
            k: REDACTED if _normalise(str(k)) in REDACTED_KEYS else _redact_value(v, depth + 1) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(v, depth + 1) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(v, depth + 1) for v in value)
    return value


def _redact(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    redacted = _redact_value(event_dict, 0)
    assert isinstance(redacted, dict)
    return redacted


def _add_trace_ids(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def _configure_logging(level: str) -> None:
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.contextvars.merge_contextvars,
            _add_trace_ids,
            _redact,
            structlog.processors.JSONRenderer(default=repr),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


# Redaction must hold even if a caller logs before (or without) setup.
_configure_logging("INFO")


def get_logger(name: str) -> FilteringBoundLogger:
    """A structlog logger that emits redacted JSON lines with trace ids."""
    logger: FilteringBoundLogger = structlog.get_logger(name)
    return logger


_lock = threading.Lock()
_active: Observability | None = None


class Observability:
    """Handle returned by ``setup_observability``. ``shutdown`` flushes and
    stops the exporter, un-instruments apps, and allows a fresh setup."""

    def __init__(self, settings: HephSettings, provider: TracerProvider) -> None:
        self.settings = settings
        self.tracer_provider = provider
        self._apps: list[FastAPI] = []

    def _instrument(self, app: FastAPI) -> None:
        if any(app is seen for seen in self._apps):
            return
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, tracer_provider=self.tracer_provider)
        self._apps.append(app)

    def shutdown(self) -> None:
        global _active
        with _lock:
            if _active is not self:
                return
            _active = None
        if self._apps:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            for app in self._apps:
                FastAPIInstrumentor.uninstrument_app(app)
            self._apps.clear()
        self.tracer_provider.shutdown()


def setup_observability(
    settings: HephSettings,
    app: FastAPI | None = None,
    *,
    span_exporter: SpanExporter | None = None,
) -> Observability:
    """Configure tracing and logging in one call.

    Idempotent: calling again with equal settings returns the same
    ``Observability`` (and instruments ``app`` if it is new). Calling with
    *different* settings raises ``RuntimeError`` rather than silently keeping
    the old service name; call ``shutdown()`` first to reconfigure.
    """
    global _active
    with _lock:
        if _active is not None:
            if _active.settings != settings:
                raise RuntimeError(
                    "observability is already set up with different settings; call shutdown() before reconfiguring"
                )
            current = _active
        else:
            resource = Resource.create({"service.name": settings.service_name, "deployment.environment": settings.env})
            provider = TracerProvider(resource=resource)
            if span_exporter is not None:
                provider.add_span_processor(SimpleSpanProcessor(span_exporter))
            else:
                endpoint = settings.otlp_endpoint.rstrip("/") + "/v1/traces"
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            if isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
                trace.set_tracer_provider(provider)
            _configure_logging(settings.log_level)
            current = _active = Observability(settings, provider)
        if app is not None:
            current._instrument(app)
        return current
