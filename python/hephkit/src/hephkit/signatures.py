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

    ``headers`` is looked up by the exact lower-case names ``webhook-id``,
    ``webhook-timestamp`` and ``webhook-signature``; an absent header is the
    empty string and is rejected. ``now`` defaults to the wall clock.
    """
    _core.verify(
        secret,
        headers.get("webhook-id", ""),
        headers.get("webhook-timestamp", ""),
        headers.get("webhook-signature", ""),
        payload,
        int(time.time()) if now is None else now,
        tolerance,
    )
