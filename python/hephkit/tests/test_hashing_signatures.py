"""Wrapper-level behaviour for hephkit.hashing and hephkit.signatures."""

import re

import pytest

from hephkit.hashing import (
    HashingError,
    canonical_json,
    content_hash,
    content_hash_bytes,
    new_uuid7,
)
from hephkit.signatures import SignatureError, sign, verify

SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"


def test_canonical_json_objects() -> None:
    assert canonical_json({"b": 1, "a": [True, None, "é", 1.5]}) == (
        '{"a":[true,null,"é",1.5],"b":1}'
    )
    assert content_hash({"a": 2, "b": 1}) == content_hash({"b": 1, "a": 2})


def test_nan_and_infinity_are_rejected_by_the_core() -> None:
    for bad in (float("nan"), float("inf"), {"x": float("-inf")}):
        with pytest.raises(HashingError) as exc:
            canonical_json(bad)
        assert exc.value.code == "HEPH-VAL-422"


def test_lone_surrogate_and_duplicate_keys_are_rejected() -> None:
    with pytest.raises(HashingError) as exc:
        canonical_json("\ud800")
    assert exc.value.code == "HEPH-VAL-422"
    with pytest.raises(HashingError):
        canonical_json({1: "a", "1": "b"})  # both coerce to member name "1"


def test_unserialisable_object_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        canonical_json({"x": object()})


def test_pathological_nesting_is_an_exception_not_an_abort() -> None:
    deep: object = []
    for _ in range(100_000):
        deep = [deep]
    with pytest.raises((RecursionError, HashingError)):
        canonical_json(deep)


