"""hephkit.errors: HephError, generated codes and the FastAPI problem+json layer."""

import asyncio
import re
from typing import Any

import pytest
from fastapi import FastAPI
import httpx
from opentelemetry.sdk.trace import TracerProvider
from pydantic import BaseModel

from hephkit import errors
from hephkit.errors import HephError, _codes
from hephkit.errors.fastapi import install_error_handlers
from hephkit.hashing import HashingError, canonical_json
from hephkit.money import Money, MoneyError
from hephkit.signatures import SignatureError, verify

TYPE_BASE = "https://heph.neoforgelabs.tech/errors/"
PROBLEM = "application/problem+json"
SECRET_TEXT = "db password hunter2 at /srv/app/secret.py"


class Item(BaseModel):
    name: str
    qty: int


class CodedError(Exception):
    """A foreign exception that carries a registry code, like our core ones."""

    def __init__(self, code: str) -> None:
        super().__init__(SECRET_TEXT)
        self.code = code


def _app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/heph")
    def heph() -> None:
        raise HephError("HEPH-IDEMP-409")

    @app.get("/heph-detail")
    def heph_detail() -> None:
        raise HephError("HEPH-NF-404", "Invoice not found.", invoice="inv_1")

    @app.get("/money")
    def money() -> None:
        Money.parse("12.345", "USD")

    @app.get("/signature")
    def signature() -> None:
        verify("whsec_dGVzdA==", {}, b"{}")

    @app.get("/hashing")
    def hashing() -> None:
        canonical_json(float("nan"))

    @app.get("/hashing-codeless")
    def hashing_codeless() -> None:
        raise HashingError("boom")

    @app.get("/coded")
    def coded() -> None:
        raise CodedError("HEPH-RATE-429")

    @app.get("/coded-unknown")
    def coded_unknown() -> None:
        raise CodedError("HEPH-ZZ-999")

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(SECRET_TEXT)

    @app.post("/items")
    def items(item: Item) -> Item:
        return item

    return app


class TestClient:
    """Sync wrapper over httpx's ASGI transport.

    ``starlette.testclient`` warns that httpx support is deprecated, and the
    suite runs under ``-W error``; driving the ASGI app directly avoids it.
    Unhandled exceptions become the 500 response instead of being re-raised.
    """

    __test__ = False

    def __init__(self, app: Any) -> None:
        self._app = app

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def go() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.request(method, url, **kwargs)

        return asyncio.run(go())

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)


class SpanApp:
    """ASGI wrapper holding a server span open around the app, as OpenTelemetry's
    ASGI instrumentation does, so error handlers run with a span active."""

    def __init__(self, app: Any) -> None:
        self._app = app
        self.trace_ids: list[str] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        with TracerProvider().get_tracer("test").start_as_current_span("request") as span:
            self.trace_ids.append(format(span.get_span_context().trace_id, "032x"))
            await self._app(scope, receive, send)


@pytest.fixture
def app() -> FastAPI:
    return _app()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _body(response: httpx.Response) -> dict[str, Any]:
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert isinstance(body, dict)
    return body


# --- HephError --------------------------------------------------------------


def test_heph_error_properties() -> None:
    err = HephError("HEPH-IDEMP-409")
    assert err.code == "HEPH-IDEMP-409"
    assert err.status == 409
    assert err.title == "Original request still in flight"
    assert err.type_url == TYPE_BASE + "HEPH-IDEMP-409"
    assert err.detail is None
    assert isinstance(err, Exception)


def test_heph_error_unknown_code_raises_value_error() -> None:
    with pytest.raises(ValueError, match="HEPH-ZZ-999"):
        HephError("HEPH-ZZ-999")
    with pytest.raises(ValueError):
        HephError("not a code")


def test_heph_error_rejects_reserved_extension_names() -> None:
    # `code` and `detail` are parameters, so they can never be extensions.
    for name in ("type", "title", "status", "trace_id"):
        with pytest.raises(ValueError, match=name):
            HephError("HEPH-GEN-500", **{name: "x"})


def test_generated_constants_match_registry() -> None:
    assert _codes.IDEMP_409 == "HEPH-IDEMP-409"
    assert _codes.GEN_500 == "HEPH-GEN-500"
    assert _codes.REGISTRY["HEPH-IDEMP-409"] == (409, "Original request still in flight")
    for code, (status, title) in _codes.REGISTRY.items():
        assert re.fullmatch(r"HEPH-[A-Z]{2,6}-[0-9]{3}", code)
        assert 400 <= status <= 599 and title
    assert errors.IDEMP_409 == _codes.IDEMP_409  # re-exported


def test_package_import_does_not_pull_in_fastapi() -> None:
    import subprocess
    import sys

    code = "import sys, hephkit.errors; sys.exit('fastapi' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


# --- FastAPI layer ------------------------------------------------------------


