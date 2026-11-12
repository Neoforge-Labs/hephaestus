# /// script
# requires-python = ">=3.12"
# dependencies = ["rfc8785==0.1.4"]
# ///
"""Generate the idempotency conformance vectors (heph-spec section 2).

PROVENANCE RULE (CLAUDE.md rule 2): expected values come only from independent
sources. This script uses ``rfc8785`` (the JCS reference package) and the
standard library ``hashlib``. It MUST NOT import, call, build or shell out to
any Hephaestus implementation (``hephkit``, ``heph``, the Rust core, the Go
kit), now or in future. If an implementation disagrees with a committed vector,
the implementation is wrong until proven otherwise -- do not re-run this against
our code to "fix" a vector.

Every fingerprint case carries a hand-written ``oracle``: the JCS string as
RFC 8785 says it must be, typed out by applying the rules (member names sorted
by UTF-16 code unit, no insignificant whitespace). ``rfc8785`` then computes the
same string independently and the script aborts, writing nothing, if the two
disagree. So a case is wrong only if the hand derivation and the reference
package are wrong in the same way.

The worked example in spec 2.2 is included as ``SPEC_EXAMPLE`` and checked the
same way, which keeps the specification and these vectors from drifting apart.

The key-syntax cases (2.1) need no package: the rule is "1 to 255 characters of
printable ASCII (VCHAR, 0x21-0x7E), with no whitespace", and each case is that
sentence applied.

Usage::

    uv run tools/gen_idempotency_vectors.py           # write the vectors
    uv run tools/gen_idempotency_vectors.py --check   # fail if committed files are stale
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import rfc8785

SPEC_VERSION = "0.4.0"
OUT_DIR = Path("conformance/idempotency")

# The example written into spec 2.2. If this stops matching, either the spec or
# this file changed without the other, which is the drift worth failing on.
SPEC_EXAMPLE_JCS = '{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges"}'
SPEC_EXAMPLE_FINGERPRINT = "sha256:9d7a9f8a22e4d35d3efc80eafe7f0026713f6ad9ba4a3abd5c025e92036fd6eb"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint_of(jcs: str) -> str:
    """Spec 2.2 steps 3 and 4: SHA-256 of the UTF-8 bytes, no newline, no BOM."""
    return "sha256:" + sha256_hex(jcs.encode("utf-8"))


def raw_body_member(body: bytes) -> str:
    """Spec 2.2 step 1: a non-JSON body becomes "sha256:" + hex of its bytes."""
    return "sha256:" + sha256_hex(body)


# (name, method, path, media_type, body, body_member, hand-written JCS oracle)
# `body_member` is what step 1 puts under "body": a parsed JSON value, the
# "sha256:..." string for a non-JSON media type, or None for no body.
_HELLO = raw_body_member(b"hello")

FINGERPRINT_CASES: list[tuple[str, str, str, str | None, str | None, Any, str]] = [
    (
        "post-json-object-sorts-member-names",
        "POST", "/v1/charges", "application/json", '{"b":1,"a":2}',
        {"b": 1, "a": 2},
        '{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges"}',
    ),
    (
        "get-with-no-body-is-null",
        "GET", "/v1/charges", None, None,
        None,
        '{"body":null,"method":"GET","path":"/v1/charges"}',
    ),
    (
        "zero-length-body-is-null",
        "POST", "/v1/charges", "application/json", "",
        None,
        '{"body":null,"method":"POST","path":"/v1/charges"}',
    ),
    (
        "non-json-media-type-hashes-the-raw-bytes",
        "POST", "/v1/upload", "text/plain", "hello",
        _HELLO,
        '{"body":"' + _HELLO + '","method":"POST","path":"/v1/upload"}',
    ),
    (
        "media-type-parameters-are-ignored",
        "POST", "/v1/charges", "application/json; charset=utf-8", '{"a":2,"b":1}',
        {"a": 2, "b": 1},
        '{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges"}',
    ),
    (
        "json-subtype-suffix-is-json",
        "POST", "/v1/charges", "application/vnd.api+json", '{"a":2,"b":1}',
        {"a": 2, "b": 1},
        '{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges"}',
    ),
    (
        "media-type-case-is-ignored",
        "POST", "/v1/charges", "APPLICATION/JSON", '{"a":2,"b":1}',
        {"a": 2, "b": 1},
        '{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges"}',
    ),
    (
        "query-string-is-part-of-the-path",
        "POST", "/v1/charges?a=1&b=2", "application/json", '{"a":2,"b":1}',
        {"a": 2, "b": 1},
        '{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges?a=1&b=2"}',
    ),
    (
        "query-order-is-not-normalised",
        "POST", "/v1/charges?b=2&a=1", "application/json", '{"a":2,"b":1}',
        {"a": 2, "b": 1},
        '{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges?b=2&a=1"}',
    ),
    (
        "empty-query-is-kept-as-received",
        "POST", "/v1/charges?", "application/json", '{"a":2,"b":1}',
        {"a": 2, "b": 1},
        '{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges?"}',
    ),
    (
        "percent-encoding-is-not-decoded",
        "POST", "/v1/charges%2Fx", "application/json", '{"a":2,"b":1}',
        {"a": 2, "b": 1},
        '{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges%2Fx"}',
    ),
    (
        "trailing-slash-is-not-collapsed",
        "POST", "/v1/charges/", "application/json", '{"a":2,"b":1}',
        {"a": 2, "b": 1},
        '{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges/"}',
    ),
    (
        "method-is-uppercase-ascii",
        "DELETE", "/v1/charges/ch_1", None, None,
        None,
        '{"body":null,"method":"DELETE","path":"/v1/charges/ch_1"}',
    ),
    (
        "json-string-body-is-a-json-value",
        "POST", "/v1/notes", "application/json", '"hi"',
        "hi",
        '{"body":"hi","method":"POST","path":"/v1/notes"}',
    ),
    (
        "json-array-body-keeps-its-order",
        "POST", "/v1/batch", "application/json", "[2,1]",
        [2, 1],
        '{"body":[2,1],"method":"POST","path":"/v1/batch"}',
    ),
    (
        "nested-objects-sort-at-every-level",
        "POST", "/v1/charges", "application/json", '{"b":{"d":1,"c":2},"a":3}',
        {"b": {"d": 1, "c": 2}, "a": 3},
        '{"body":{"a":3,"b":{"c":2,"d":1}},"method":"POST","path":"/v1/charges"}',
    ),
]

# Bodies the spec rejects before a fingerprint exists (2.2 step 1).
FINGERPRINT_ERROR_CASES: list[tuple[str, str, str, str, str, str]] = [
    (
        "json-media-type-with-unparseable-body",
        "POST", "/v1/charges", "application/json", "{", "HEPH-VAL-422",
    ),
    (
        "json-media-type-with-empty-object-missing-brace",
        "POST", "/v1/charges", "application/json", '{"a":', "HEPH-VAL-422",
    ),
    (
        "json-subtype-with-unparseable-body",
        "POST", "/v1/charges", "application/merge-patch+json", "nope", "HEPH-VAL-422",
    ),
]

# Spec 2.1: 1 to 255 characters of printable ASCII (VCHAR, 0x21-0x7E), no
# whitespace. A required endpoint rejects a violation with HEPH-IDEMP-400; an
# endpoint that does not require a key ignores one instead of failing.
KEY_CASES: list[tuple[str, str | None, bool, dict[str, Any]]] = [
    ("uuid-is-accepted", "8e03978e-40d5-43e8-bc93-6894a57f9324", True, {"ok": True}),
    ("single-vchar-is-the-minimum-length", "a", True, {"ok": True}),
    ("lowest-vchar-0x21-is-accepted", "!", True, {"ok": True}),
    ("highest-vchar-0x7e-is-accepted", "~", True, {"ok": True}),
    ("255-characters-is-accepted", "k" * 255, True, {"ok": True}),
    ("256-characters-is-rejected", "k" * 256, True, {"error": "HEPH-IDEMP-400"}),
    ("empty-key-is-rejected", "", True, {"error": "HEPH-IDEMP-400"}),
    ("missing-key-is-rejected", None, True, {"error": "HEPH-IDEMP-400"}),
    ("space-is-rejected", "ab cd", True, {"error": "HEPH-IDEMP-400"}),
    ("tab-is-rejected", "ab\tcd", True, {"error": "HEPH-IDEMP-400"}),
    ("newline-is-rejected", "ab\ncd", True, {"error": "HEPH-IDEMP-400"}),
    ("del-0x7f-is-rejected", "ab\x7fcd", True, {"error": "HEPH-IDEMP-400"}),
    ("control-0x1f-is-rejected", "ab\x1fcd", True, {"error": "HEPH-IDEMP-400"}),
    ("non-ascii-is-rejected", "abcdé", True, {"error": "HEPH-IDEMP-400"}),
    # Not required: a malformed key is ignored, never a failure (2.1).
    ("optional-endpoint-ignores-a-malformed-key", "ab cd", False, {"ignored": True}),
    ("optional-endpoint-ignores-a-missing-key", None, False, {"ignored": True}),
    ("optional-endpoint-still-uses-a-valid-key", "8e03978e-40d5", False, {"ok": True}),
]


def _canonical(value: Any) -> str:
    """The JCS form, from the reference package, as text."""
    return rfc8785.dumps(value).decode("utf-8")


def build_fingerprint_file() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    disagreements: list[str] = []

    # The spec's own worked example, checked both ways before anything else.
    spec_independent = _canonical({"method": "POST", "path": "/v1/charges", "body": {"b": 1, "a": 2}})
    if spec_independent != SPEC_EXAMPLE_JCS:
        disagreements.append(
            f"spec 2.2 example: rfc8785 gives {spec_independent!r}, spec says {SPEC_EXAMPLE_JCS!r}"
        )
    if fingerprint_of(SPEC_EXAMPLE_JCS) != SPEC_EXAMPLE_FINGERPRINT:
        disagreements.append(
            f"spec 2.2 example: computed {fingerprint_of(SPEC_EXAMPLE_JCS)}, spec says {SPEC_EXAMPLE_FINGERPRINT}"
        )

    for name, method, path, media_type, body, body_member, oracle in FINGERPRINT_CASES:
        independent = _canonical({"method": method, "path": path, "body": body_member})
        if independent != oracle:
            disagreements.append(f"{name}: rfc8785 gives {independent!r}, the hand oracle says {oracle!r}")
            continue
        case: dict[str, Any] = {
            "name": name,
            "input": {"method": method, "path": path},
            "expect": {"jcs": oracle, "fingerprint": fingerprint_of(oracle)},
        }
        if media_type is not None:
            case["input"]["media_type"] = media_type
        if body is not None:
            case["input"]["body"] = body
        cases.append(case)

    for name, method, path, media_type, body, code in FINGERPRINT_ERROR_CASES:
        cases.append(
            {
                "name": name,
                "input": {"method": method, "path": path, "media_type": media_type, "body": body},
                "expect": {"error": code},
            }
        )

    if disagreements:
        raise ValueError(
            "the hand-written oracle and the reference package disagree; nothing written:\n  "
            + "\n  ".join(disagreements)
        )

    return {
        "suite": "idempotency.fingerprint",
        "spec": SPEC_VERSION,
        "description": (
            "Request fingerprints (heph-spec 2.2). Each case carries the JCS string as well as the "
            "fingerprint, so a failure says which of the four steps went wrong rather than only that "
            "a digest differed. A body is the parsed JSON value for a JSON media type, "
            '"sha256:<hex of the raw bytes>" for any other, and null when there is no body.'
        ),
        "source": (
            "RFC 8785 (JCS) by way of the rfc8785 reference package, SHA-256 from the Python standard "
            "library, and heph-spec 2.2 including its worked example. No Hephaestus implementation was "
            "run; see tools/gen_idempotency_vectors.py."
        ),
        "cases": cases,
    }


def build_key_file() -> dict[str, Any]:
    return {
        "suite": "idempotency.key",
        "spec": SPEC_VERSION,
        "description": (
            "Idempotency-Key syntax (heph-spec 2.1): 1 to 255 characters of printable ASCII "
            "(VCHAR, 0x21-0x7E) with no whitespace. `required` is whether the endpoint requires a key: "
            "when it does not, a malformed key is ignored rather than failing the request."
        ),
        "source": "heph-spec 2.1, applied case by case. No implementation was run.",
        "cases": [
            {
                "name": name,
                "input": {"key": key, "required": required},
                "expect": expect,
            }
            for name, key, required, expect in KEY_CASES
        ],
    }


def generate(repo_root: Path) -> dict[Path, str]:
    """Map each output path to its content."""
    return {
        repo_root / OUT_DIR / "fingerprint.json": json.dumps(build_fingerprint_file(), indent=2) + "\n",
        repo_root / OUT_DIR / "key.json": json.dumps(build_key_file(), indent=2) + "\n",
    }


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    check = "--check" in args
    unknown = [a for a in args if a != "--check"]
    if unknown:
        print(f"usage: gen_idempotency_vectors.py [--check] (unknown: {' '.join(unknown)})", file=sys.stderr)
        return 2
    root = root or Path(__file__).resolve().parents[1]

    try:
        files = generate(root)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1

    if check:
        drift = [p for p, text in files.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
        for path in drift:
            print(
                f"{path.relative_to(root)} is stale or missing; run: uv run tools/gen_idempotency_vectors.py",
                file=sys.stderr,
            )
        return 1 if drift else 0

    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
