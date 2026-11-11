"""Run every conformance vector through the Python API.

Vector files are discovered by globbing ``conformance/**/*.json``. A file
whose ``suite`` has no runner here is a hard failure, never a skip: a new
vector file must not be silently untested.
"""

from __future__ import annotations

import base64
import json
import operator
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from hephkit import _core
from hephkit.errors import HephError
from hephkit.hashing import (
    HashingError,
    canonical_json,
    content_hash,
)
from hephkit.idempotency import fingerprint, fingerprint_document, validate_key
from hephkit.money import Money, MoneyError
from hephkit.signatures import SignatureError, sign, verify

ROOT = Path(__file__).resolve().parents[3] / "conformance"
SCHEMA_DIR = ROOT / "schema"

Case = dict[str, Any]


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


#: The four ordering operators, in the order `_ORDERINGS` records them.
_OPERATORS: tuple[Callable[[Money, Money], bool], ...] = (
    operator.lt,
    operator.le,
    operator.gt,
    operator.ge,
)

#: What each ordering a vector can expect means for those four operators, so
#: one case pins all four: `lt` means `a < b` and `a <= b` hold while `a > b`
#: and `a >= b` do not. No operator can drift from the spec on its own.
_ORDERINGS: dict[str, tuple[bool, bool, bool, bool]] = {
    "lt": (True, True, False, False),
    "eq": (False, True, False, True),
    "gt": (False, False, True, True),
}


def run_compare(case: Case) -> None:
    i = case["input"]
    expect = case["expect"]
    if "error" in expect:
        # Every operator must fail the same way: a correct `<` next to a `>=`
        # that answers a currency mismatch anyway would otherwise pass.
        for op in _OPERATORS:
            with pytest.raises(MoneyError) as exc:
                op(_operand(i, "a"), _operand(i, "b"))
            assert getattr(exc.value, "code") == expect["error"]
        return
    a, b = _operand(i, "a"), _operand(i, "b")
    assert tuple(op(a, b) for op in _OPERATORS) == _ORDERINGS[expect["ordering"]]


def run_allocate(case: Case) -> None:
    i = case["input"]

    def compute() -> list[Money]:
        # `_operand` so `money_text` reaches the core's text entry point, as it
        # already does in the Rust runner. Reading i["money"] only left the text
        # spelling supported by the schema and unreachable from Python, so a
        # vector using it would have failed with a KeyError rather than on the
        # behaviour it pins.
        return _operand(i, "money").allocate(i["ratios"])

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


def run_idempotency_key(case: Case) -> None:
    i = case["input"]

    def compute() -> str | None:
        return validate_key(i["key"], required=i["required"])

    if expect_error(case, HephError, compute):
        return
    result = compute()
    if case["expect"].get("ignored"):
        # 2.1: an endpoint that does not require a key ignores a bad one.
        assert result is None
    else:
        assert result == i["key"]


def run_idempotency_fingerprint(case: Case) -> None:
    i = case["input"]
    body = i["body"].encode("utf-8") if "body" in i else None
    media_type = i.get("media_type")

    def document() -> dict[str, Any]:
        return fingerprint_document(i["method"], i["path"], body, media_type)

    if expect_error(case, HephError, document):
        return
    # The vector carries the canonical string as well as the digest, so check
    # both: a mismatch then names which of 2.2's four steps went wrong instead
    # of only reporting two different hashes.
    assert canonical_json(document()) == case["expect"]["jcs"]
    assert fingerprint(i["method"], i["path"], body, media_type) == case["expect"]["fingerprint"]


RUNNERS: dict[str, Callable[[Case], None]] = {
    "idempotency.key": run_idempotency_key,
    "idempotency.fingerprint": run_idempotency_fingerprint,
    "money.currency": run_currency,
    "money.parse": run_parse,
    "money.format": run_format,
    "money.arith": run_arith,
    "money.compare": run_compare,
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
    assert len(vector_files()) >= 10, vector_files()


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
