"""Standard Webhooks signing and verification (spec section 5). Experimental.

The HMAC, the base64 rules, the timestamp window and the constant-time
comparison are all in the Rust core.
"""

import time
from collections.abc import Mapping

from hephkit import _core
from hephkit._core import SignatureError

__all__ = ["SignatureError", "sign", "verify"]


def sign(secret: str, msg_id: str, timestamp: int, payload: bytes) -> str:
    """The ``webhook-signature`` value ``v1,<base64>`` for a message.

    An unusable secret raises :class:`SignatureError` with ``code`` ``HEPH-VAL-422``.
    A ``timestamp`` outside the signed 64-bit range raises ``OverflowError``.
    """
    return _core.sign(secret, msg_id, timestamp, payload)


def verify(
    secret: str,
    headers: Mapping[str, str],
    payload: bytes,
    *,
    now: int | None = None,
    tolerance: int = _core.DEFAULT_TOLERANCE_SECS,
) -> None:
    """Return ``None`` if the message verifies; raise :class:`SignatureError`
    (``code`` ``HEPH-WH-401``) otherwise, whatever the reason (spec 5.6).

    ``headers`` is looked up case-insensitively (HTTP field names, RFC 9110) for
    ``webhook-id``, ``webhook-timestamp`` and ``webhook-signature``; an absent
    header is the empty string and is rejected. A name given twice with different
    values (differing only in case) is rejected, whatever the key order. ``now``
    defaults to the wall clock. ``now`` or ``tolerance`` outside the signed 64-bit
    range raises ``OverflowError``.
    """
    now_secs = int(time.time()) if now is None else now
    lowered: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(key, str):
            continue  # not a header name
        name = key.lower()
        if name in lowered and lowered[name] != value:
            # One field under two spellings with different values (RFC 9110
            # 5.2): fail closed, with the core's own rejection, whichever order
            # the mapping was built in.
            _core.verify(secret, "", "", "", payload, now_secs, tolerance)
        lowered[name] = value
    _core.verify(
        secret,
        lowered.get("webhook-id", ""),
        lowered.get("webhook-timestamp", ""),
        lowered.get("webhook-signature", ""),
        payload,
        now_secs,
        tolerance,
    )
