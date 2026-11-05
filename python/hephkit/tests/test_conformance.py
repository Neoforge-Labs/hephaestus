"""Run every conformance vector through the Python API.

Vector files are discovered by globbing ``conformance/**/*.json``. A file
whose ``suite`` has no runner here is a hard failure, never a skip: a new
vector file must not be silently untested.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from hephkit import _core
from hephkit.hashing import (
    HashingError,
    canonical_json,
    content_hash,
)
from hephkit.money import Money, MoneyError
from hephkit.signatures import SignatureError, sign, verify

ROOT = Path(__file__).resolve().parents[3] / "conformance"
SCHEMA_DIR = ROOT / "schema"

Case = dict[str, Any]


def _error_class(code: str, kind: type[Exception]) -> type[Exception]:
    return kind


def expect_error(case: Case, kind: type[Exception], thunk: Callable[[], object]) -> bool:
    """If the case expects an error, run `thunk`, check class and code, return True."""
    expect = case["expect"]
    if "error" not in expect:
        return False
    with pytest.raises(kind) as exc:
        thunk()
    assert getattr(exc.value, "code") == expect["error"]
    return True


def money_from_wire_case(w: Any) -> Money:
    return Money.from_wire(w)


def run_currency(case: Case) -> None:
    code = case["input"]["code"]
    if expect_error(case, MoneyError, lambda: Money(1, code)):
        return
    exponent = case["expect"]["exponent"]
    d = Money(1, code).to_decimal()
    assert -d.as_tuple().exponent == exponent  # type: ignore[operator]


def run_parse(case: Case) -> None:
    i = case["input"]
    thunk = lambda: Money.parse(i["amount"], i["currency"], i["rounding"])  # noqa: E731
    if expect_error(case, MoneyError, thunk):
        return
    m = thunk()
    assert m.minor == int(case["expect"]["minor"])
    assert m.currency == i["currency"]


def run_format(case: Case) -> None:
    i = case["input"]
    thunk = lambda: Money(int(i["minor"]), i["currency"])  # noqa: E731
    if expect_error(case, MoneyError, thunk):
        return
    m = thunk()
    amount = case["expect"]["amount"]
    assert str(m.to_decimal()) == amount
    assert m.to_decimal() == Decimal(amount)
    assert str(m) == f"{i['currency']} {amount}"
    # Round trip through the strict parser.
    assert Money.parse(amount, i["currency"]) == m


def _operand(i: Case, key: str) -> Money:
    """`a_text`/`b_text` carry exact JSON bytes that a Python dict cannot (duplicate
    member names), so they go straight to the core's text entry point."""
    if f"{key}_text" in i:
        minor, cur = _core.money_from_wire(i[f"{key}_text"])
        return Money(minor, cur)
    return Money.from_wire(i[key])


def run_arith(case: Case) -> None:
    i = case["input"]

    def compute() -> Money:
        a = _operand(i, "a")
        if i["op"] == "neg":
            return -a
        b = _operand(i, "b")
        if i["op"] == "add":
            return a + b
        if i["op"] == "sub":
            return a - b
        raise AssertionError(f"unknown op {i['op']!r}")

    if expect_error(case, MoneyError, compute):
        return
    assert compute().to_wire() == case["expect"]["result"]


def run_allocate(case: Case) -> None:
    i = case["input"]

    def compute() -> list[Money]:
        return Money.from_wire(i["money"]).allocate(i["ratios"])

    if expect_error(case, MoneyError, compute):
        return
    assert [p.to_wire() for p in compute()] == case["expect"]["parts"]


def _loads_without_duplicates(text: str) -> Any:
    """Parse `text` with Python's loader, or raise ValueError if it has duplicate
    member names (a Python object cannot carry them)."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        d = dict(items)
        if len(d) != len(items):
            raise ValueError("duplicate member name")
        return d

    return json.loads(text, object_pairs_hook=pairs)


def run_jcs(case: Case) -> None:
    text = case["input"]["json"]
    # Text entry point: exact bytes, including duplicate names and bad syntax.
    if not expect_error(case, HashingError, lambda: _core.canonical_json(text)):
        assert _core.canonical_json(text) == case["expect"]["canonical"]
    # Object entry point, wherever Python's loader can carry the document.
    try:
        obj = _loads_without_duplicates(text)
    except ValueError:
        return
    if not expect_error(case, HashingError, lambda: canonical_json(obj)):
        assert canonical_json(obj) == case["expect"]["canonical"]


def run_content(case: Case) -> None:
    text = case["input"]["json"]
    if not expect_error(case, HashingError, lambda: _core.content_hash_json(text)):
        assert _core.content_hash_json(text) == case["expect"]["hash"]
    try:
        obj = _loads_without_duplicates(text)
    except ValueError:
        return
    if not expect_error(case, HashingError, lambda: content_hash(obj)):
        assert content_hash(obj) == case["expect"]["hash"]


def run_sign(case: Case) -> None:
    i = case["input"]
    payload = base64.b64decode(i["payload_b64"], validate=True)

    def compute() -> str:
        return sign(i["secret"], i["msg_id"], i["timestamp"], payload)

    if expect_error(case, SignatureError, compute):
        return
    assert compute() == case["expect"]["signature"]


def run_verify(case: Case) -> None:
    i = case["input"]
    payload = base64.b64decode(i["payload_b64"], validate=True)

    def compute() -> None:
        return verify(i["secret"], i["headers"], payload, now=i["now"])

    if expect_error(case, SignatureError, compute):
        return
    assert case["expect"] == {"ok": True}
    assert compute() is None


RUNNERS: dict[str, Callable[[Case], None]] = {
    "money.currency": run_currency,
    "money.parse": run_parse,
    "money.format": run_format,
    "money.arith": run_arith,
    "money.allocate": run_allocate,
    "hashing.jcs": run_jcs,
    "hashing.content": run_content,
    "signatures.sign": run_sign,
    "signatures.verify": run_verify,
}


def vector_files() -> list[Path]:
    return sorted(
        p for p in ROOT.rglob("*.json") if SCHEMA_DIR not in p.parents
    )


def collect() -> list[Any]:
    params = []
    for path in vector_files():
        doc = json.loads(path.read_text(encoding="utf-8"))
        suite = doc["suite"]
        for case in doc["cases"]:
            params.append(
                pytest.param(suite, case, id=f"{suite}::{case['name']}")
            )
    return params


def test_vector_files_are_found() -> None:
    assert len(vector_files()) >= 9, vector_files()


def test_every_vector_file_has_a_runner() -> None:
    unknown = {}
    for path in vector_files():
        suite = json.loads(path.read_text(encoding="utf-8"))["suite"]
        if suite not in RUNNERS:
            unknown[str(path.relative_to(ROOT))] = suite
    assert not unknown, f"vector files with no Python runner: {unknown}"


def test_every_runner_has_a_vector_file() -> None:
    present = {
        json.loads(p.read_text(encoding="utf-8"))["suite"] for p in vector_files()
    }
    assert set(RUNNERS) <= present, set(RUNNERS) - present


@pytest.mark.parametrize(("suite", "case"), collect())
def test_vector(suite: str, case: Case) -> None:
    runner = RUNNERS.get(suite)
    if runner is None:
        pytest.fail(f"no runner for suite {suite!r}")
    runner(case)
