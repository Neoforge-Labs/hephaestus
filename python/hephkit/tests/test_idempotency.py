"""Cases for section 2 that the conformance vectors cannot express.

The vectors carry a body as text, so a body that is not valid UTF-8 has no
place in them, and every vector with a body also declares a media type. Both
are real requests, so they are covered here instead. Everything the vectors
*can* express is checked by tests/test_conformance.py against them, not
duplicated here.
"""

from __future__ import annotations

import pytest

from hephkit.errors import HephError
from hephkit.hashing import content_hash_bytes
from hephkit.idempotency import (
    fingerprint,
    fingerprint_document,
    is_json_media_type,
    validate_key,
)


def test_a_body_with_no_media_type_is_hashed_as_raw_bytes() -> None:
    """No Content-Type is not JSON, so 2.2's "any other media type" applies."""
    doc = fingerprint_document("POST", "/v1/upload", b"hello", None)
    assert doc["body"] == content_hash_bytes(b"hello")


def test_a_json_body_that_is_not_utf8_is_rejected() -> None:
    """2.2 rejects a JSON body that cannot be parsed; undecodable counts.

    JSON text is UTF-8, so bytes that do not decode never had a chance of
    parsing. Returning HEPH-VAL-422 rather than letting UnicodeDecodeError
    escape keeps the failure inside the registry, where a caller can act on it.
    """
    with pytest.raises(HephError) as exc:
        fingerprint("POST", "/v1/charges", b"\xff\xfe", "application/json")
    assert exc.value.code == "HEPH-VAL-422"


def test_an_unparseable_json_body_names_the_registry_code() -> None:
    with pytest.raises(HephError) as exc:
        fingerprint("POST", "/v1/charges", b"{", "application/json")
    assert exc.value.code == "HEPH-VAL-422"


@pytest.mark.parametrize(
    ("media_type", "expected"),
    [
        ("application/json", True),
        ("application/json; charset=utf-8", True),
        ("  APPLICATION/JSON  ", True),
        ("application/vnd.api+json", True),
        ("application/merge-patch+json;charset=utf-8", True),
        ("text/plain", False),
        ("application/jsonish", False),
        ("application/x-json", False),
        ("", False),
        (None, False),
    ],
)
def test_is_json_media_type(media_type: str | None, expected: bool) -> None:
    assert is_json_media_type(media_type) is expected


def test_the_method_member_is_uppercased() -> None:
    """2.2 states the member is an uppercase ASCII string."""
    assert fingerprint_document("post", "/v1/charges")["method"] == "POST"
    assert fingerprint("post", "/x") == fingerprint("POST", "/x")


def test_headers_are_not_part_of_the_fingerprint() -> None:
    """2.2: headers, the key included, are not in it.

    There is no parameter for them, which is the real guarantee; this pins that
    the signature does not grow one by accident.
    """
    import inspect

    assert list(inspect.signature(fingerprint).parameters) == ["method", "path", "body", "media_type"]


def test_an_optional_endpoint_keeps_a_valid_key() -> None:
    """Ignoring a bad key must not mean ignoring a good one."""
    assert validate_key("abc", required=False) == "abc"
    assert validate_key("a b", required=False) is None
    assert validate_key(None, required=False) is None
