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
  cannot leak their fields. Dict keys must be str, bytes, int, float, bool or
  None; any other key type (date, UUID, Path, plain ``Enum``, tuple, objects) renders as
  ``<TypeName>`` and its value is withheld as ``[REDACTED]``, because such a key
  cannot be checked against the redaction words. Key by string if you need both.
  ``str``- and ``int``-mixin enums and other ``str``/``int`` subclasses are
  treated as their underlying data, which is what the JSON output (and the
  redaction match) sees.
* The rule is deliberately over-eager on prefixes: ``token_count`` is redacted
  (prefix ``token_``) while ``tokens_used`` is kept. LLM products that log token
  counts should name them ``tokens_used`` or ``input_tokens``, or accept the redaction.
* Only keys are inspected. Secrets embedded inside free-text values are not found.

``get_logger`` is annotated ``FilteringBoundLogger``, the type structlog really
returns under this configuration (the design text says ``BoundLogger``).

Importing this module configures nothing. ``structlog`` is process-global and a
product may own it already, so hephkit touches it only when asked:
``setup_observability`` configures it, and ``configure_logging`` is the public
call for a product that wants the redacting chain without the tracing.

``setup_observability`` does not install error handlers. A product that wants
problem+json bodies carrying ``trace_id`` calls both::

    setup_observability(settings, app)
    install_error_handlers(app)

Starting never needs the collector: the endpoint is probed once with a bounded
TCP connect, and an endpoint that is blank or unreachable gets a no-op exporter
instead of ``BatchSpanProcessor`` + OTLP, so a product with no collector pays
nothing and emits no retry noise. ``probe_timeout=None`` skips the probe and
always builds the OTLP exporter.

Shutting down is registered with ``atexit``, so a product that forgets costs
nothing more than a bounded flush at interpreter exit. A FastAPI product should
prefer an explicit lifespan, which flushes at the right moment::

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        o = setup_observability(settings, app)
        yield
        o.shutdown()

