"""Idempotency keys, fingerprints and the record store (spec section 2). Maturity: experimental.

The whole of section 2 is here. 2.1 and 2.2 -- key syntax and the request
fingerprint -- are pure functions over a request, pinned by
``conformance/idempotency/*.json``, and they live in this file. 2.3 to 2.8 are
the record store, which needs SQL transactions and constraints (CLAUDE.md rule
6), so it lives in submodules whose names this module re-exports:

* ``IdempotencyStore`` is the decision of 2.3 to 2.8 -- proceed, replay, 409 or
  422 -- together with ``complete``, ``release``, ``purge_expired`` and the
  ``idempotent_record`` context manager, whose default way out is release.
  ``Record`` is what that context manager yields and ``IdempotencyStateError``
  what ``complete`` raises when the record is not this attempt's to complete.
* ``Executor`` is the port every statement runs through. It is "run my
  statements in your transaction", never "give me a connection"; ``Executors``
  pairs the two a request needs, and ``Proceed`` and ``Replay`` are what a claim
  answers.
* ``AsyncpgExecutor``, ``SQLAlchemyExecutor``, the ``*_executors`` factories and
  the ``*_work_connection`` accessors are the adapters for the two driver
  stacks. Drivers are imported lazily, so importing this module requires
  neither of them.
* ``SCHEMA_SQL`` is the table: the text of ``schema.sql``, safe to run
  repeatedly. There is deliberately no ``create_schema``: the DDL is a
  multi-statement script while the port runs one parameterised statement at a
  time, so the caller executes this text on a connection of its own or pastes it
  into its own migration. The repo ships no migration tooling (ADR 0020).

**The two framework integrations stay in their own modules and are not
re-exported here**, so that importing ``hephkit.idempotency`` pulls in no web
framework -- the same split as ``hephkit.errors`` and ``hephkit.errors.fastapi``:

* ``hephkit.idempotency.fastapi.idempotent_route`` makes one route idempotent on
  its ``Idempotency-Key`` header. It imports FastAPI, and its handler must
  return a fully built ``Response``.
* ``hephkit.idempotency.worker.idempotent`` makes an event handler idempotent on
  its event id.

hephkit opens no connection, owns no pool and runs no background task: the
caller hands the store executors over connections it owns, and ``purge_expired``
(2.7's retention sweep) is the consumer's to schedule. The transaction boundary
differs per call and the two are not interchangeable -- ``claim`` and ``release``
commit on their own, ``complete`` runs inside the caller's transaction -- which
is what makes 2.5, 2.7 and 2.8 reachable at all. ADR 0020 records that and why
one transaction is not an option; the docs page is `/modules/idempotency`.

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
from hephkit.idempotency._sql import DDL as SCHEMA_SQL
from hephkit.idempotency.adapters import (
    AsyncpgExecutor,
    SQLAlchemyExecutor,
    asyncpg_executors,
    asyncpg_work_connection,
    sqlalchemy_executors,
    sqlalchemy_work_connection,
)
from hephkit.idempotency.ports import Executor, Executors, Proceed, Replay
from hephkit.idempotency.store import IdempotencyStateError, IdempotencyStore, Record

__all__ = [
    "MAX_KEY_LENGTH",
    "SCHEMA_SQL",
    "AsyncpgExecutor",
    "Executor",
    "Executors",
    "IdempotencyStateError",
    "IdempotencyStore",
    "Proceed",
    "Record",
    "Replay",
    "SQLAlchemyExecutor",
    "asyncpg_executors",
    "asyncpg_work_connection",
    "fingerprint",
    "fingerprint_document",
    "is_json_media_type",
    "sqlalchemy_executors",
    "sqlalchemy_work_connection",
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
