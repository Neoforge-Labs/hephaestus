"""Tests for hephkit.observability and the generated hephkit.conventions."""

import asyncio
import json
import logging
import time
import typing
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from pydantic import ValidationError
from fastapi import FastAPI
import httpx
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from hephkit import conventions
from hephkit import observability as obs_module
from hephkit.errors.fastapi import install_error_handlers
from hephkit.observability import Observability, configure_logging, get_logger, setup_observability
from hephkit.settings import HephSettings


class TestClient:
    """Sync wrapper over httpx's ASGI transport (starlette's client warns, and
    the suite runs under ``-W error``). Unhandled errors become the 500."""

    __test__ = False

    def __init__(self, app: Any, **_ignored: Any) -> None:
        self._app = app

    def get(self, url: str) -> httpx.Response:
        async def go() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get(url)

        return asyncio.run(go())


def _settings(**kw: Any) -> HephSettings:
    return HephSettings(env="test", service_name="svc-a", **kw)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    # Importing the module configures nothing (see
    # test_importing_the_module_configures_no_logging), so every test that logs
    # without calling setup_observability has to install the chain the way a
    # consumer would.
    configure_logging()
    yield
    active = obs_module._active
    if active is not None:
        active.shutdown()


def _lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def _one(capsys: pytest.CaptureFixture[str], **kw: Any) -> dict[str, Any]:
    get_logger("t").info("x", **kw)
    (line,) = _lines(capsys)
    return line


# --- conventions -----------------------------------------------------------


def test_conventions_constants_and_pii() -> None:
    assert conventions.TENANT_ID == "tenant.id"
    assert conventions.USER_ID == "user.id"
    assert conventions.PII_ATTRIBUTES == frozenset({"user.id"})
    assert "idempotency.key" not in conventions.PII_ATTRIBUTES


# --- spans and correlation -------------------------------------------------


def test_server_span_has_resource_and_log_correlates(capsys: pytest.CaptureFixture[str]) -> None:
    exporter = InMemorySpanExporter()
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, str]:
        get_logger("api").info("in request", tenant_id="t1")
        return {"ok": "yes"}

    setup_observability(_settings(), app, span_exporter=exporter)
    assert TestClient(app).get("/ping").status_code == 200

    spans = exporter.get_finished_spans()
    server = [s for s in spans if s.kind.name == "SERVER"]
    assert len(server) == 1
    assert server[0].resource.attributes["service.name"] == "svc-a"
    assert server[0].resource.attributes["deployment.environment"] == "test"

    (line,) = [entry for entry in _lines(capsys) if entry["event"] == "in request"]
    assert line["trace_id"] == format(server[0].context.trace_id, "032x")
    assert line["span_id"] == format(server[0].context.span_id, "016x")
    assert line["tenant_id"] == "t1"
    assert line["level"] == "info"
    assert "timestamp" in line


def test_log_outside_a_span_has_no_trace_ids(capsys: pytest.CaptureFixture[str]) -> None:
    line = _one(capsys)
    assert "trace_id" not in line and "span_id" not in line


def test_problem_response_carries_the_same_trace_id() -> None:
    exporter = InMemorySpanExporter()
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("x")

    setup_observability(_settings(), app, span_exporter=exporter)
    body = TestClient(app).get("/boom").json()
    server = [s for s in exporter.get_finished_spans() if s.kind.name == "SERVER"]
    assert body["trace_id"] == format(server[0].context.trace_id, "032x")


def test_contextvars_are_merged(capsys: pytest.CaptureFixture[str]) -> None:
    structlog.contextvars.bind_contextvars(job_name="reindex")
    try:
        assert _one(capsys)["job_name"] == "reindex"
    finally:
        structlog.contextvars.clear_contextvars()


def test_contextvar_pii_is_redacted_too(capsys: pytest.CaptureFixture[str]) -> None:
    structlog.contextvars.bind_contextvars(user_id="u-1")
    try:
        assert _one(capsys)["user_id"] == "[REDACTED]"
    finally:
        structlog.contextvars.clear_contextvars()


# --- redaction -------------------------------------------------------------


def test_brief_case_redacts_password_and_user_id_keeps_amount(capsys: pytest.CaptureFixture[str]) -> None:
    line = _one(capsys, password="p", user_id="u", amount="10")
    assert line["password"] == "[REDACTED]"
    assert line["user_id"] == "[REDACTED]"
    assert line["amount"] == "10"
    assert line["event"] == "x"


@pytest.mark.parametrize("key", ["password", "secret", "token", "authorization", "api_key", "card_number", "cookie"])
def test_every_default_key_is_redacted(capsys: pytest.CaptureFixture[str], key: str) -> None:
    assert _one(capsys, **{key: "v"})[key] == "[REDACTED]"


