"""hephkit.errors: HephError, generated codes and the FastAPI problem+json layer."""

import asyncio
import json
import pathlib
import re
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import httpx
from opentelemetry.sdk.trace import TracerProvider
from pydantic import BaseModel

from hephkit import errors
from hephkit.errors import HephError, _codes
from hephkit.errors.fastapi import install_error_handlers, problem_response
from hephkit.hashing import HashingError, canonical_json
from hephkit.money import Money, MoneyError
from hephkit.signatures import SignatureError, verify

TYPE_BASE = "https://hephkit.dev/errors/"
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

    @app.get("/currency-mismatch")
    def currency_mismatch() -> None:
        Money.parse("1", "USD") + Money.parse("1", "EUR")

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

    def __init__(self, app: Any, *, raise_app_exceptions: bool = False) -> None:
        self._app = app
        self._raise = raise_app_exceptions

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def go() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app, raise_app_exceptions=self._raise)
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


def test_heph_error_unhashable_code_raises_value_error() -> None:
    with pytest.raises(ValueError):
        HephError(["HEPH-GEN-500"])  # type: ignore[arg-type]


def test_heph_error_rejects_reserved_extension_names() -> None:
    # `code` and `detail` are parameters, so they can never be extensions.
    for name in ("type", "title", "status", "trace_id"):
        with pytest.raises(ValueError, match=name):
            HephError("HEPH-GEN-500", **{name: "x"})


def test_problem_response_cannot_be_made_to_fabricate_a_trace_id() -> None:
    """A caller-supplied `trace_id` used to survive into the body whenever no
    span was active, naming a trace that never existed. The other five
    reserved members were already safe (they are assigned after the merge);
    all six are now filtered, so the rule matches `HephError`'s."""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/x")
    def x() -> JSONResponse:
        import warnings

        # The drop now warns, so a caller is not left wondering where its
        # member went; the suite runs under -W error, hence the catch.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return problem_response(
                _codes.NF_404,
                extensions={"trace_id": "deadbeef", "status": 200, "hint": "kept"},
            )

    body = _body(TestClient(app).get("/x"))
    assert "trace_id" not in body
    assert body["status"] == 404
    assert body["code"] == "HEPH-NF-404"
    assert body["hint"] == "kept"


def test_dropping_a_reserved_extension_warns() -> None:
    """Dropping is right (raising would turn a correct 404 into a GEN-500) but
    a silent drop leaves a caller wondering where its member went."""
    with pytest.warns(RuntimeWarning, match="trace_id.*reserved and were dropped"):
        problem_response("HEPH-NF-404", extensions={"trace_id": "x"})


def test_an_extension_that_clashes_with_nothing_does_not_warn() -> None:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        problem_response("HEPH-NF-404", extensions={"hint": "fine"})
        problem_response("HEPH-NF-404")


def test_production_code_uses_the_generated_constants_not_literals() -> None:
    """Codes live only in `spec/errors.yaml`, which is why `_codes.py` is
    generated. Three literals in `errors/fastapi.py` re-typed codes while the
    generated constants went unimported, so the generator enforced nothing."""
    from hephkit.errors import fastapi as web

    source = pathlib.Path(web.__file__).read_text(encoding="utf-8")
    offenders = sorted(set(re.findall(r'"(HEPH-[A-Z]{2,6}-[0-9]{3})"', source)))
    assert offenders == [], f"{web.__name__} re-types codes as literals: {offenders}"
    assert web._GENERIC is _codes.GEN_500


def test_generated_constants_match_registry() -> None:
    assert _codes.IDEMP_409 == "HEPH-IDEMP-409"
    assert _codes.GEN_500 == "HEPH-GEN-500"
    assert _codes.DETAIL_HINTS["HEPH-IDEMP-409"].startswith("A request with this key")
    assert set(_codes.DETAIL_HINTS) == set(_codes.REGISTRY)
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
        "detail": _codes.DETAIL_HINTS["HEPH-IDEMP-409"],
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


def test_default_detail_is_the_registry_hint_and_differs_from_title(client: TestClient) -> None:
    body = _body(client.get("/heph"))
    assert body["detail"] == "A request with this key is still being processed. Retry after it completes."
    assert body["detail"] != body["title"]