def test_content_hash_bytes_and_type() -> None:
    assert content_hash_bytes(b"") == (
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    with pytest.raises(TypeError):
        content_hash_bytes("text")  # type: ignore[arg-type]


def test_uuid7_shape_and_order() -> None:
    ids = [new_uuid7() for _ in range(50)]
    assert all(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", i) for i in ids)
    assert ids == sorted(ids)


def test_sign_verify_roundtrip_and_defaults() -> None:
    sig = sign(SECRET, "msg_1", 1_000, b"{}")
    headers = {
        "webhook-id": "msg_1",
        "webhook-timestamp": "1000",
        "webhook-signature": sig,
    }
    assert verify(SECRET, headers, b"{}", now=1_000) is None
    assert verify(SECRET, headers, b"{}", now=1_300) is None
    for kwargs in ({"now": 1_301}, {"now": 999_999, "tolerance": 10}):
        with pytest.raises(SignatureError) as exc:
            verify(SECRET, headers, b"{}", **kwargs)  # type: ignore[arg-type]
        assert exc.value.code == "HEPH-WH-401"


def test_verify_wall_clock_default() -> None:
    import time

    ts = int(time.time())
    sig = sign(SECRET, "m", ts, b"x")
    headers = {"webhook-id": "m", "webhook-timestamp": str(ts), "webhook-signature": sig}
    verify(SECRET, headers, b"x")
    stale = {**headers, "webhook-timestamp": str(ts - 10_000)}
    with pytest.raises(SignatureError):
        verify(SECRET, stale, b"x")


def test_verify_missing_headers_fail_closed() -> None:
    with pytest.raises(SignatureError) as exc:
        verify(SECRET, {}, b"x", now=1)
    assert exc.value.code == "HEPH-WH-401"


def test_negative_and_extreme_tolerance_do_not_abort() -> None:
    sig = sign(SECRET, "m", 5, b"x")
    headers = {"webhook-id": "m", "webhook-timestamp": "5", "webhook-signature": sig}
    with pytest.raises(SignatureError):
        verify(SECRET, headers, b"x", now=5, tolerance=-1)
    verify(SECRET, headers, b"x", now=5, tolerance=2**63 - 1)
    with pytest.raises(OverflowError, match="tolerance outside the signed 64-bit"):
        verify(SECRET, headers, b"x", now=5, tolerance=2**63)
    with pytest.raises(OverflowError, match="now outside"):
        verify(SECRET, headers, b"x", now=2**63)
    with pytest.raises(OverflowError, match="timestamp outside"):
        sign(SECRET, "m", 2**63, b"")


def test_sign_unusable_secret_is_signature_error_with_val_code() -> None:
    for secret in ("", "whsec_", "!!!not base64"):
        with pytest.raises(SignatureError) as exc:
            sign(secret, "m", 1, b"x")
        assert exc.value.code == "HEPH-VAL-422"
        assert not isinstance(exc.value, HashingError)


@pytest.mark.slow
def test_non_utf8_and_huge_payloads() -> None:
    sig = sign(SECRET, "m", 1, b"\xff\xfe\x00")
    assert sig.startswith("v1,")
    big = b"a" * (64 * 1024 * 1024)
    assert sign(SECRET, "m", 1, big).startswith("v1,")
    with pytest.raises(TypeError):
        sign(SECRET, "m", 1, "text")  # type: ignore[arg-type]
    with pytest.raises(UnicodeEncodeError):
        sign(SECRET, "m\ud800", 1, b"")  # lone surrogate cannot be UTF-8


@pytest.mark.slow
def test_huge_string_inputs() -> None:
    from hephkit.money import Money, MoneyError

    with pytest.raises(MoneyError):
        Money.parse("1" * 10_000_000, "KES")
    # Ten million trailing zeros preserve the value, so this is 1.00 (ADR 0016),
    # and one non-zero digit ten million places out still has to be found.
    assert Money.parse("1." + "0" * 10_000_000, "KES").minor == 100
    with pytest.raises(MoneyError):
        Money.parse("1." + "0" * 10_000_000 + "1", "KES")
    assert Money.parse("0." + "0" * 10_000_000, "KES", "down").minor == 0
    assert len(canonical_json("x" * 10_000_000)) == 10_000_002


def test_verify_header_names_are_case_insensitive() -> None:
    sig = sign(SECRET, "m", 7, b"x")
    mixed = {"Webhook-Id": "m", "WEBHOOK-TIMESTAMP": "7", "webhook-signature": sig}
    assert verify(SECRET, mixed, b"x", now=7) is None


def test_absent_header_is_distinguishable_from_a_lookup_miss() -> None:
    sig = sign(SECRET, "m", 7, b"x")
    missing = {"Webhook-Id": "m", "WEBHOOK-TIMESTAMP": "7"}
    with pytest.raises(SignatureError) as exc:
        verify(SECRET, missing, b"x", now=7)
    assert exc.value.code == "HEPH-WH-401"
    assert sig  # the same message verifies once the header is present


def test_hashing_error_exported_with_code() -> None:
    from hephkit import hashing

    assert "HashingError" in hashing.__all__
    with pytest.raises(hashing.HashingError) as exc:
        hashing.canonical_json(float("nan"))
    assert exc.value.code == "HEPH-VAL-422"


def _signed(msg_id: str = "m") -> dict[str, str]:
    sig = sign(SECRET, msg_id, 7, b"x")
    return {"webhook-timestamp": "7", "webhook-signature": sig}


def test_case_colliding_headers_with_different_values_fail_closed_both_orders() -> None:
    base = _signed("m")
    ok = {**base, "Webhook-Id": "m"}
    # Same spelling pair, both insertion orders: always rejected.
    first = {**base, "webhook-id": "a", "Webhook-Id": "m"}
    second = {**base, "Webhook-Id": "m", "webhook-id": "a"}
    assert verify(SECRET, ok, b"x", now=7) is None
    for headers in (first, second):
        with pytest.raises(SignatureError) as exc:
            verify(SECRET, headers, b"x", now=7)
        assert exc.value.code == "HEPH-WH-401"


def test_case_colliding_headers_with_identical_values_pass() -> None:
    headers = {**_signed("m"), "webhook-id": "m", "Webhook-Id": "m"}
    assert verify(SECRET, headers, b"x", now=7) is None


def test_non_str_header_keys_are_ignored_not_attribute_errors() -> None:
    headers: dict[object, str] = {**_signed("m"), "webhook-id": "m", 1: "a", b"x": "b"}
    assert verify(SECRET, headers, b"x", now=7) is None  # type: ignore[arg-type]
    with pytest.raises(SignatureError) as exc:
        verify(SECRET, {1: "a"}, b"x", now=7)  # type: ignore[dict-item]
    assert exc.value.code == "HEPH-WH-401"