Needs the ``observability`` extra: ``pip install "hephkit[observability]"``.
"""

from __future__ import annotations

import atexit
import contextlib
import dataclasses
import datetime
import decimal
import enum
import logging
import socket
import threading
import uuid
import warnings
from collections.abc import ItemsView, Iterable, Mapping, Sequence, ValuesView
from collections.abc import Set as AbstractSet
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, Final, Literal, cast
from urllib.parse import urlsplit

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from structlog.typing import EventDict, FilteringBoundLogger, Processor, WrappedLogger

from hephkit.conventions import PII_ATTRIBUTES

if TYPE_CHECKING:
    from fastapi import FastAPI

    from hephkit.settings import HephSettings

__all__ = ["Observability", "configure_logging", "get_logger", "setup_observability"]

REDACTED: Final = "[REDACTED]"
_TRUNCATED: Final = "[TRUNCATED]"
_MAX_DEPTH: Final = 16


def _normalise(key: str) -> str:
    return key.lower().replace(".", "_").replace("-", "_")


REDACTED_KEYS: Final[frozenset[str]] = frozenset(
    {"password", "secret", "token", "authorization", "api_key", "card_number", "cookie"}
    | {_normalise(name) for name in PII_ATTRIBUTES}
)


def _key_text(key: object) -> str | None:
    """The text the JSON serialiser will write for ``key``, or ``None`` if it
    is not a JSON key type. Both the redaction match and the emitted key use
    this, so they cannot disagree: ``json`` writes a ``str`` subclass's raw data
    (not its ``__str__``) and an ``int`` subclass via ``int.__repr__``."""
    if isinstance(key, bytes):
        return key.decode("utf-8", "replace")
    if isinstance(key, str):
        return str.__str__(key)
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int):
        return int.__repr__(key)  # ValueError beyond the int-to-str digit limit
    if isinstance(key, float):
        return float.__repr__(key)
    if key is None:
        return "null"
    return None


def _is_redacted(key: object, words: frozenset[str]) -> bool:
    try:
        text = _key_text(key)
        if text is None:
            # A key we cannot name (tuple, custom object) cannot be shown to be
            # safe, so its value is withheld rather than risk leaking it.
            return True
        k = _normalise(text)
    except Exception:  # fail closed
        return True
    return any(k == w or k.startswith(w + "_") or k.endswith("_" + w) for w in words)


def _placeholder(obj: object) -> str:
    """Render of last resort: the type only, never the fields. ``repr`` of an
    unknown object can print secrets that key-based redaction cannot see."""
    return f"<{type(obj).__name__}>"


_STRINGIFIED: Final = (datetime.date, datetime.time, datetime.timedelta, decimal.Decimal, uuid.UUID, PurePath)
_OPAQUE_BYTES: Final = (bytearray, memoryview)


def _emit_key(key: object) -> str:
    """The key as plain ``str``, exactly the text ``_is_redacted`` matched.
    Never ``str()``/``repr()`` an arbitrary object: that is the leak the
    type-name fallback exists to close."""
    try:
        text = _key_text(key)
    except Exception:
        text = None
    return _placeholder(key) if text is None else text


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


# The accepted level names, case-insensitively. `HephSettings.LogLevel` must
# list exactly these (pinned by a test): the two used to disagree in both
# directions -- settings rejected `debug` and `WARN` that this function accepted,
# while this function's error message advertised `NOTSET` that settings rejected.
#
# `WARN` and `FATAL` are `logging`'s own deprecated aliases, kept because an
# operator's muscle memory has them and honouring them costs nothing. `NOTSET`
# is deliberately NOT accepted: it is 0, so as a filtering threshold it means
# "emit everything", including records below DEBUG. That is not a level anyone
# selects on purpose, and silently accepting it would be the same class of
# surprise this function exists to remove.
LOG_LEVELS: Final = ("CRITICAL", "FATAL", "ERROR", "WARNING", "WARN", "INFO", "DEBUG")


def _numeric_level(level: str) -> int:
    """``level`` as a numeric threshold, raising rather than defaulting.

    A typo used to become ``INFO`` silently, so an operator raising verbosity
    during an incident got nothing and no warning. Case-insensitive, because
    ``HEPH_LOG_LEVEL=debug`` is the common convention and rejecting it would
    turn that same incident into a failed start.
    """
    if not isinstance(level, str) or level.upper() not in LOG_LEVELS:
        known = ", ".join(LOG_LEVELS)
        raise ValueError(f"unknown log level {level!r}: expected one of {known} (any case)")
    return logging.getLevelNamesMapping()[level.upper()]


def _configure_logging(level: str, words: frozenset[str] = REDACTED_KEYS) -> None:
    numeric = _numeric_level(level)
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


def configure_logging(level: str = "INFO", *, redact_keys: Iterable[str] = ()) -> None:
    """Install hephkit's structlog chain: contextvars -> trace ids -> redaction -> JSON.

    ``setup_observability`` calls this for you. Call it directly when you want
    the redacting logger without the tracing, or when you want it in place
    *before* setup: **redaction only holds for calls made after this runs.**
    Importing ``hephkit.observability`` configures nothing, so a product that
    logs before setting observability up — or that never sets it up — must call
    this itself, as early as it can, or its own structlog configuration applies
    and nothing is redacted.

    ``structlog.configure`` is process-global, so this replaces whatever
    configuration is in place. A product that owns its own chain should add
    ``hephkit``'s processors to it rather than call this: the pieces are
    ``structlog.contextvars.merge_contextvars``, then the trace-id and redaction
    processors, then a JSON renderer.

    ``redact_keys`` adds product-specific words to the default redaction set
    (see the module docstring for the matching rule). ``level`` must name a
    ``logging`` level; an unknown one raises ``ValueError`` rather than
    quietly becoming ``INFO``.
    """
    _configure_logging(level, REDACTED_KEYS | {_normalise(k) for k in redact_keys})


_warned_unconfigured = False


def get_logger(name: str) -> FilteringBoundLogger:
    """A structlog logger.

    Under hephkit's configuration it emits redacted JSON lines with trace ids —
    but only under hephkit's configuration. Importing this module no longer
    installs it, so until ``setup_observability`` or ``configure_logging`` has
    run, this returns a logger on whatever structlog is set to, **and nothing
    is redacted**: ``get_logger("t").info("hi", password="hunter2")`` prints the
    password. Redaction is a security property, so the first call made while
    structlog is unconfigured warns rather than leaving that to be discovered
    in a log file.
    """
    global _warned_unconfigured
    if not _warned_unconfigured and not structlog.is_configured():
        _warned_unconfigured = True  # once per process: a warning per log call is noise
        warnings.warn(
            "hephkit.observability.get_logger() was called before structlog was "
            "configured, so log records are NOT redacted and carry no trace ids. "
            "Call setup_observability(settings) or configure_logging() first.",
            RuntimeWarning,
            stacklevel=2,
        )
    logger: FilteringBoundLogger = structlog.get_logger(name)
    return logger


_lock = threading.Lock()
_active: Observability | None = None
SHUTDOWN_TIMEOUT: Final = 2.0
COLLECTOR_PROBE_TIMEOUT: Final = 0.25


class _NoOpSpanExporter(SpanExporter):
    """Drops spans without touching the network.

    Stands in for the OTLP exporter when no collector is configured or reachable.
    The alternative — ``BatchSpanProcessor`` retrying against a dead endpoint —
    costs a product that has no collector a stream of exporter tracebacks for
    the life of the process; measured in one ingot as 4,008 warnings and a
    suite that took 198 s.
    """

    def export(self, spans: Any) -> SpanExportResult:
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def _connects(endpoint: str, timeout: float) -> bool:
    parts = urlsplit(endpoint)
    host = parts.hostname
    if not host:
        return False
    port = parts.port or (443 if parts.scheme == "https" else 80)
    with contextlib.suppress(OSError, ValueError, OverflowError):
        with socket.create_connection((host, port), timeout=timeout):
            return True
    return False


def _collector_reachable(endpoint: str, timeout: float) -> bool:
    """Whether ``endpoint``'s host:port accepts a TCP connection within ``timeout``.

    Runs on a daemon thread joined with ``timeout``, which is what makes the
    bound real: ``socket.create_connection``'s own timeout covers the connect
    but NOT ``getaddrinfo``, so a name that resolves slowly blocks for as long
    as the resolver takes. Measured at 5,040 ms against a 250 ms budget for
    ``otel-collector.observability.svc.cluster.local`` — the most likely
    production value there is — after which the no-op exporter would have been
    installed for the life of the process. The thread is abandoned rather than
    waited on; it holds nothing but a socket and cannot delay interpreter exit.

    A timeout counts as unreachable, so in a dev or test environment with a
    slow resolver tracing is disabled. That is the right guess there and the
    wrong one in production, which is why the probe is off by default in
    ``prod`` (see ``_probe_budget``).
    """
    answer: list[bool] = []
    prober = threading.Thread(
        target=lambda: answer.append(_connects(endpoint, timeout)),
        name="hephkit-otel-probe",
        daemon=True,
    )
    prober.start()
    prober.join(timeout)
    return bool(answer) and answer[0]


def _probe_budget(settings: HephSettings, requested: float | None | str) -> float | None:
    """Seconds to spend probing, or ``None`` to skip the probe and always export.

    ``"auto"`` (the default) probes in ``dev`` and ``test`` and does NOT probe in
    ``prod``. The noise the probe answers — 4,008 exporter warnings and a 198 s
    suite in one ingot — is a dev and test problem, and ``HephSettings`` already
    carries ``env`` to tell them apart. A kit that other products adopt must
    never silently drop *production* traces to fix a test-suite annoyance, and a
    probe that guesses wrong in prod does exactly that. An explicit value is
    honoured in every environment, ``prod`` included.
    """
    if isinstance(requested, str):
        return None if settings.env == "prod" else COLLECTOR_PROBE_TIMEOUT
    return requested


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
        # A product that forgets to shut down still flushes once, boundedly, at
        # interpreter exit. Prefer an explicit lifespan (see the module
        # docstring): atexit runs too late to flush spans of a request that the
        # server is still finishing.
        atexit.register(self.shutdown)

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
        atexit.unregister(self.shutdown)
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
    probe_timeout: float | None | Literal["auto"] = "auto",
) -> Observability:
    """Configure tracing and logging in one call.

    ``redact_keys`` adds product-specific words to the default redaction set
    (see the module docstring for the matching rule).

    With no ``span_exporter``, spans go to ``settings.otlp_endpoint`` over OTLP
    HTTP. A blank endpoint always gets a no-op exporter. A non-blank one is
    probed first in ``dev`` and ``test``, and is NOT probed in ``prod``:

    * ``probe_timeout="auto"`` (the default) — probe with a
      ``COLLECTOR_PROBE_TIMEOUT`` budget in ``dev``/``test``, skip it in
      ``prod``. A product with no collector then pays nothing and emits no
      export retries where that noise actually hurts, while production traces
      are never dropped on the strength of one TCP connect.
    * ``probe_timeout=None`` — never probe; always build the OTLP exporter.
    * ``probe_timeout=<seconds>`` — probe with that budget in every
      environment, ``prod`` included.

    The probe is one connect on a daemon thread joined with the budget, so a
    slow-resolving name cannot delay startup, and it runs before the lock so it
    cannot delay another thread's setup either.

    Shutdown is registered with ``atexit``; a FastAPI product should call
    ``shutdown()`` from its lifespan instead (see the module docstring).

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
    # Probed OUTSIDE the lock: even bounded, this waits on the network, and
    # holding `_lock` across it would stall every other thread's setup. The
    # unsynchronised `_active` read only avoids a needless probe on a repeat
    # call; the authoritative check is still inside the lock below.
    endpoint = settings.otlp_endpoint.strip()
    reachable = True
    if span_exporter is None and endpoint and _active is None:
        budget = _probe_budget(settings, probe_timeout)
        if budget is not None:
            reachable = _collector_reachable(settings.otlp_endpoint, budget)
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
            elif endpoint and reachable:
                traces = endpoint.rstrip("/") + "/v1/traces"
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=traces)))
            else:
                # No collector: drop spans cheaply rather than retry forever.
                provider.add_span_processor(SimpleSpanProcessor(_NoOpSpanExporter()))
            _SWITCH.target = provider
            if isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
                trace.set_tracer_provider(_SWITCH)
            _configure_logging(settings.log_level, words)
            current = _active = Observability(settings, provider, words)
        if app is not None:
            current._instrument(app)
        return current