def test_detail_falls_back_to_title_when_hint_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    from hephkit.errors import fastapi as web

    monkeypatch.setattr(web, "DETAIL_HINTS", {})
    assert json.loads(web.problem_response("HEPH-IDEMP-409").body)["detail"] == "Original request still in flight"


def test_trace_id_omitted_when_opentelemetry_is_absent(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    from hephkit.errors import fastapi as web

    monkeypatch.setattr(web, "trace", None)  # what a failed import leaves behind
    body = _body(TestClient(SpanApp(app)).get("/heph"))
    assert "trace_id" not in body
    assert body["code"] == "HEPH-IDEMP-409"


def test_unknown_route_is_problem_json_nf_404(client: TestClient) -> None:
    response = client.get("/no/such/route")
    assert response.status_code == 404
    body = _body(response)
    assert body["code"] == "HEPH-NF-404"
    assert body["type"] == TYPE_BASE + "HEPH-NF-404"
    assert body["detail"] == _codes.DETAIL_HINTS["HEPH-NF-404"]


def test_other_http_exceptions_pass_through_unchanged(client: TestClient) -> None:
    response = client.post("/heph")  # route exists for GET only -> 405
    assert response.status_code == 405
    assert response.headers["content-type"] == "application/json"
    assert "code" not in response.json()


def test_money_error_maps_to_422(client: TestClient) -> None:
    response = client.get("/money")
    assert response.status_code == 422
    body = _body(response)
    assert body["code"] == "HEPH-MONEY-422"
    assert body["status"] == 422
    assert body["title"] == "Invalid money amount"
    assert body["type"] == TYPE_BASE + "HEPH-MONEY-422"
    assert isinstance(MoneyError("x"), ValueError)


def test_currency_mismatch_maps_to_409(client: TestClient) -> None:
    response = client.get("/currency-mismatch")
    assert response.status_code == 409
    assert _body(response) == {
        "type": TYPE_BASE + "HEPH-MONEY-409",
        "title": "Currency mismatch",
        "status": 409,
        "detail": _codes.DETAIL_HINTS["HEPH-MONEY-409"],
        "code": "HEPH-MONEY-409",
    }


@pytest.mark.parametrize("path", ["/heph", "/money", "/signature", "/hashing", "/currency-mismatch"])
def test_our_coded_exceptions_are_not_reraised(app: FastAPI, path: str) -> None:
    """Expected client errors must not propagate to the server as crashes."""
    response = TestClient(app, raise_app_exceptions=True).get(path)
    assert response.headers["content-type"] == PROBLEM


def test_unknown_exceptions_still_propagate_after_the_500_is_built(app: FastAPI) -> None:
    with pytest.raises(RuntimeError):
        TestClient(app, raise_app_exceptions=True).get("/boom")


def _deep(depth: int = 100_000) -> Any:
    value: Any = []
    for _ in range(depth):
        value = [value]
    return value


@pytest.mark.parametrize("bad", [object(), _deep()], ids=["object", "deeply-nested"])
def test_unserialisable_extension_falls_back_to_a_500_problem(
    app: FastAPI, bad: Any
) -> None:
    @app.get("/bad-extension")
    def bad_extension() -> None:
        raise HephError("HEPH-NF-404", leaky=bad)

    response = TestClient(app).get("/bad-extension")
    assert response.status_code == 500
    body = _body(response)  # also asserts content-type application/problem+json
    assert body["code"] == "HEPH-GEN-500"
    assert body["detail"] == _codes.DETAIL_HINTS["HEPH-GEN-500"]
    assert "leaky" not in body
    assert "leaky" not in response.text


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
        "detail": _codes.DETAIL_HINTS["HEPH-GEN-500"],
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


@pytest.mark.parametrize("bad", [object(), _deep()], ids=["object", "deeply-nested"])
def test_problem_response_itself_never_raises_on_bad_extensions(bad: Any) -> None:
    from hephkit.errors.fastapi import problem_response

    response = problem_response("HEPH-NF-404", extensions={"leaky": bad})
    assert response.status_code == 500
    assert response.media_type == PROBLEM
    assert b"leaky" not in response.body
