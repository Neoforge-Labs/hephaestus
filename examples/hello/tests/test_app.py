"""The five-minute example, asserted end to end.

These are the four promises the tutorial makes: money crosses the wire in minor
units, a bad amount comes back as a problem+json the error registry defines, a
split adds up, and a request leaves a trace carrying the currency. Each is
checked through the real app, not through hephkit directly -- the point is that
wiring hephkit into a FastAPI service takes the handful of lines in app.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app import create_app


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def client(exporter: InMemorySpanExporter):
    app, observability = create_app(span_exporter=exporter)
    with TestClient(app) as c:
        yield c
    observability.shutdown()


def test_price_returns_minor_units(client: TestClient) -> None:
    r = client.get("/price", params={"amount": "10.2", "currency": "KES"})
    assert r.status_code == 200
    # KES has two minor digits, so 10.2 is 1020 cents -- and the wire carries a
    # string, never a float.
    assert r.json() == {"price": {"amount": "1020", "currency": "KES"}}


def test_price_rejects_a_grouped_amount_as_problem_json(client: TestClient) -> None:
    r = client.get("/price", params={"amount": "1,000", "currency": "KES"})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "HEPH-MONEY-422"
    # The type URL is a MUST in heph-spec 1.4 and resolves to a real page.
    assert body["type"] == "https://hephkit.dev/errors/HEPH-MONEY-422"
    assert body["status"] == 422


def test_split_allocates_the_remainder(client: TestClient) -> None:
    r = client.get("/split", params={"amount": "1.00", "currency": "KES", "ways": 3})
    assert r.status_code == 200
    # Largest remainder, ties to the lower index: the extra cent goes first.
    assert [p["amount"] for p in r.json()["parts"]] == ["34", "33", "33"]
    assert {p["currency"] for p in r.json()["parts"]} == {"KES"}


def test_a_priced_request_emits_a_span_carrying_the_currency(
    client: TestClient, exporter: InMemorySpanExporter
) -> None:
    client.get("/price", params={"amount": "10.2", "currency": "KES"})
    currencies = [
        span.attributes.get("money.currency")
        for span in exporter.get_finished_spans()
        if span.attributes and "money.currency" in span.attributes
    ]
    assert "KES" in currencies, "no span carried money.currency; check setup_observability wiring"
