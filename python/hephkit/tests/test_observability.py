"""Tests for hephkit.observability and the generated hephkit.conventions."""

import asyncio
import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from fastapi import FastAPI
import httpx
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from hephkit import conventions
from hephkit import observability as obs_module
from hephkit.errors.fastapi import install_error_handlers
from hephkit.observability import Observability, get_logger, setup_observability
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
    assert line["Set-Cookie"] == "c"  # exact matching only; not a registered name


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


def test_keys_that_merely_contain_a_redacted_word_are_kept(capsys: pytest.CaptureFixture[str]) -> None:
    # Documented decision: exact match only. Substring matching would blank
    # fields like my_token_count and make the boundary unpredictable.
    line = _one(capsys, password_hint="h", my_token_count=3, tokens_used=4)
    assert line["password_hint"] == "h"
    assert line["my_token_count"] == 3
    assert line["tokens_used"] == 4


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


def test_unknown_log_level_falls_back_to_info(capsys: pytest.CaptureFixture[str]) -> None:
    setup_observability(_settings(log_level="NOPE"), span_exporter=InMemorySpanExporter())
    get_logger("t").debug("quiet")
    get_logger("t").info("shown")
    assert [entry["event"] for entry in _lines(capsys)] == ["shown"]


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
    o = setup_observability(_settings(otlp_endpoint="http://127.0.0.1:1"), app)
    assert isinstance(o, Observability)
    assert TestClient(app).get("/p").status_code == 200
    assert time.monotonic() - started < 2.0


def test_default_exporter_targets_the_settings_endpoint() -> None:
    o = setup_observability(_settings(otlp_endpoint="http://collector.invalid:54318/"))
    (processor,) = o.tracer_provider._active_span_processor._span_processors  # type: ignore[attr-defined]
    assert processor.span_exporter._endpoint == "http://collector.invalid:54318/v1/traces"
    o.tracer_provider.force_flush = lambda *_a, **_k: True  # type: ignore[method-assign,assignment]


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


def test_importing_observability_opens_no_sockets() -> None:
    out = _run(
        "import socket\n"
        "def boom(*a, **k): raise AssertionError('network at import')\n"
        "socket.socket.connect = boom; socket.create_connection = boom; socket.getaddrinfo = boom\n"
        "import hephkit.observability; print('ok')"
    )
    assert out == "ok"
