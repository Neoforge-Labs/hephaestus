# /// script
# requires-python = ">=3.12"
# dependencies = ["rfc8785==0.1.4", "standardwebhooks==1.1.0"]
# ///
"""Generate the hashing and signature conformance vectors from reference packages.

PROVENANCE RULE (CLAUDE.md rule 2): this script may only take expected values
from independent sources. It imports ``rfc8785`` (JCS), ``standardwebhooks``
(signing and verification) and the standard library (``hashlib``, ``hmac``
through the reference package). It MUST NOT import, call, build or shell out to
any Hephaestus implementation (``hephkit``, ``heph``, the Rust core, the Go
kit), now or in future. Do not re-run it against our code to "fix" a vector:
if an implementation disagrees with a committed vector, the implementation is
wrong until proven otherwise.

Where a value also appears in RFC 8785, in the Standard Webhooks reference
material or in spec/heph-spec.md, it is written out below as an ``oracle`` and
the script aborts (writing nothing) if the reference package disagrees. Error
expectations for conditions the reference packages cannot see (duplicate member
names, malformed JSON text) come from spec section 4.3, not from a package.

Usage (writes conformance/hashing/*.json and conformance/signatures/*.json)::

    uv run tools/gen_signature_vectors.py              # everything
    uv run tools/gen_signature_vectors.py --hashing    # jcs.json and content.json
    uv run tools/gen_signature_vectors.py --signatures # sign.json and verify.json

One case bypasses ``standardwebhooks``: the signature over a payload that is not
valid UTF-8 (``RAW_PAYLOAD``). The package only accepts ``str``, but Standard
Webhooks signs the raw body bytes, so a wrapper that decodes the body to text
would pass every other vector and still be wrong. That signature is derived with
``hmac``, ``hashlib`` and ``base64`` from the standard library (HMAC-SHA256 over
``{msg_id}.{timestamp}.{payload}`` with the base64-decoded secret), and the same
function is cross-checked against the package on a UTF-8 payload before use.

Header convention for ``signatures.verify``: all three header keys are always
present; an absent header is represented by the empty string.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

import rfc8785
import standardwebhooks
from standardwebhooks import webhooks

ROOT = Path(__file__).resolve().parents[1]
SPEC = "0.1.0"
VAL = "HEPH-VAL-422"
WH = "HEPH-WH-401"

SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
RAW_SECRET = SECRET.removeprefix("whsec_")
OTHER_SECRET = "whsec_" + base64.b64encode(b"0123456789abcdef").decode()
MSG_ID = "msg_p5jXN8AQM9LWM0D4loKWxJek"
TS = 1614265330
PAYLOAD = '{"test": 2432232314}'
TOLERANCE = 300


class Disagreement(Exception):
    """A reference package contradicts a value taken from an RFC or the spec."""


# --------------------------------------------------------------------------- JCS


def _no_dups(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate member name {key!r}")
        out[key] = value
    return out


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite literal {name}")


def jcs(text: str) -> str:
    """Canonicalise JSON text with the rfc8785 reference package."""
    value = json.loads(text, object_pairs_hook=_no_dups, parse_constant=_reject_constant)
    return rfc8785.dumps(value).decode("utf-8")


def _expected(text: str) -> dict[str, str]:
    try:
        return {"canonical": jcs(text)}
    except Exception:  # noqa: BLE001 - any rejection is a VAL-422 per spec 4.3
        return {"error": VAL}


RFC_322_INPUT = (
    '{"numbers":[333333333.33333329,1E30,4.50,2e-3,0.000000000000000000000000001],'
    '"string":"\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/",'
    '"literals":[null,true,false]}'
)
RFC_322_OUTPUT = (
    '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
    '"string":"\u20ac$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
)
RFC_323_INPUT = (
    '{"\\u20ac":"Euro Sign","\\r":"Carriage Return","\\ufb33":"Hebrew Letter Dalet With Dagesh",'
    '"1":"One","\\ud83d\\ude00":"Emoji: Grinning Face","\\u0080":"Control",'
    '"\\u00f6":"Latin Small Letter O With Diaeresis"}'
)
RFC_323_OUTPUT = (
    '{"\\r":"Carriage Return","1":"One","\u0080":"Control",'
    '"\u00f6":"Latin Small Letter O With Diaeresis","\u20ac":"Euro Sign",'
    '"\U0001f600":"Emoji: Grinning Face","\ufb33":"Hebrew Letter Dalet With Dagesh"}'
)

# (name, JSON text, oracle canonical string or None, spec_error)
# oracle: independently stated expected output (RFC text); spec_error: the
# expected result is an error taken from spec 4.3 rather than from the package.
JCS_CASES: list[tuple[str, str, str | None, bool]] = [
    ("empty-object", "{}", "{}", False),
    ("empty-array", "[]", "[]", False),
    ("top-level-scalars-null", "null", "null", False),
    ("whitespace-stripped-array-order-kept", ' [ 3 , 1 ,\n 2 , {"b" : 1 , "a" : [ ] } ] ', '[3,1,2,{"a":[],"b":1}]', False),
    ("keys-sorted", '{"b":1,"a":2,"B":3}', '{"B":3,"a":2,"b":1}', False),
    ("rfc8785-3.2.2-sample", RFC_322_INPUT, RFC_322_OUTPUT, False),
    ("rfc8785-3.2.3-utf16-key-sort", RFC_323_INPUT, RFC_323_OUTPUT, False),
    (
        "nested-keys-utf16-code-unit-order-not-code-point",
        '{"outer":{"\\ufb33":1,"\\ud83d\\ude00":2,"\\uffff":3},"a":[{"z":1,"y":2}]}',
        '{"a":[{"y":2,"z":1}],"outer":{"\U0001f600":2,"\ufb33":1,"\uffff":3}}',
        False,
    ),
    (
        "sorted-deeply-nested",
        '{"z":{"y":{"x":1,"a":2},"b":[{"d":1,"c":2}]},"a":null}',
        '{"a":null,"z":{"b":[{"c":2,"d":1}],"y":{"a":2,"x":1}}}',
        False,
    ),
    ("non-ascii-raw-and-escaped-equal", '["\u00e9","\\u00e9","\u20ac","\\u20ac"]', '["\u00e9","\u00e9","\u20ac","\u20ac"]', False),
    ("non-bmp-surrogate-pair-and-raw", '["\\ud83d\\ude00","\U0001f600"]', '["\U0001f600","\U0001f600"]', False),
    ("non-ascii-keys", '{"\u00e9":1,"e":2,"z":3}', '{"e":2,"z":3,"\u00e9":1}', False),
    (
        "string-escapes-short-forms-and-control-chars",
        '["\\u0000\\u0008\\u0009\\u000a\\u000c\\u000d\\u001f\\u007f\\u0022\\u005c\\u002f"]',
        '["\\u0000\\b\\t\\n\\f\\r\\u001f\u007f\\"\\\\/"]',
        False,
    ),
    ("line-separators-not-escaped", '["\\u2028\\u2029"]', '["\u2028\u2029"]', False),
    # Numbers: RFC 8785 Appendix B (IEEE-754 bit pattern -> serialisation).
    ("number-zero-negative-zero-literals", '[0,-0,0.0,-0.0]', "[0,0,0,0]", False),
    ("number-0.1", '{"n":0.1}', '{"n":0.1}', False),
    ("number-1e20-is-float-literal-and-expands", '{"n":1e20}', '{"n":100000000000000000000}', False),
    ("number-1e21-switches-to-exponent", '{"n":1e21}', '{"n":1e+21}', False),
    ("number-1.5e300", '{"n":1.5e300}', '{"n":1.5e+300}', False),
    ("number-fraction-literal-rounds-to-double", '{"n":123456789012345678901234567890.5}', '{"n":1.2345678901234568e+29}', False),
    ("number-integer-literal-max-safe", '{"n":9007199254740991}', '{"n":9007199254740991}', False),
    ("number-integer-literal-negative-max-safe", '{"n":-9007199254740991}', '{"n":-9007199254740991}', False),
    ("number-integer-literal-2-pow-53-rejected", '{"n":9007199254740992}', None, False),
    ("number-integer-literal-2-pow-53-plus-1-rejected", '{"n":9007199254740993}', None, False),
    ("number-integer-literal-negative-beyond-safe-rejected", '{"n":-9007199254740993}', None, False),
    ("number-integer-literal-beyond-u64-rejected", '{"n":184467440737095516160}', None, False),
    ("number-float-literal-overflow-to-infinity-rejected", '{"n":1e400}', None, False),
    ("rfc8785-appendix-b-extremes", '[5e-324,1.7976931348623157e308]', "[5e-324,1.7976931348623157e+308]", False),
    ("rfc8785-appendix-b-2-pow-53-as-float", '[9007199254740992.0,295147905179352830000.0]', "[9007199254740992,295147905179352830000]", False),
    ("rfc8785-appendix-b-1e23-neighbours", '[9.999999999999997e22,1e23,1.0000000000000001e23]', "[9.999999999999997e+22,1e+23,1.0000000000000001e+23]", False),
    ("rfc8785-appendix-b-1e21-neighbours", '[9.999999999999997e20,9.999999999999999e20,1e21]', "[999999999999999700000,999999999999999900000,1e+21]", False),
    ("rfc8785-appendix-b-small", '[0.000001,9.999999999999997e-7,-0.0000033333333333333333]', "[0.000001,9.999999999999997e-7,-0.0000033333333333333333]", False),
    ("rfc8785-appendix-b-333333333", '[333333333.3333332,333333333.33333325,333333333.3333333,333333333.3333334,333333333.33333343]', "[333333333.3333332,333333333.33333325,333333333.3333333,333333333.3333334,333333333.33333343]", False),
    ("rfc8785-appendix-b-1424953923781206.2", '[1424953923781206.2]', "[1424953923781206.2]", False),
    # cyberphone/json-canonicalization testdata (input/weird.json -> output/weird.json etc.)
    (
        "cyberphone-weird",
        '{"\\u20ac":"Euro Sign","\\r":"Carriage Return","\\u000a":"Newline","1":"One","\\u0080":"Control\\u007f","\\ud83d\\ude02":"Smiley","\\u00f6":"Latin Small Letter O With Diaeresis","\\ufb33":"Hebrew Letter Dalet With Dagesh","</script>":"Browser Challenge"}',
        '{"\\n":"Newline","\\r":"Carriage Return","1":"One","</script>":"Browser Challenge","\u0080":"Control\u007f","\u00f6":"Latin Small Letter O With Diaeresis","\u20ac":"Euro Sign","\U0001f602":"Smiley","\ufb33":"Hebrew Letter Dalet With Dagesh"}',
        False,
    ),
    (
        "cyberphone-structures",
        '{"1":{"f":{"f":"hi","F":5},"\\n":56.0},"10":{},"":"empty","a":{},"111":[{"e":"yes","E":"no"}],"A":{}}',
        '{"":"empty","1":{"\\n":56,"f":{"F":5,"f":"hi"}},"10":{},"111":[{"E":"no","e":"yes"}],"A":{},"a":{}}',
        False,
    ),
    ("cyberphone-unicode-not-normalised", '{"Unnormalized Unicode":"A\\u030a"}', '{"Unnormalized Unicode":"A\u030a"}', False),
    # Rejections from spec 4.3 that a package cannot see in text form.
    ("duplicate-member-names-rejected", '{"a":1,"a":2}', None, True),
    ("duplicate-member-names-nested-rejected", '{"x":{"b":1,"b":1}}', None, True),
    ("nan-literal-rejected", '{"n":NaN}', None, True),
    ("infinity-literal-rejected", '{"n":Infinity}', None, True),
    ("negative-infinity-literal-rejected", '{"n":-Infinity}', None, True),
    ("lone-high-surrogate-rejected", '["\\ud800"]', None, True),
    ("lone-low-surrogate-rejected", '["\\udc00"]', None, True),
    ("malformed-json-rejected", '{"a":', None, True),
    ("trailing-garbage-rejected", '{} x', None, True),
]


def build_jcs() -> list[dict[str, Any]]:
    cases = []
    for name, text, oracle, spec_error in JCS_CASES:
        if spec_error:
            expect: dict[str, str] = {"error": VAL}
            got = _expected(text)
            if "error" not in got:
                raise Disagreement(f"{name}: spec 4.3 requires rejection but rfc8785 produced {got}")
        else:
            expect = _expected(text)
            if oracle is None:
                if expect != {"error": VAL}:
                    raise Disagreement(f"{name}: expected rejection, rfc8785 produced {expect}")
            elif expect != {"canonical": oracle}:
                raise Disagreement(f"{name}: oracle {oracle!r} != rfc8785 {expect!r}")
        cases.append({"name": name, "input": {"json": text}, "expect": expect})
    cases.extend(_depth_boundary_cases())
    return cases


# Spec 4.3 nesting limit: a top-level scalar has depth 0, every array or object
# entered adds 1, and a document whose maximum depth exceeds 128 is rejected.
MAX_DEPTH = 128


def _nest(depth: int) -> str:
    """`depth` nested empty-array levels: depth 3 is `[[[]]]`."""
    return "[" * (depth - 1) + "[]" + "]" * (depth - 1)


def _depth_boundary_cases() -> list[dict[str, Any]]:
    deepest = _nest(MAX_DEPTH)
    # Accepted case: the reference package agrees (it has no depth limit of its own).
    if _expected(deepest) != {"canonical": deepest}:
        raise Disagreement("deepest accepted nest does not canonicalise to itself")
    # Rejected case: derived from the spec rule alone; the package would accept it.
    return [
        {"name": "nesting-depth-128-accepted-boundary", "input": {"json": deepest},
         "expect": {"canonical": deepest}},
        {"name": "nesting-depth-129-rejected-boundary", "input": {"json": _nest(MAX_DEPTH + 1)},
         "expect": {"error": VAL}},
    ]


# Content hashes: oracle values independent of this script's hashing code.
SPEC_FINGERPRINT_BODY = '{"method":"POST","path":"/v1/charges","body":{"b":1,"a":2}}'
SPEC_FINGERPRINT = "sha256:9d7a9f8a22e4d35d3efc80eafe7f0026713f6ad9ba4a3abd5c025e92036fd6eb"  # spec 2.2
EMPTY_OBJECT_HASH = "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"  # sha256("{}")
NULL_HASH = "sha256:74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"  # sha256("null")

CONTENT_CASES: list[tuple[str, str, str | None]] = [
    ("empty-object", "{}", EMPTY_OBJECT_HASH),
    ("null", "null", NULL_HASH),
    ("spec-2.2-fingerprint-example", SPEC_FINGERPRINT_BODY, SPEC_FINGERPRINT),
    ("key-order-does-not-change-hash", '{"a":2,"b":1}', None),
    ("whitespace-does-not-change-hash", ' { "b" : 1 , "a" : 2 } ', None),
    ("rfc8785-3.2.2-sample", RFC_322_INPUT, None),
    ("rfc8785-3.2.3-utf16-key-sort", RFC_323_INPUT, None),
    ("non-ascii-string-hashed-as-utf8", '{"name":"Zo\u00eb \u20ac \U0001f600"}', None),
    ("empty-string", '""', None),
    ("number-1e21", '{"n":1e21}', None),
    ("integer-literal-2-pow-53-rejected", '{"n":9007199254740992}', "ERR"),
    ("duplicate-member-names-rejected", '{"a":1,"a":2}', "ERR"),
]


def build_content() -> list[dict[str, Any]]:
    cases = []
    for name, text, oracle in CONTENT_CASES:
        try:
            digest = hashlib.sha256(jcs(text).encode("utf-8")).hexdigest()
            expect: dict[str, str] = {"hash": f"sha256:{digest}"}
        except Exception:  # noqa: BLE001
            expect = {"error": VAL}
        if oracle == "ERR":
            if expect != {"error": VAL}:
                raise Disagreement(f"{name}: expected rejection, got {expect}")
        elif oracle is not None and expect != {"hash": oracle}:
            raise Disagreement(f"{name}: oracle {oracle} != computed {expect}")
        cases.append({"name": name, "input": {"json": text}, "expect": expect})
    # The two key-order/whitespace cases must agree with each other and with {"a":2,"b":1}.
    by = {c["name"]: c["expect"] for c in cases}
    if not by["key-order-does-not-change-hash"] == by["whitespace-does-not-change-hash"]:
        raise Disagreement("key-order and whitespace cases hash differently")
    return cases


# ------------------------------------------------------------------- signatures


def b64(data: str) -> str:
    return base64.b64encode(data.encode("utf-8")).decode("ascii")


def sign(secret: str, msg_id: str, ts: int, payload: str) -> str:
    return webhooks.Webhook(secret).sign(msg_id, datetime.fromtimestamp(ts, timezone.utc), payload)


RAW_PAYLOAD = b"\xff\xfe\x00binary"  # not valid UTF-8


def sign_raw(secret: str, msg_id: str, ts: int, payload: bytes) -> str:
    """Standard Webhooks v1 signature over raw bytes, from stdlib primitives only."""
    key = base64.b64decode(secret.removeprefix("whsec_") + "==")
    mac = hmac.new(key, f"{msg_id}.{ts}.".encode() + payload, hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode("ascii")


def _check_stdlib_matches_package() -> None:
    for secret, ts, text in [(SECRET, TS, PAYLOAD), (OTHER_SECRET, 0, "x"), (SECRET, 4102444800, "\u00eb")]:
        if sign_raw(secret, MSG_ID, ts, text.encode()) != sign(secret, MSG_ID, ts, text):
            raise Disagreement("stdlib HMAC derivation differs from standardwebhooks on a UTF-8 payload")


# Independent oracle: test_sign_function in the Standard Webhooks repository
# (libraries/python/tests/test_webhooks.py) for this secret/id/timestamp/payload.
ORACLE_SIGN = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="

SIGN_INPUTS: list[tuple[str, str, str, int, str]] = [
    ("reference-example", SECRET, MSG_ID, TS, PAYLOAD),
    ("secret-without-whsec-prefix-is-raw-base64", RAW_SECRET, MSG_ID, TS, PAYLOAD),
    ("different-secret-length-16-bytes", OTHER_SECRET, MSG_ID, TS, PAYLOAD),
    ("empty-payload", SECRET, MSG_ID, TS, ""),
    ("non-ascii-payload-signed-as-utf8", SECRET, MSG_ID, TS, '{"name":"Zo\u00eb \u20ac \U0001f600"}'),
    ("payload-with-newlines-signed-raw", SECRET, MSG_ID, TS, '{\n  "a": 1\n}\n'),
    ("different-msg-id", SECRET, "msg_2KWPBgLlAfxdpx2AI54pPJ85f4W", TS, PAYLOAD),
    ("timestamp-zero", SECRET, MSG_ID, 0, PAYLOAD),
    ("timestamp-beyond-2038", SECRET, MSG_ID, 4102444800, PAYLOAD),
    ("payload-containing-dots-and-spaces", SECRET, MSG_ID, TS, f"{MSG_ID}.{TS}.x y"),
]


def build_sign() -> list[dict[str, Any]]:
    cases = []
    for name, secret, msg_id, ts, payload in SIGN_INPUTS:
        sig = sign(secret, msg_id, ts, payload)
        if name == "reference-example" and sig != ORACLE_SIGN:
            raise Disagreement(f"reference example: oracle {ORACLE_SIGN} != package {sig}")
        cases.append(
            {
                "name": name,
                "input": {"secret": secret, "msg_id": msg_id, "timestamp": ts, "payload_b64": b64(payload)},
                "expect": {"signature": sig},
            }
        )
    _check_stdlib_matches_package()
    cases.append(
        {
            "name": "non-utf8-payload-signed-as-raw-bytes",
            "input": {"secret": SECRET, "msg_id": MSG_ID, "timestamp": TS,
                      "payload_b64": base64.b64encode(RAW_PAYLOAD).decode("ascii")},
            "expect": {"signature": sign_raw(SECRET, MSG_ID, TS, RAW_PAYLOAD)},
        }
    )
    by = {c["name"]: c["expect"]["signature"] for c in cases}
    if by["secret-without-whsec-prefix-is-raw-base64"] != by["reference-example"]:
        raise Disagreement("prefixed and raw secrets sign differently")
    return cases


class _FixedClock(datetime):
    fixed: int = 0

    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return datetime.fromtimestamp(cls.fixed, tz)


def package_verify(secret: str, headers: dict[str, str], payload: str, now: int) -> bool:
    """Run the reference verifier with its clock pinned to ``now``.

    Any exception counts as a rejection: the package leaks ValueError/binascii
    errors for malformed signatures, while the spec says every failure is
    HEPH-WH-401 (spec 5.6). ``json_parse=False`` because the package otherwise
    JSON-decodes the body after a good MAC and would reject an empty body, which
    is a signature-valid message under spec 5.
    """
    _FixedClock.fixed = now
    with mock.patch.object(webhooks, "datetime", _FixedClock):
        try:
            webhooks.Webhook(secret).verify(payload, headers, json_parse=False)
        except Exception:  # noqa: BLE001
            return False
    return True


def build_verify() -> list[dict[str, Any]]:
    now = TS + 10
    good = sign(SECRET, MSG_ID, TS, PAYLOAD)
    bad = "v1," + base64.b64encode(b"\x00" * 32).decode()

    def headers(sig: str, *, mid: str = MSG_ID, ts: int | str = TS) -> dict[str, str]:
        return {"webhook-id": mid, "webhook-timestamp": str(ts), "webhook-signature": sig}

    # (name, secret, headers, payload, now, intended_ok)
    rows: list[tuple[str, str, dict[str, str], str, int, bool]] = [
        ("valid", SECRET, headers(good), PAYLOAD, now, True),
        ("payload-tampered", SECRET, headers(good), PAYLOAD.replace("2432232314", "2432232315"), now, False),
        ("timestamp-301-seconds-old", SECRET, headers(good), PAYLOAD, TS + 301, False),
        ("timestamp-301-seconds-in-the-future", SECRET, headers(good), PAYLOAD, TS - 301, False),
        ("timestamp-exactly-300-seconds-old-accepted", SECRET, headers(good), PAYLOAD, TS + TOLERANCE, True),
        ("timestamp-exactly-300-seconds-in-the-future-accepted", SECRET, headers(good), PAYLOAD, TS - TOLERANCE, True),
        ("two-signatures-only-second-matches", SECRET, headers(f"{bad} {good}"), PAYLOAD, now, True),
        ("two-signatures-only-first-matches", SECRET, headers(f"{good} {bad}"), PAYLOAD, now, True),
        ("unknown-version-before-valid-v1-ignored", SECRET, headers(f"v1a,abc {good}"), PAYLOAD, now, True),
        ("only-unknown-version-with-correct-mac-rejected", SECRET, headers("v2," + good.split(",")[1]), PAYLOAD, now, False),
        ("missing-webhook-id-is-empty-string", SECRET, headers(good, mid=""), PAYLOAD, now, False),
        ("missing-webhook-timestamp-is-empty-string", SECRET, {**headers(good), "webhook-timestamp": ""}, PAYLOAD, now, False),
        ("missing-webhook-signature-is-empty-string", SECRET, headers(""), PAYLOAD, now, False),
        ("malformed-signature-no-comma", SECRET, headers(good.replace(",", "")), PAYLOAD, now, False),
        ("malformed-signature-bad-base64", SECRET, headers("v1,!!!"), PAYLOAD, now, False),
        ("wrong-secret", OTHER_SECRET, headers(good), PAYLOAD, now, False),
        ("secret-without-whsec-prefix-accepted-as-raw-base64", RAW_SECRET, headers(good), PAYLOAD, now, True),
        ("timestamp-header-differs-from-signed-timestamp", SECRET, headers(good, ts=TS + 1), PAYLOAD, now, False),
        ("msg-id-header-differs-from-signed-id", SECRET, headers(good, mid="msg_other"), PAYLOAD, now, False),
        ("timestamp-header-not-a-number", SECRET, headers(good, ts="abc"), PAYLOAD, now, False),
        ("signature-for-empty-payload", SECRET, headers(sign(SECRET, MSG_ID, TS, "")), "", now, True),
        (
            "signature-for-non-ascii-payload",
            SECRET,
            headers(sign(SECRET, MSG_ID, TS, '{"name":"Zo\u00eb \u20ac"}')),
            '{"name":"Zo\u00eb \u20ac"}',
            now,
            True,
        ),
    ]
    cases = []
    for name, secret, hdrs, payload, at, intended in rows:
        got = package_verify(secret, hdrs, payload, at)
        if got != intended:
            raise Disagreement(f"{name}: intended ok={intended}, standardwebhooks says ok={got}")
        cases.append(
            {
                "name": name,
                "input": {"secret": secret, "headers": hdrs, "payload_b64": b64(payload), "now": at},
                "expect": {"ok": True} if intended else {"error": WH},
            }
        )
    _check_stdlib_matches_package()
    raw_good = sign_raw(SECRET, MSG_ID, TS, RAW_PAYLOAD)
    lossy = sign_raw(SECRET, MSG_ID, TS, RAW_PAYLOAD.decode("utf-8", errors="replace").encode("utf-8"))
    if raw_good == lossy:
        raise Disagreement("lossy-decode signature equals raw signature")
    raw_b64 = base64.b64encode(RAW_PAYLOAD).decode("ascii")
    for name, sig, ok in [
        ("non-utf8-payload-signed-as-raw-bytes", raw_good, True),
        ("non-utf8-payload-signature-over-lossy-decoded-text-rejected", lossy, False),
    ]:
        cases.append(
            {
                "name": name,
                "input": {"secret": SECRET, "headers": headers(sig), "payload_b64": raw_b64, "now": now},
                "expect": {"ok": True} if ok else {"error": WH},
            }
        )
    return cases


# --------------------------------------------------------------------- writing


def _write(path: Path, suite: str, description: str, source: str, cases: list[dict[str, Any]]) -> None:
    names = [c["name"] for c in cases]
    assert len(set(names)) == len(names), f"duplicate case names in {suite}"
    doc = {"suite": suite, "spec": SPEC, "description": description, "source": source, "cases": cases}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({len(cases)} cases)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--hashing", action="store_true", help="only hashing vectors")
    parser.add_argument("--signatures", action="store_true", help="only signature vectors")
    args = parser.parse_args()
    both = not (args.hashing or args.signatures)
    versions = f"rfc8785 0.1.4, standardwebhooks {getattr(standardwebhooks, '__version__', '1.1.0')}"
    out: list[tuple[Path, str, str, str, list[dict[str, Any]]]] = []
    try:
        if args.hashing or both:
            out.append((ROOT / "conformance/hashing/jcs.json", "hashing.jcs",
                        "Canonical JSON (spec 4). Input is JSON text; expect is the RFC 8785 string, or HEPH-VAL-422 (spec 4.3).",
                        f"Generated by tools/gen_signature_vectors.py --hashing. RFC 8785 sections 3.2.2, 3.2.3 and Appendix B; cyberphone/json-canonicalization testdata/input and testdata/output weird.json, structures.json and unicode.json (https://github.com/cyberphone/json-canonicalization, master at commit 32a48195b9b20fe67b1795e39e4509f14d860b45, read 2026-11-05 through a text-extracting fetch, so control characters in its output files were reconstructed from the escaped input); expected strings produced by {versions}; rejections of duplicate names, NaN/Infinity, lone surrogates and malformed text hand-derived from spec 4.3; the two nesting-depth boundary cases are built from the spec 4.3 limit of 128 (a top-level scalar is depth 0, each array or object entered adds 1): depth 128 is accepted and its output equals its input, depth 129 is rejected by the spec rule alone (rfc8785 has no depth limit and would accept it).",
                        build_jcs()))
            out.append((ROOT / "conformance/hashing/content.json", "hashing.content",
                        "Content hash (spec 4.2): sha256 over the UTF-8 bytes of the RFC 8785 output.",
                        f"hashlib.sha256 over rfc8785 output ({versions}); {{}}, null and the spec 2.2 fingerprint example cross-checked against independently stated digests.",
                        build_content()))
        if args.signatures or both:
            out.append((ROOT / "conformance/signatures/sign.json", "signatures.sign",
                        "Standard Webhooks v1 signature (spec 5.2). `timestamp` is integer seconds; `payload_b64` is the base64 of the raw body bytes.",
                        f"standardwebhooks.Webhook.sign ({versions}), except the non-UTF-8 case which uses stdlib hmac/hashlib/base64 (cross-checked against the package on UTF-8 payloads); reference example cross-checked against test_sign_function in https://github.com/standard-webhooks/standard-webhooks/blob/main/libraries/python/tests/test_webhooks.py (main at commit ab6844147ce9cdb0d2dbf2e60d1ea85001fd2554, read 2026-11-05); the non-UTF-8 case is rebuilt from spec 5.2 with stdlib only.",
                        build_sign()))
            out.append((ROOT / "conformance/signatures/verify.json", "signatures.verify",
                        "Verification (spec 5). `now` is the verifier clock in integer seconds. All three header keys are always present; an absent header is the empty string. Tolerance 300 s, inclusive.",
                        f"standardwebhooks.Webhook.verify with its clock pinned to `now` ({versions}); any exception counts as rejection (spec 5.6); the two non-UTF-8 cases are derived with stdlib hmac (the package only takes str). Every case's intended outcome is also stated in this script and the run aborts if the package disagrees.",
                        build_verify()))
    except Disagreement as exc:
        print(f"REFERENCE DISAGREEMENT, nothing written: {exc}", file=sys.stderr)
        return 2
    for item in out:
        _write(*item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
