"""The five-minute example: prices and splits, with traces and real errors.

This is the whole app. What it demonstrates is how little there is of it:
``setup_observability`` and ``install_error_handlers`` are the only wiring, and
neither handler contains a try/except. A bad amount raises ``MoneyError`` and
reaches the client as the problem+json that ``spec/errors.yaml`` defines,
because the handlers hephkit installed know how to render it.

Run it with ``fastapi dev app.py`` after ``heph dev up``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Query
from hephkit.conventions import MONEY_CURRENCY
from hephkit.money import Money
from hephkit.settings import HephSettings
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SpanExporter

from hephkit.errors.fastapi import install_error_handlers
from hephkit.observability import Observability, setup_observability


def create_app(
    settings: HephSettings | None = None,
    *,
    span_exporter: SpanExporter | None = None,
) -> tuple[FastAPI, Observability]:
    """Build the app and its observability. Tests pass an in-memory exporter."""
    settings = settings or HephSettings(service_name="hello")
    app = FastAPI(title="hello", version="0.0.0")
    observability = setup_observability(settings, app, span_exporter=span_exporter)
    install_error_handlers(app)

    @app.get("/price")
    def price(
        amount: Annotated[str, Query(description="Decimal amount, e.g. 10.20")],
        currency: Annotated[str, Query(description="ISO 4217 code, e.g. KES")],
    ) -> dict[str, dict[str, str]]:
        # Strict by default: `Money.parse` refuses grouping separators and
        # excess precision rather than guessing, and the raise becomes a
        # HEPH-MONEY-422 problem+json on the way out.
        money = Money.parse(amount, currency)
        # The parsed currency, not the raw query value, so a span never carries
        # something the kit refused.
        trace.get_current_span().set_attribute(MONEY_CURRENCY, money.currency)
        return {"price": money.to_wire()}

    @app.get("/split")
    def split(
        amount: Annotated[str, Query(description="Decimal amount to divide")],
        currency: Annotated[str, Query(description="ISO 4217 code")],
        ways: Annotated[int, Query(ge=1, le=1000, description="How many parts")],
    ) -> dict[str, list[dict[str, str]]]:
        money = Money.parse(amount, currency)
        trace.get_current_span().set_attribute(MONEY_CURRENCY, money.currency)
        # Equal ratios: allocate distributes the remainder by largest remainder,
        # ties to the lower index, so the parts always sum back to the total.
        parts = money.allocate([1] * ways)
        return {"parts": [p.to_wire() for p in parts]}

    return app, observability


app, _observability = create_app()