def test_every_pii_attribute_is_redacted_dotted_and_underscored(capsys: pytest.CaptureFixture[str]) -> None:
    for name in conventions.PII_ATTRIBUTES:
        assert _one(capsys, **{name: "v"})[name] == "[REDACTED]"
        underscored = name.replace(".", "_")
        assert _one(capsys, **{underscored: "v"})[underscored] == "[REDACTED]"


def test_non_pii_attributes_are_kept_in_both_forms(capsys: pytest.CaptureFixture[str]) -> None:
    line = _one(capsys, **{"tenant.id": "t", "idempotency_key": "k", "idempotency.key": "k"})
    assert line["tenant.id"] == "t"
    assert line["idempotency_key"] == "k" and line["idempotency.key"] == "k"


def test_mixed_case_and_hyphens(capsys: pytest.CaptureFixture[str]) -> None:
    line = _one(capsys, Password="p", USER_ID="u", **{"API-Key": "k", "Set-Cookie": "c"})
    assert line["Password"] == line["USER_ID"] == line["API-Key"] == "[REDACTED]"
    assert line["Set-Cookie"] == "[REDACTED]"


def test_nested_dict_and_list_of_dicts(capsys: pytest.CaptureFixture[str]) -> None:
    line = _one(
        capsys,
        payload={"user": {"user.id": "u", "name": "n"}, "password": "p"},
        rows=[{"token": "t", "n": 1}, {"user_id": "u"}],
        pair=({"secret": "s"}, "plain"),
    )
    assert line["payload"] == {"user": {"user.id": "[REDACTED]", "name": "n"}, "password": "[REDACTED]"}
    assert line["rows"] == [{"token": "[REDACTED]", "n": 1}, {"user_id": "[REDACTED]"}]
    assert line["pair"] == [{"secret": "[REDACTED]"}, "plain"]  # JSON has no tuples


def test_non_string_values_are_redacted_whatever_their_type(capsys: pytest.CaptureFixture[str]) -> None:
    line = _one(capsys, password=1234, token=None, secret={"a": 1}, cookie=["x"], user_id=b"bytes")
    assert [line[k] for k in ("password", "token", "secret", "cookie", "user_id")] == ["[REDACTED]"] * 5


@pytest.mark.parametrize(
    "key",
    ["access_token", "set-cookie", "refresh_token", "api_key_id", "password_hint", "authorization_header",
     "X-Api-Key", "card_number_last4", "user.id.hash"],
)
def test_word_boundary_keys_are_redacted(capsys: pytest.CaptureFixture[str], key: str) -> None:
    assert _one(capsys, **{key: "v"})[key] == "[REDACTED]"


@pytest.mark.parametrize("key", ["amount", "my_token_count", "account_id", "tokens_used", "secretary", "mycookie"])
def test_keys_with_the_word_only_in_the_middle_or_inside_another_word_are_kept(
    capsys: pytest.CaptureFixture[str], key: str
) -> None:
    assert _one(capsys, **{key: "v"})[key] == "v"


def test_caller_added_keys_are_redacted_and_defaults_kept(capsys: pytest.CaptureFixture[str]) -> None:
    setup_observability(_settings(), span_exporter=InMemorySpanExporter(), redact_keys=["mpesa_passkey", "Paystack-Secret-Key"])
    line = _one(capsys, mpesa_passkey="a", paystack_secret_key="b", PAYSTACK_SECRET_KEY_LIVE="c", password="d", amount="1")
    assert line["mpesa_passkey"] == line["paystack_secret_key"] == line["PAYSTACK_SECRET_KEY_LIVE"] == "[REDACTED]"
    assert line["password"] == "[REDACTED]" and line["amount"] == "1"


def test_second_setup_with_different_redact_keys_raises() -> None:
    setup_observability(_settings(), span_exporter=InMemorySpanExporter(), redact_keys=["a_key"])
    with pytest.raises(RuntimeError, match="different settings"):
        setup_observability(_settings(), redact_keys=["b_key"])


def test_redaction_does_not_touch_values_that_look_secret(capsys: pytest.CaptureFixture[str]) -> None:
    assert _one(capsys, note="password")["note"] == "password"


def test_cyclic_structures_do_not_crash_logging(capsys: pytest.CaptureFixture[str]) -> None:
    loop: dict[str, Any] = {"password": "p"}
    loop["self"] = loop
    line = _one(capsys, loop=loop)
    assert line["loop"]["password"] == "[REDACTED]"
    node = line["loop"]
    while isinstance(node, dict) and "self" in node:
        node = node["self"]
    assert node == "[TRUNCATED]"


