"""One-call OpenTelemetry tracing and structured, redacted logging. Experimental.

``setup_observability(settings, app)`` builds a tracer provider whose resource
carries ``service.name`` and ``deployment.environment``, exports spans over OTLP
HTTP to ``settings.otlp_endpoint`` (or to an injected ``span_exporter``),
instruments the FastAPI ``app`` if given, and configures structlog to emit JSON
lines through this chain: contextvars -> trace ids -> redaction -> JSON.

Redaction (decisions, each pinned by a test):

* A key is normalised (lower-case, ``.`` and ``-`` become ``_``) and redacted
  when it *equals* a redacted word, *starts with* ``<word>_`` or *ends with*
  ``_<word>``. So ``access_token``, ``set-cookie``, ``refresh_token``,
  ``api_key_id`` and ``password_hint`` are redacted, while ``amount``,
  ``account_id`` and ``my_token_count`` (the word is only in the middle) are
  kept. ``user.id``, ``user_id`` and ``USER_ID`` are one key. A secret name with
  the word in the middle (``paystack_secret_key``) needs ``redact_keys``.
* Default words: password, secret, token, authorization, api_key, card_number,
  cookie, plus every ``pii: true`` attribute from the generated conventions.
  ``setup_observability(..., redact_keys=[...])`` adds product-specific words.
* Redaction is recursive: keys inside dict values, lists of dicts and tuples
  are redacted too (to a depth of 16, beyond which the value is replaced by
  ``"[TRUNCATED]"``). Whatever the value's type, a redacted key's value
  becomes ``"[REDACTED]"``.
* Dataclasses and pydantic models are dumped and redacted; sequences, sets,
  ``dict.items()``/``values()`` are expanded and redacted. Any other object is
  rendered as ``"<TypeName>"`` only, never ``repr``, so unanticipated shapes
  cannot leak their fields. Dict keys that JSON cannot carry are stringified.
* The rule is deliberately over-eager on prefixes: ``token_count`` is redacted
  (prefix ``token_``) while ``tokens_used`` is kept. LLM products that log token
  counts should name them ``tokens_used`` or ``input_tokens``, or accept the redaction.
* Only keys are inspected. Secrets embedded inside free-text values are not found.

``get_logger`` is annotated ``FilteringBoundLogger``, the type structlog really
returns under this configuration (the design text says ``BoundLogger``).

``setup_observability`` does not install error handlers. A product that wants
problem+json bodies carrying ``trace_id`` calls both::

    setup_observability(settings, app)
    install_error_handlers(app)

Starting never needs the collector: spans are exported from a background batch
thread, so an unreachable endpoint cannot block or fail ``setup_observability``.

Needs the ``observability`` extra: ``pip install "hephkit[observability]"``.
"""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import enum
import logging
import threading
import uuid
from collections.abc import ItemsView, Iterable, Mapping, Sequence, ValuesView
from collections.abc import Set as AbstractSet
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, Final, cast

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from structlog.typing import EventDict, FilteringBoundLogger, Processor, WrappedLogger

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


def _is_redacted(key: object, words: frozenset[str]) -> bool:
    if isinstance(key, bytes):
        k = _normalise(key.decode("utf-8", "replace"))
    elif isinstance(key, _JSON_KEYS):
        try:
            k = _normalise(str(key))
        except ValueError:  # integer beyond Python's int-to-str digit limit
            return True
    else:
        # A key we cannot name (tuple, custom object) cannot be shown to be
        # safe, so its value is withheld rather than risk leaking it.
        return True
    return any(k == w or k.startswith(w + "_") or k.endswith("_" + w) for w in words)


def _placeholder(obj: object) -> str:
    """Render of last resort: the type only, never the fields. ``repr`` of an
    unknown object can print secrets that key-based redaction cannot see."""
    return f"<{type(obj).__name__}>"


_JSON_KEYS: Final = (str, int, float, bool, type(None))
_STRINGIFIED: Final = (datetime.date, datetime.time, datetime.timedelta, decimal.Decimal, uuid.UUID, PurePath)
_OPAQUE_BYTES: Final = (bytearray, memoryview)


def _emit_key(key: object) -> object:
    """The key as the renderer will see it. Never ``str()``/``repr()`` an
    arbitrary object: that is the leak the type-name fallback exists to close."""
    if isinstance(key, bytes):
        return key.decode("utf-8", "replace")
    if isinstance(key, int) and not isinstance(key, bool):
        try:
            str(key)
        except ValueError:  # beyond Python's int-to-str digit limit
            return _placeholder(key)
        return key
    if isinstance(key, _JSON_KEYS):
        return key
    return _placeholder(key)


def _redact_value(value: object, depth: int, words: frozenset[str]) -> object:
    if depth > _MAX_DEPTH:
        return _TRUNCATED
    try:
        if value is None or isinstance(value, (str, float, bool)):
            return value
        if isinstance(value, int):
            str(value)  # raises beyond Python's int-to-str digit limit
            return value
        return _redact_container(value, depth, words)
    except Exception:  # a logging call must never raise
        return _placeholder(value)


