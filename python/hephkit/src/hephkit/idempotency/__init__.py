"""Idempotency keys and request fingerprints (spec section 2). Maturity: experimental.

**This module itself is 2.1 and 2.2 only.** Key syntax and the request
fingerprint are pure functions over a request, pinned by
``conformance/idempotency/*.json``, and nothing here talks to a database or
performs I/O.

The record store that 2.3 to 2.8 describe lives in the submodules, because it
needs SQL transactions and constraints (CLAUDE.md rule 6):

* ``hephkit.idempotency.store.IdempotencyStore.claim`` is the decision of 2.3
  to 2.8 -- proceed, replay, 409 or 422.
* ``hephkit.idempotency.ports`` holds the executor port it runs through and the
  outcome types, and ``hephkit.idempotency.adapters`` the asyncpg and
  SQLAlchemy executors. Neither this module nor ``ports`` imports a driver.
* ``schema.sql`` (also ``_sql.DDL``) is the table.

``store.IdempotencyStore`` also completes and releases a record, and
``store.idempotent_record`` wraps all three around a block. The FastAPI route
integration is ``hephkit.idempotency.fastapi.idempotent_route``, and the worker
decorator, keyed on an event id, is ``hephkit.idempotency.worker.idempotent``.

The fingerprint is deliberately built from the kit's existing primitives:
``hephkit.hashing.content_hash`` canonicalises with RFC 8785 and hashes in one
step, which is exactly steps 2 to 4 of 2.2, and ``content_hash_bytes`` is step
1's non-JSON branch. There is no hashing code of its own here to disagree with
the rest of the kit.
"""

from __future__ import annotations

import json
from typing import Any, Final

from hephkit.errors import HephError
from hephkit.hashing import content_hash, content_hash_bytes

__all__ = [
    "MAX_KEY_LENGTH",
    "fingerprint",
    "fingerprint_document",
    "is_json_media_type",
    "validate_key",
]

# Spec 2.1: 1 to 255 characters of printable ASCII (VCHAR, 0x21-0x7E).
MAX_KEY_LENGTH: Final = 255
_VCHAR_LOW: Final = 0x21
_VCHAR_HIGH: Final = 0x7E


def _is_valid_key(key: str) -> bool:
    return 1 <= len(key) <= MAX_KEY_LENGTH and all(_VCHAR_LOW <= ord(c) <= _VCHAR_HIGH for c in key)


def validate_key(key: str | None, *, required: bool = True) -> str | None:
    """Check an ``Idempotency-Key`` header value (spec 2.1).

    Returns the key when it is usable, or ``None`` when there is nothing to key
    on and the endpoint does not require one.

    ``required`` is the endpoint's own setting, not the client's. When it is
    true, a missing, empty or malformed key raises ``HephError`` with
    ``HEPH-IDEMP-400``. When it is false, the same key is *ignored*: 2.1 says an
    endpoint that does not require a key MUST NOT fail the request over one, so
    a client sending a bad key to an endpoint that never promised idempotency
    still gets its request served.

    Keys are opaque. The caller is responsible for not putting personal data in
    one, because the key is recorded as the ``idempotency.key`` telemetry
    attribute and is not redacted.
    """
    if key is not None and _is_valid_key(key):
        return key
    if not required:
        return None
    raise HephError(
        "HEPH-IDEMP-400",
        "The Idempotency-Key header is missing or is not 1 to 255 printable ASCII characters "
        "without whitespace.",
    )


def is_json_media_type(media_type: str | None) -> bool:
    """Whether 2.2 treats this ``Content-Type`` as JSON.

    Compared case-insensitively on type/subtype with parameters ignored, so
    ``application/json; charset=utf-8`` is JSON, and any subtype ending in
    ``+json`` (``application/vnd.api+json``) is too.
    """
    if not media_type:
        return False
    essence = media_type.split(";", 1)[0].strip().lower()
    return essence == "application/json" or essence.endswith("+json")


def _body_member(body: bytes | None, media_type: str | None) -> Any:
    """Step 1's ``body`` member: the JSON value, a digest string, or None."""
    if not body:
        # No body or a zero-length body is the JSON value null (2.2). `not
        # body` covers both, and b"" is the zero-length case the spec names.
        return None
    if not is_json_media_type(media_type):
        return content_hash_bytes(body)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        # 2.2: a body with a JSON media type that does not parse is rejected.
        # The request never gets a fingerprint, so this is the caller's error
        # rather than a mismatch with a stored one.
        raise HephError(
            "HEPH-VAL-422",
            "The request body is declared as JSON but is not valid JSON.",
        ) from exc


def fingerprint_document(
    method: str,
    path: str,
    body: bytes | None = None,
    media_type: str | None = None,
) -> dict[str, Any]:
    """The three-member object of 2.2 step 1, before canonicalisation.

    Exposed because the conformance vectors carry the canonical string as well
    as the digest: a failure can then say which step went wrong rather than
    only that two hashes differed.
    """
    return {
        # 2.2: the method is an uppercase ASCII string.
        "method": method.upper(),
        # The raw request target, exactly as received. Never normalised: no
        # percent-decoding, case-folding, query reordering or slash collapsing,
        # so two orderings of one query are two different requests. Callers
        # must pass the target they received, not one a framework has tidied.
        "path": path,
        "body": _body_member(body, media_type),
    }


def fingerprint(
    method: str,
    path: str,
    body: bytes | None = None,
    media_type: str | None = None,
) -> str:
    """The request fingerprint of spec 2.2: ``sha256:`` + 64 lowercase hex.

    Identifies the request a key was first used with. Headers, including the
    key itself, are not part of it.

    Raises ``HephError`` with ``HEPH-VAL-422`` when the body claims a JSON media
    type and does not parse.
    """
    # content_hash canonicalises with RFC 8785 and hashes the UTF-8 bytes of
    # the result: steps 2, 3 and 4 in one call, sharing the kit's single
    # canonicaliser rather than repeating it.
    return content_hash(fingerprint_document(method, path, body, media_type))