def test_unserialisable_values_do_not_crash_logging(capsys: pytest.CaptureFixture[str]) -> None:
    assert "object" in _one(capsys, thing=object())["thing"]


def test_log_level_filters_from_settings(capsys: pytest.CaptureFixture[str]) -> None:
    setup_observability(_settings(log_level="WARNING"), span_exporter=InMemorySpanExporter())
    get_logger("t").info("quiet")
    get_logger("t").warning("loud")
    assert [entry["event"] for entry in _lines(capsys)] == ["loud"]


def test_log_levels_are_case_insensitive_and_the_two_ends_agree() -> None:
    """`HEPH_LOG_LEVEL=debug` became a hard startup failure: the Literal was
    case-sensitive while `_configure_logging` uppercased, and `_numeric_level`'s
    own message advertised NOTSET/WARN/FATAL that settings rejected. The two
    ends disagreed in both directions; now they list exactly the same set."""
    from hephkit.settings import LogLevel

    literal = typing.get_args(typing.get_args(LogLevel)[0])
    assert set(literal) == set(obs_module.LOG_LEVELS), "settings and observability disagree"

    for spelling in ("debug", "Debug", "DEBUG", "dEbUg"):
        assert _settings(log_level=spelling).log_level == "DEBUG"
        assert obs_module._numeric_level(spelling) == logging.DEBUG

    # logging's own aliases are honoured; NOTSET is not a threshold anyone
    # selects on purpose (it is 0, i.e. emit everything below DEBUG too).
    assert _settings(log_level="warn").log_level == "WARN"
    assert obs_module._numeric_level("warn") == logging.WARNING
    with pytest.raises(ValidationError):
        _settings(log_level="NOTSET")
    with pytest.raises(ValueError, match="unknown log level"):
        obs_module._numeric_level("NOTSET")


def test_a_lowercase_level_actually_sets_the_threshold(capsys: pytest.CaptureFixture[str]) -> None:
    setup_observability(_settings(log_level="debug"), span_exporter=InMemorySpanExporter())
    get_logger("t").debug("shown now")
    assert [e["event"] for e in _lines(capsys)] == ["shown now"]


def test_an_unknown_log_level_is_rejected_not_silently_downgraded() -> None:
    """``HEPH_LOG_LEVEL=DEBUGG`` used to be accepted by settings and then
    silently become ``INFO`` here, so an operator raising verbosity during an
    incident got nothing and no warning. Both ends now refuse it."""
    with pytest.raises(ValidationError):
        _settings(log_level="NOPE")
    with pytest.raises(ValueError, match="unknown log level 'NOPE'"):
        obs_module._configure_logging("NOPE")


# --- idempotency -----------------------------------------------------------


def test_second_setup_with_same_settings_is_a_noop() -> None:
    first = setup_observability(_settings(), span_exporter=InMemorySpanExporter())
    provider = first.tracer_provider
    second = setup_observability(_settings(), span_exporter=InMemorySpanExporter())
    assert second is first and second.tracer_provider is provider


def test_second_setup_with_different_settings_raises() -> None:
    first = setup_observability(_settings(), span_exporter=InMemorySpanExporter())
    with pytest.raises(RuntimeError, match="different settings"):
        setup_observability(HephSettings(env="test", service_name="other"))  # type: ignore[call-arg]
    assert obs_module._active is first  # unchanged


def test_second_setup_instruments_a_new_app_once() -> None:
    exporter = InMemorySpanExporter()
    first_app, second_app = FastAPI(), FastAPI()
    for app in (first_app, second_app):
        app.get("/p")(lambda: {})
    o = setup_observability(_settings(), first_app, span_exporter=exporter)
    setup_observability(_settings(), first_app)  # same app again: no double wrap
    setup_observability(_settings(), second_app)
    TestClient(second_app).get("/p")
    TestClient(first_app).get("/p")
    assert len([s for s in exporter.get_finished_spans() if s.kind.name == "SERVER"]) == 2
    assert len(o._apps) == 2


def test_shutdown_allows_reconfiguration_and_is_idempotent() -> None:
    first = setup_observability(_settings(), span_exporter=InMemorySpanExporter())
    first.shutdown()
    first.shutdown()
    second = setup_observability(
        HephSettings(env="test", service_name="other"),  # type: ignore[call-arg]
        span_exporter=InMemorySpanExporter(),
    )
    assert second is not first and second.settings.service_name == "other"


def test_shutdown_uninstruments_the_app() -> None:
    exporter = InMemorySpanExporter()
    app = FastAPI()
    app.get("/p")(lambda: {})
    o = setup_observability(_settings(), app, span_exporter=exporter)
    o.shutdown()
    exporter.clear()
    TestClient(app).get("/p")
    assert exporter.get_finished_spans() == ()