def _redact_container(value: object, depth: int, words: frozenset[str]) -> object:
    def sub(item: object) -> object:
        return _redact_value(item, depth + 1, words)

    if isinstance(value, Mapping):
        return {
            _emit_key(k): REDACTED if _is_redacted(k, words) else sub(v)
            for k, v in value.items()
        }
    if isinstance(value, ItemsView):
        return sub(dict(value))
    if isinstance(value, tuple):
        return tuple(sub(v) for v in value)
    if isinstance(value, (bytes, *_OPAQUE_BYTES)):
        return _placeholder(value)
    if isinstance(value, (Sequence, AbstractSet, ValuesView)):
        return [sub(v) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return sub(dataclasses.asdict(value))
    dump = getattr(type(value), "model_dump", None)  # pydantic models, without importing pydantic
    if callable(dump):
        return sub(dump(value))
    if isinstance(value, enum.Enum):
        return sub(value.value)
    if isinstance(value, _STRINGIFIED):
        return value.isoformat() if isinstance(value, (datetime.date, datetime.time)) else str(value)
    return value  # left to the renderer, whose fallback is the type name


def _make_redactor(words: frozenset[str]) -> Processor:
    def redact(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
        return cast(EventDict, _redact_value(event_dict, 0, words))

    return redact


def _add_trace_ids(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def _configure_logging(level: str, words: frozenset[str] = REDACTED_KEYS) -> None:
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.contextvars.merge_contextvars,
            _add_trace_ids,
            _make_redactor(words),
            structlog.processors.JSONRenderer(default=_placeholder),
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
SHUTDOWN_TIMEOUT: Final = 2.0


class _SwitchTracer(trace.Tracer):
    """Resolves the real tracer on every call, so tracers handed out before a
    shutdown/restart keep working against whichever provider is current."""

    def __init__(self, owner: _SwitchProvider, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self._owner = owner
        self._args = args
        self._kwargs = kwargs

    def _real(self) -> trace.Tracer:
        return self._owner.current().get_tracer(*self._args, **self._kwargs)

    def start_span(self, *args: Any, **kwargs: Any) -> trace.Span:
        return self._real().start_span(*args, **kwargs)

    def start_as_current_span(self, *args: Any, **kwargs: Any) -> Any:
        return self._real().start_as_current_span(*args, **kwargs)


class _SwitchProvider(trace.TracerProvider):
    """The one global provider we install. OpenTelemetry allows setting the
    global only once per process, so restarts retarget this object instead.
    Between ``shutdown()`` and the next setup it is a no-op provider."""

    def __init__(self) -> None:
        self.target: trace.TracerProvider | None = None

    def current(self) -> trace.TracerProvider:
        return self.target or trace.NoOpTracerProvider()

    def get_tracer(self, *args: Any, **kwargs: Any) -> trace.Tracer:
        return _SwitchTracer(self, args, kwargs)


_SWITCH = _SwitchProvider()


class Observability:
    """Handle returned by ``setup_observability``. ``shutdown`` un-instruments
    apps, flushes and stops the exporter, and allows a fresh setup."""

    def __init__(self, settings: HephSettings, provider: TracerProvider, words: frozenset[str]) -> None:
        self.settings = settings
        self.tracer_provider = provider
        self._words = words
        self._apps: list[FastAPI] = []

    def _instrument(self, app: FastAPI) -> None:
        if any(app is seen for seen in self._apps):
            return
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, tracer_provider=self.tracer_provider)
        self._apps.append(app)

    def shutdown(self, timeout: float = SHUTDOWN_TIMEOUT) -> None:
        """Flush and stop, waiting at most ``timeout`` seconds (default 2.0).

        With a reachable collector this returns as soon as the final export
        completes. With an unreachable one, spans still queued after
        ``timeout`` are dropped and the call returns; a product can always exit
        promptly. Spans still in flight when this is called may end after the
        processor stops; the SDK then prints "Processor is already shutdown" to
        stderr and drops them. Safe to call twice. A later ``setup_observability`` installs a
        fresh, working provider.
        """
        global _active
        with _lock:
            if _active is not self:
                return
            _active = None
            _SWITCH.target = None
        if self._apps:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            for app in self._apps:
                FastAPIInstrumentor.uninstrument_app(app)
            self._apps.clear()
        stopper = threading.Thread(target=self.tracer_provider.shutdown, name="hephkit-otel-shutdown", daemon=True)
        stopper.start()
        stopper.join(timeout)


def setup_observability(
    settings: HephSettings,
    app: FastAPI | None = None,
    *,
    span_exporter: SpanExporter | None = None,
    redact_keys: Iterable[str] = (),
) -> Observability:
    """Configure tracing and logging in one call.

    ``redact_keys`` adds product-specific words to the default redaction set
    (see the module docstring for the matching rule).

    Idempotent: calling again with the same settings and ``redact_keys`` returns
    the same ``Observability`` (and instruments ``app`` if it is new). Calling
    with *different* ones raises ``RuntimeError`` rather than silently keeping
    the old service name; call ``shutdown()`` first to reconfigure.

    If the product already installed its own global OpenTelemetry provider,
    hephkit leaves it alone: only hephkit's FastAPI server spans go to this
    provider's exporter, and spans made through the global tracer go to the
    product's. Traces are split across the two; configure one or the other.

    This does not install error handlers; call ``install_error_handlers(app)``
    yourself (see the module docstring).
    """
    global _active
    words = REDACTED_KEYS | {_normalise(k) for k in redact_keys}
    with _lock:
        if _active is not None:
            if _active.settings != settings or _active._words != words:
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
            _SWITCH.target = provider
            if isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
                trace.set_tracer_provider(_SWITCH)
            _configure_logging(settings.log_level, words)
            current = _active = Observability(settings, provider, words)
        if app is not None:
            current._instrument(app)
        return current
