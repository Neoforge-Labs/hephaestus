"""Canonical JSON, content hashes and UUIDv7 (spec section 4). Experimental.

Every rule lives in the Rust core. This module only turns a Python object into
JSON text for the core; nothing is canonicalised or validated here, so NaN,
Infinity, lone surrogates, duplicate member names and over-deep nesting are
rejected by the core with ``HEPH-VAL-422``.
"""

import json
from typing import Any

from hephkit import _core
from hephkit._core import HashingError

__all__ = [
    "HashingError",
    "canonical_json",
    "content_hash",
    "content_hash_bytes",
    "new_uuid7",
]


def _to_json_text(obj: Any) -> str:
    # ensure_ascii keeps lone surrogates as escapes (so the core can reject
    # them) instead of failing to encode; allow_nan emits the literals NaN and
    # Infinity so that the core, not Python, rejects them.
    return json.dumps(obj, ensure_ascii=True, allow_nan=True, separators=(",", ":"))


def canonical_json(obj: Any) -> str:
    """RFC 8785 canonical form of ``obj`` (spec 4)."""
    return _core.canonical_json(_to_json_text(obj))


def content_hash(obj: Any) -> str:
    """``sha256:`` + hex digest of the canonical form of ``obj`` (spec 4.2)."""
    return _core.content_hash_json(_to_json_text(obj))


def content_hash_bytes(data: bytes) -> str:
    """``sha256:`` + hex digest of ``data``."""
    return _core.content_hash_bytes(data)


def new_uuid7() -> str:
    """A new lowercase hyphenated UUIDv7; strictly increasing within a process."""
    return _core.new_uuid7()