# --- no network on import or setup -----------------------------------------


def test_setup_with_unreachable_collector_neither_blocks_nor_raises() -> None:
    app = FastAPI()
    app.get("/p")(lambda: {})
    started = time.monotonic()
    o = setup_observability(_settings(otlp_endpoint="http://127.0.0.1:1"), app, probe_timeout=None)
    assert isinstance(o, Observability)
    assert TestClient(app).get("/p").status_code == 200
    assert time.monotonic() - started < 2.0


def test_shutdown_is_bounded_with_an_unreachable_collector() -> None:
    o = setup_observability(_settings(otlp_endpoint="http://127.0.0.1:1"), probe_timeout=None)
    o.tracer_provider.get_tracer("t").start_span("pending").end()
    started = time.monotonic()
    o.shutdown(timeout=1.0)
    assert time.monotonic() - started < 2.0


def test_default_shutdown_bound_is_two_seconds() -> None:
    assert obs_module.SHUTDOWN_TIMEOUT == 2.0
    o = setup_observability(_settings(otlp_endpoint="http://127.0.0.1:1"), probe_timeout=None)
    o.tracer_provider.get_tracer("t").start_span("pending").end()
    started = time.monotonic()
    o.shutdown()
    assert time.monotonic() - started < 4.0


def test_shutdown_flushes_promptly_to_a_reachable_collector() -> None:
    import http.server
    import threading

    received: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            received.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        o = setup_observability(_settings(otlp_endpoint=f"http://127.0.0.1:{server.server_port}"))
        o.tracer_provider.get_tracer("t").start_span("sent").end()
        started = time.monotonic()
        o.shutdown()
        assert time.monotonic() - started < 1.5
        assert received == ["/v1/traces"]
    finally:
        server.shutdown()
        server.server_close()


def test_setup_after_shutdown_installs_a_working_global_tracer() -> None:
    from opentelemetry import trace

    first_exporter, second_exporter = InMemorySpanExporter(), InMemorySpanExporter()
    first = setup_observability(_settings(), span_exporter=first_exporter)
    held = trace.get_tracer("held-across-restart")
    held.start_span("one").end()
    first.shutdown()
    held.start_span("while-down").end()  # no-op, must not raise
    setup_observability(_settings(), span_exporter=second_exporter)
    held.start_span("two").end()
    trace.get_tracer("fresh").start_span("three").end()
    assert [s.name for s in first_exporter.get_finished_spans()] == ["one"]
    assert [s.name for s in second_exporter.get_finished_spans()] == ["two", "three"]


def test_global_tracer_start_as_current_span_goes_through_the_switch() -> None:
    from opentelemetry import trace

    exporter = InMemorySpanExporter()
    setup_observability(_settings(), span_exporter=exporter)
    with trace.get_tracer("t").start_as_current_span("cm") as span:
        assert span.get_span_context().is_valid
    assert [s.name for s in exporter.get_finished_spans()] == ["cm"]


def test_default_exporter_targets_the_settings_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class FakeExporter(InMemorySpanExporter):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__()
            seen.update(kwargs)

    monkeypatch.setattr(obs_module, "OTLPSpanExporter", FakeExporter)
    setup_observability(_settings(otlp_endpoint="http://collector.invalid:54318/"), probe_timeout=None)
    assert seen == {"endpoint": "http://collector.invalid:54318/v1/traces"}


# --- no collector: no-op exporter, no retry noise ---------------------------


def _processors(o: Observability) -> list[Any]:
    # The SDK keeps processors in a MultiSpanProcessor; reach the exporters.
    active = o.tracer_provider._active_span_processor._span_processors
    return [getattr(p, "span_exporter", None) for p in active]


def test_an_unreachable_collector_gets_the_no_op_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**kwargs: Any) -> None:
        raise AssertionError("the OTLP exporter must not be built for an unreachable collector")

    monkeypatch.setattr(obs_module, "OTLPSpanExporter", boom)
    o = setup_observability(_settings(otlp_endpoint="http://127.0.0.1:1"))
    (exporter,) = _processors(o)
    assert isinstance(exporter, obs_module._NoOpSpanExporter)
    o.tracer_provider.get_tracer("t").start_span("dropped").end()  # must not raise