def test_heph_error_response_shape(client: TestClient) -> None:
    response = client.get("/heph")
    assert response.status_code == 409
    assert _body(response) == {
        "type": TYPE_BASE + "HEPH-IDEMP-409",
        "title": "Original request still in flight",
        "status": 409,
        "detail": "Original request still in flight",
        "code": "HEPH-IDEMP-409",
    }


def test_no_trace_id_member_when_no_span_is_active(client: TestClient) -> None:
    assert "trace_id" not in _body(client.get("/heph"))


def test_trace_id_present_when_span_is_active(app: FastAPI) -> None:
    wrapped = SpanApp(app)
    body = _body(TestClient(wrapped).get("/heph"))
    assert re.fullmatch(r"[0-9a-f]{32}", body["trace_id"])
    assert body["trace_id"] == wrapped.trace_ids[0]


def test_detail_and_extensions_are_carried(client: TestClient) -> None:
    response = client.get("/heph-detail")
    assert response.status_code == 404
    body = _body(response)
    assert body["detail"] == "Invoice not found."
    assert body["invoice"] == "inv_1"
    assert body["code"] == "HEPH-NF-404"


def test_money_error_maps_to_422(client: TestClient) -> None:
    response = client.get("/money")
    assert response.status_code == 422
    body = _body(response)
    assert body["code"] == "HEPH-MONEY-422"
    assert body["status"] == 422
    assert body["title"] == "Invalid money amount"
    assert body["type"] == TYPE_BASE + "HEPH-MONEY-422"
    assert isinstance(MoneyError("x"), ValueError)


def test_signature_error_maps_to_401(client: TestClient) -> None:
    response = client.get("/signature")
    assert response.status_code == 401
    body = _body(response)
    assert body["code"] == "HEPH-WH-401"
    assert body["status"] == 401
    assert issubclass(SignatureError, ValueError)


def test_any_exception_with_a_registry_code_is_mapped_by_code(client: TestClient) -> None:
    response = client.get("/coded")
    assert response.status_code == 429
    body = _body(response)
    assert body["code"] == "HEPH-RATE-429"
    assert SECRET_TEXT not in response.text


def test_exception_with_unregistered_code_is_a_500(client: TestClient) -> None:
    response = client.get("/coded-unknown")
    assert response.status_code == 500
    assert _body(response)["code"] == "HEPH-GEN-500"
    assert "HEPH-ZZ-999" not in response.text
    assert SECRET_TEXT not in response.text


def test_hashing_error_maps_by_its_code(client: TestClient) -> None:
    response = client.get("/hashing")
    assert response.status_code == 422
    assert _body(response)["code"] == "HEPH-VAL-422"


def test_hashing_error_without_code_is_a_500(client: TestClient) -> None:
    response = client.get("/hashing-codeless")
    assert response.status_code == 500
    assert _body(response)["code"] == "HEPH-GEN-500"


def test_unhandled_exception_is_500_and_does_not_leak(client: TestClient) -> None:
    response = client.get("/boom")
    assert response.status_code == 500
    body = _body(response)
    assert body == {
        "type": TYPE_BASE + "HEPH-GEN-500",
        "title": "Internal error",
        "status": 500,
        "detail": "Internal error",
        "code": "HEPH-GEN-500",
    }
    for fragment in ("hunter2", "/srv/app", "secret.py", "RuntimeError", "Traceback"):
        assert fragment not in response.text


def test_unhandled_exception_carries_trace_id_when_span_active(app: FastAPI) -> None:
    wrapped = SpanApp(app)
    response = TestClient(wrapped).get("/boom")
    assert response.status_code == 500
    assert response.json()["trace_id"] == wrapped.trace_ids[0]
    assert SECRET_TEXT not in response.text


def test_validation_error_carries_trace_id_when_span_active(app: FastAPI) -> None:
    wrapped = SpanApp(app)
    response = TestClient(wrapped).post("/items", json={})
    assert response.json()["trace_id"] == wrapped.trace_ids[0]


def test_validation_errors_map_to_422_with_field_errors(client: TestClient) -> None:
    response = client.post("/items", json={"name": "widget", "qty": "lots"})
    assert response.status_code == 422
    body = _body(response)
    assert body["code"] == "HEPH-VAL-422"
    assert body["status"] == 422
    assert body["title"] == "Validation failed"
    assert body["type"] == TYPE_BASE + "HEPH-VAL-422"
    assert isinstance(body["errors"], list) and len(body["errors"]) == 1
    (field,) = body["errors"]
    assert field["loc"] == ["body", "qty"]
    assert field["msg"]
    assert field["type"]
    # the submitted value must not be echoed back (registry detail_hint)
    assert "lots" not in response.text


def test_validation_errors_for_multiple_fields(client: TestClient) -> None:
    body = _body(client.post("/items", json={}))
    assert {tuple(e["loc"]) for e in body["errors"]} == {("body", "name"), ("body", "qty")}


def test_validation_error_on_malformed_json(client: TestClient) -> None:
    response = client.post("/items", content=b"{nope", headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert _body(response)["code"] == "HEPH-VAL-422"