def test_a_blank_endpoint_gets_the_no_op_exporter_without_probing(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a blank endpoint must not be probed")

    monkeypatch.setattr(obs_module, "_collector_reachable", boom)
    o = setup_observability(_settings(otlp_endpoint="  "))
    (exporter,) = _processors(o)
    assert isinstance(exporter, obs_module._NoOpSpanExporter)


def test_a_reachable_collector_still_gets_the_otlp_exporter() -> None:
    import socket as _socket

    listener = _socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        o = setup_observability(_settings(otlp_endpoint=f"http://127.0.0.1:{port}"))
        (exporter,) = _processors(o)
        assert isinstance(exporter, OTLPSpanExporter)
    finally:
        listener.close()


def test_probe_reads_the_scheme_default_port_and_fails_closed() -> None:
    assert obs_module._collector_reachable("http://127.0.0.1:1", 0.25) is False
    assert obs_module._collector_reachable("not a url at all", 0.25) is False
    assert obs_module._collector_reachable("", 0.25) is False


def test_the_no_op_exporter_reports_success_and_flushes() -> None:
    exporter = obs_module._NoOpSpanExporter()
    assert exporter.export([]) is SpanExportResult.SUCCESS
    assert exporter.force_flush() is True
    assert exporter.shutdown() is None


def test_the_default_probe_is_time_bounded_even_when_dns_hangs() -> None:
    """The wave that added the probe used `socket.create_connection`, whose
    timeout covers the connect but NOT getaddrinfo, so a slow-resolving name
    blocked for as long as the resolver took -- measured at 5,040 ms against a
    250 ms budget -- and then installed the no-op exporter for the process
    lifetime. The probe now runs on a joined daemon thread.

    Deliberately asserts the DEFAULT path: passing probe_timeout=None (which
    every other unreachable-collector test does, to keep the OTLP exporter in
    play) is exactly how the regression went uncaught."""
    settings = _settings(otlp_endpoint="http://otel.invalid.example.test:4318")
    started = time.monotonic()
    o = setup_observability(settings)
    elapsed = time.monotonic() - started
    # Generous against CI jitter, and still an order of magnitude under the
    # 5 s a hanging resolver cost.
    assert elapsed < 2.0, f"setup took {elapsed:.2f}s; the probe is not bounded"
    (exporter,) = _processors(o)
    assert isinstance(exporter, obs_module._NoOpSpanExporter)


def test_the_probe_bound_covers_name_resolution_not_just_connect() -> None:
    slow = "otel-collector.observability.svc.cluster.local"
    started = time.monotonic()
    assert obs_module._collector_reachable(f"http://{slow}:4318", 0.25) is False
    elapsed = time.monotonic() - started
    assert elapsed < 1.5, f"resolving {slow} took {elapsed:.2f}s; the join is not bounding it"


def test_prod_never_probes_so_production_traces_are_not_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A kit other products adopt must not silently drop production traces to
    fix a test-suite annoyance. The probe answers dev/test noise, and `env`
    already tells the two apart."""
    def boom(*args: Any, **kwargs: Any) -> bool:
        raise AssertionError("prod must not be probed by default")

    monkeypatch.setattr(obs_module, "_collector_reachable", boom)
    prod = HephSettings(  # type: ignore[call-arg]
        env="prod", service_name="svc-a", database_url="postgresql://x", otlp_endpoint="http://127.0.0.1:1"
    )
    o = setup_observability(prod)
    (exporter,) = _processors(o)
    assert isinstance(exporter, OTLPSpanExporter), "prod must export without probing"


def test_an_explicit_probe_timeout_is_honoured_in_prod_too() -> None:
    prod = HephSettings(  # type: ignore[call-arg]
        env="prod", service_name="svc-a", database_url="postgresql://x", otlp_endpoint="http://127.0.0.1:1"
    )
    o = setup_observability(prod, probe_timeout=0.25)
    (exporter,) = _processors(o)
    assert isinstance(exporter, obs_module._NoOpSpanExporter)


def test_probe_budget_resolves_the_three_spellings() -> None:
    dev, prod = _settings(), HephSettings(  # type: ignore[call-arg]
        env="prod", service_name="s", database_url="postgresql://x"
    )
    assert obs_module._probe_budget(dev, "auto") == obs_module.COLLECTOR_PROBE_TIMEOUT
    assert obs_module._probe_budget(prod, "auto") is None
    assert obs_module._probe_budget(dev, None) is None
    assert obs_module._probe_budget(prod, 0.5) == 0.5


# --- shutdown is registered, not merely available ---------------------------


def test_atexit_flushes_a_product_that_forgot_to_shut_down() -> None:
    """Nothing used to call ``shutdown()``, so a product that forgot left the
    batch processor exporting until the process died. ``atexit`` runs handlers
    LIFO, so a probe registered *before* setup runs *after* hephkit's own
    handler and can see that it ran."""
    out = _run(
        "import atexit\n"
        "from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter\n"
        "import hephkit.observability as obs\n"
        "from hephkit.settings import HephSettings\n"
        "atexit.register(lambda: print('after hephkit shutdown, active =', obs._active))\n"
        "obs.setup_observability(HephSettings(env='test', service_name='s'),"
        " span_exporter=InMemorySpanExporter())\n"
        "assert obs._active is not None\n"
        "print('exiting with observability still set up')\n"
    )
    assert out.splitlines() == [
        "exiting with observability still set up",
        "after hephkit shutdown, active = None",
    ]


def test_shutdown_unregisters_itself_so_a_second_call_is_harmless() -> None:
    o = setup_observability(_settings(), span_exporter=InMemorySpanExporter())
    o.shutdown()
    o.shutdown()  # the atexit copy, after an explicit lifespan shutdown
    assert obs_module._active is None


# --- import hygiene ----------------------------------------------------------


def _run(code: str) -> str:
    import subprocess
    import sys

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def test_other_modules_do_not_need_the_observability_extra() -> None:
    out = _run(
        "import sys, hephkit.money, hephkit.errors, hephkit.hashing, hephkit.signatures;"
        "print(any(m.split('.')[0] in ('structlog', 'hephkit.observability') or m == 'hephkit.observability' for m in sys.modules))"
    )
    assert out == "False"


def test_importing_the_module_configures_no_logging() -> None:
    """Importing a library must not take a consumer's structlog chain over.

    One ingot owns structlog itself and had to re-apply its own configuration
    *after* ``setup_observability``, which cost it the trace-id processor, so
    its log lines carried no ``trace_id`` while its problem+json bodies did.
    Configuration is now opt-in: ``setup_observability``, or the public
    ``configure_logging``."""
    out = _run(
        "import structlog, hephkit.observability as obs\n"
        "mine = lambda: any(p is obs._add_trace_ids for p in structlog.get_config()['processors'])\n"
        "print(mine())\n"
        "obs.configure_logging()\n"
        "print(mine())\n"
    )
    before, after = out.splitlines()
    # structlog's default chain happens to be 6 long too, so identify ours by
    # the two processors only hephkit installs.
    assert before == "False"
    assert after == "True"


def test_configure_logging_redacts_and_takes_extra_words(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG", redact_keys=["paystack_secret_key"])
    line = _one(capsys, paystack_secret_key="k", password="p", amount="10")
    assert line["paystack_secret_key"] == "[REDACTED]"
    assert line["password"] == "[REDACTED]"
    assert line["amount"] == "10"


def test_configure_logging_rejects_an_unknown_level() -> None:
    with pytest.raises(ValueError, match="unknown log level 'DEBUGG'"):
        configure_logging("DEBUGG")


def test_get_logger_warns_once_when_structlog_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Making configuration opt-in left `get_logger`'s docstring promising
    redaction it no longer delivered, at the exact call site a consumer reads.
    Redaction is a security property, so an unconfigured call says so."""
    monkeypatch.setattr(obs_module, "_warned_unconfigured", False)
    monkeypatch.setattr(structlog, "is_configured", lambda: False)
    with pytest.warns(RuntimeWarning, match="NOT redacted"):
        get_logger("t")
    # Once per process: a warning per log call would be noise.
    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")
        get_logger("t")


def test_get_logger_does_not_warn_once_configured() -> None:
    import warnings as _w

    configure_logging()
    with _w.catch_warnings():
        _w.simplefilter("error")
        get_logger("t")


def test_the_configured_logger_really_does_redact(capsys: pytest.CaptureFixture[str]) -> None:
    """The promise `get_logger`'s docstring makes, held to."""
    configure_logging()
    line = _one(capsys, password="hunter2", api_key="sk_live_abc")
    assert line["password"] == "[REDACTED]" and line["api_key"] == "[REDACTED]"
    assert "hunter2" not in json.dumps(line) and "sk_live_abc" not in json.dumps(line)


def test_importing_observability_opens_no_sockets() -> None:
    out = _run(
        "import socket\n"
        "def boom(*a, **k): raise AssertionError('network at import')\n"
        "socket.socket.connect = boom; socket.create_connection = boom; socket.getaddrinfo = boom\n"
        "import hephkit.observability; print('ok')"
    )
    assert out == "ok"


# --- repr/container leaks and non-JSON keys ----------------------------------

import collections  # noqa: E402
import dataclasses  # noqa: E402

from pydantic import BaseModel, SecretStr  # noqa: E402


@dataclasses.dataclass
class _D:
    password: str
    name: str = "n"


@dataclasses.dataclass(frozen=True)
class _F:
    password: str


class _M(BaseModel):
    password: str
    name: str = "n"


class _Opaque:
    def __init__(self) -> None:
        self.password = "OPAQUELEAK"

    def __repr__(self) -> str:
        return f"Opaque(password={self.password!r})"


def _rendered(capsys: pytest.CaptureFixture[str], **kw: Any) -> str:
    get_logger("t").info("x", **kw)
    return capsys.readouterr().out


@pytest.mark.parametrize(
    ("field", "value", "secret"),
    [
        ("dc", _D(password="HUNTER2"), "HUNTER2"),
        ("dq", collections.deque([{"password": "DEQLEAK"}]), "DEQLEAK"),
        ("it", {"password": "SETLEAK"}.items(), "SETLEAK"),
        ("pm", _M(password="PYDLEAK"), "PYDLEAK"),
        ("st", {_F(password="FSLEAK")}, "FSLEAK"),
        ("vals", {"a": {"password": "VALLEAK"}}.values(), "VALLEAK"),
        ("opaque", _Opaque(), "OPAQUELEAK"),
        ("nested", [{"inner": _D(password="NESTLEAK")}], "NESTLEAK"),
        ("sec", _M.model_construct(password=SecretStr("SECLEAK")), "SECLEAK"),
    ],
)
def test_secret_values_never_reach_the_rendered_line(
    capsys: pytest.CaptureFixture[str], field: str, value: object, secret: str
) -> None:
    out = _rendered(capsys, **{field: value})
    assert secret not in out
    json.loads(out)  # still one valid JSON line


def test_known_shapes_are_expanded_and_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    line = _one(
        capsys,
        ctl={"password": "p"},
        dc=_D(password="x"),
        dq=collections.deque([{"password": "x"}]),
        it={"password": "x"}.items(),
        pm=_M(password="x"),
    )
    assert line["ctl"] == {"password": "[REDACTED]"}
    assert line["dc"] == {"password": "[REDACTED]", "name": "n"}
    assert line["dq"] == [{"password": "[REDACTED]"}]
    assert line["it"] == {"password": "[REDACTED]"}
    assert line["pm"] == {"password": "[REDACTED]", "name": "n"}


def test_unknown_objects_render_as_their_type_only(capsys: pytest.CaptureFixture[str]) -> None:
    assert _one(capsys, o=_Opaque(), e=ValueError("secret text"))["o"] == "<_Opaque>"


def test_common_scalars_stay_readable(capsys: pytest.CaptureFixture[str]) -> None:
    import datetime
    import decimal
    import uuid

    u = uuid.UUID(int=1)
    line = _one(capsys, d=datetime.date(2026, 1, 2), n=decimal.Decimal("1.50"), u=u, b=b"raw")
    assert line["d"] == "2026-01-02" and line["n"] == "1.50" and line["u"] == str(u) and line["b"] == "<bytes>"


def test_failing_dump_falls_back_to_type_name(capsys: pytest.CaptureFixture[str]) -> None:
    class Bad(BaseModel):
        x: int = 1

        def model_dump(self, **_: Any) -> dict[str, Any]:  # type: ignore[override]
            raise RuntimeError("boom")

    @dataclasses.dataclass
    class BadDC:
        f: Any

    class Unclonable:
        def __deepcopy__(self, memo: Any) -> None:
            raise RuntimeError("no")

    line = _one(capsys, a=Bad(), b=BadDC(f=Unclonable()))
    assert line["a"] == "<Bad>" and line["b"] == "<BadDC>"


def test_non_json_dict_keys_do_not_raise(capsys: pytest.CaptureFixture[str]) -> None:
    line = _one(capsys, d={("a", 1): "t", b"k": "b", 7: "i", None: "n", "ok": 1})
    assert line["d"] == {"<tuple>": "[REDACTED]", "k": "b", "7": "i", "null": "n", "ok": 1}


def test_redacted_bytes_key_is_still_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    out = _rendered(capsys, d={b"password": "BYTESLEAK", b"access_token": "T2"})
    assert "BYTESLEAK" not in out and "T2" not in out
    assert json.loads(out)["d"] == {"password": "[REDACTED]", "access_token": "[REDACTED]"}


class _RG:
    def __repr__(self) -> str:
        return "RG(password='RGLEAK')"

    __str__ = __repr__


class _BadClass:
    @property  # type: ignore[misc]
    def __class__(self) -> type:  # type: ignore[override]
        raise RuntimeError("no class")


def test_object_and_tuple_keys_never_leak_through_repr(capsys: pytest.CaptureFixture[str]) -> None:
    out = _rendered(capsys, a={_RG(): "VALLEAK"}, b={("password", "TUPLEAK"): "V2"})
    assert "RGLEAK" not in out and "TUPLEAK" not in out and "VALLEAK" not in out and "V2" not in out
    assert json.loads(out)["a"] == {"<_RG>": "[REDACTED]"}
    assert json.loads(out)["b"] == {"<tuple>": "[REDACTED]"}


def test_huge_int_keys_do_not_raise(capsys: pytest.CaptureFixture[str]) -> None:
    assert json.loads(_rendered(capsys, d={10**5000: "x"}))["d"] == {"<int>": "[REDACTED]"}


def test_memoryview_is_opaque(capsys: pytest.CaptureFixture[str]) -> None:
    out = _rendered(capsys, mv=memoryview(b"MVLEAK"))
    assert json.loads(out)["mv"] == "<memoryview>"
    assert "77" not in out.split('"event"')[0]


def test_object_whose_class_raises_does_not_drop_the_line(capsys: pytest.CaptureFixture[str]) -> None:
    line = _one(capsys, bad=_BadClass(), keep="yes")
    assert line["keep"] == "yes" and line["event"] == "x"
    assert isinstance(line["bad"], str) and line["bad"].startswith("<")


def test_enum_and_timedelta_keep_their_values(capsys: pytest.CaptureFixture[str]) -> None:
    import datetime
    import enum

    class Color(enum.Enum):
        RED = "red"

    class Level(enum.IntEnum):
        HIGH = 3

    line = _one(capsys, c=Color.RED, i=Level.HIGH, td=datetime.timedelta(seconds=90))
    assert line["c"] == "red" and line["i"] == 3 and line["td"] == "0:01:30"


def test_enum_holding_a_secret_shaped_value_is_still_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    import enum

    class E(enum.Enum):
        V = {"password": "ENUMLEAK"}

    assert "ENUMLEAK" not in _rendered(capsys, e=E.V)


def test_huge_int_value_does_not_raise(capsys: pytest.CaptureFixture[str]) -> None:
    line = _one(capsys, big=10**5000, ok=10**30, nested=[10**5000])
    assert line["big"] == "<int>" and line["ok"] == 10**30 and line["nested"] == ["<int>"]


class _RaisingInt(int):
    def __str__(self) -> str:
        raise RuntimeError("no str")


def test_key_whose_str_raises_does_not_collapse_the_mapping(capsys: pytest.CaptureFixture[str]) -> None:
    line = _one(capsys, n={_RaisingInt(4): 1, "z": 2}, keep=1)
    assert line["n"] == {"4": 1, "z": 2}  # read via int.__repr__, as json does
    assert line["keep"] == 1


def test_key_whose_class_raises_fails_closed_without_collapsing_the_mapping(
    capsys: pytest.CaptureFixture[str],
) -> None:
    line = _one(capsys, n={_BadClass(): "KEYBADLEAK", "z": 2}, keep=1)
    assert line["n"] == {"<_BadClass>": "[REDACTED]", "z": 2}
    assert line["keep"] == 1


class _StrEnumKey(str, __import__("enum").Enum):
    A = "password"


class _LyingStr(str):
    def __str__(self) -> str:
        return "harmless"


class _LyingInt(int):
    def __str__(self) -> str:
        return "harmless"

    __repr__ = __str__


@pytest.mark.parametrize(
    ("key", "secret"),
    [
        (_StrEnumKey.A, "ENUMKEYLEAK"),
        (_LyingStr("password"), "STRSUBLEAK"),
        (_LyingStr("user.id"), "STRSUBPII"),
        (_LyingStr("access_token"), "STRSUBTOKEN"),
    ],
)
def test_key_the_serialiser_would_write_is_the_key_that_is_matched(
    capsys: pytest.CaptureFixture[str], key: object, secret: str
) -> None:
    out = _rendered(capsys, m={key: secret})
    assert secret not in out
    assert "[REDACTED]" in out


def test_int_subclass_key_is_matched_and_emitted_by_its_data(capsys: pytest.CaptureFixture[str]) -> None:
    out = _rendered(capsys, m={_LyingInt(12345): "INTSUBVAL", "amount": "ok"})
    assert json.loads(out)["m"] == {"12345": "INTSUBVAL", "amount": "ok"}


def test_key_controls_still_behave(capsys: pytest.CaptureFixture[str]) -> None:
    out = _rendered(capsys, m={"password": "CTLSECRET", "amount": "10", "tenant.id": "t1"})
    assert "CTLSECRET" not in out
    assert json.loads(out)["m"] == {"password": "[REDACTED]", "amount": "10", "tenant.id": "t1"}


def test_bool_and_float_keys_render_as_json_does(capsys: pytest.CaptureFixture[str]) -> None:
    assert _one(capsys, m={True: 1, False: 2, 1.5: 3})["m"] == {"true": 1, "false": 2, "1.5": 3}
