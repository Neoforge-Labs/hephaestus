"""Claiming an idempotency key: the decision of spec 2.3 to 2.8.

This is the function the module exists for. It answers one question -- may this
request run? -- and the answer decides whether a retried payment is charged
twice. Nothing here opens a connection or performs I/O of its own: every
statement goes through the caller's :class:`~hephkit.idempotency.ports.Executor`.

**The caller's connection must have no transaction open and must be at the
default ``READ COMMITTED`` isolation level.** Both are part of the contract, and
both are explained on :meth:`IdempotencyStore.claim`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Final, Literal

from hephkit.errors import HephError
from hephkit.idempotency import _sql
from hephkit.idempotency.ports import Executor, Proceed, Replay

__all__ = ["IdempotencyStore"]

# The defaults of 2.7, which also fix the floor: retention MAY be configured
# longer, so anything shorter is not a setting but a hole in the guarantee.
DEFAULT_RETENTION: Final = timedelta(hours=24)
DEFAULT_LEASE: Final = timedelta(seconds=60)

# A claim reads the record it failed to insert. A concurrent release() or
# retention purge can remove that record in between, leaving nothing to decide
# on, and the honest answer is to claim the key again. Twice is enough: a third
# pass would mean something is removing the key as fast as we create it, which
# is a retry-later condition (2.5) rather than something to loop on.
_PASSES: Final = 2


class IdempotencyStore:
    """The record store of spec section 2, over a caller-supplied executor.

    ``retention`` is 2.7's window, 24 hours by default and configurable only
    longer. ``lease`` is how long an ``in_flight`` record is protected before a
    genuine retry may take it over (2.8), 60 seconds by default.
    """

    def __init__(
        self,
        *,
        retention: timedelta = DEFAULT_RETENTION,
        lease: timedelta = DEFAULT_LEASE,
    ) -> None:
        if retention < DEFAULT_RETENTION:
            raise ValueError(
                f"retention may only be configured longer than {DEFAULT_RETENTION} (spec 2.7), "
                f"not {retention}"
            )
        if lease <= timedelta(0):
            raise ValueError(f"lease must be a positive interval, not {lease}")
        self._retention = retention
        self._lease = lease

    async def claim(
        self,
        ex: Executor,
        *,
        scope: str,
        key: str,
        fingerprint: str,
        kind: Literal["http", "event"] = "http",
    ) -> Proceed | Replay:
        """Claim ``key`` for one operation, committing on its own (spec 2.3 to 2.8).

        **``ex`` must be on a connection with no transaction open**, so each of
        claim's statements commits as it runs and the ``in_flight`` record is
        visible to the next request at once. Joining the caller's transaction
        instead would hide the record until the handler finished, and 2.5's 409,
        the lease and 2.8's takeover would all be unreachable (design finding
        2). For asyncpg that means a connection you have not started a
        transaction on; for SQLAlchemy, a connection with
        ``isolation_level="AUTOCOMMIT"``.

        **The connection must be at ``READ COMMITTED``**, Postgres's default.
        Under ``REPEATABLE READ`` or ``SERIALIZABLE``, ``ON CONFLICT`` and ``FOR
        UPDATE`` against a row a concurrent transaction has just committed raise
        a serialization failure (``40001``) instead of blocking. Nothing here
        retries one: re-running a claim means re-running the handler, so a
        ``40001`` surfaces to the caller.

        Returns :class:`Proceed` when the operation may run and
        :class:`Replay` when a completed record answers the request instead.
        Raises ``HephError`` with ``HEPH-IDEMP-422`` when the key was used for a
        different payload (2.6) or ``HEPH-IDEMP-409`` while the original is in
        flight (2.5); the registry renders both, so there is no response body to
        build here.

        ``scope`` is the authenticated principal's tenant id, or the empty
        string when there is none (2.3). The empty string is a real scope, not
        the absence of one. ``kind`` tells an event from an HTTP request, which
        is what lets a completed event record carry no response.
        """
        # `scope=None` is the mistake worth catching: as a value it would be a
        # NOT NULL violation from whichever driver got there first, and if it
        # were ever coerced to "" it would quietly merge every tenant's keys.
        for name, value in (("scope", scope), ("key", key)):
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a str, not {type(value).__name__}")

        for _ in range(_PASSES):
            claimed = await ex.fetch_one(
                _sql.CLAIM_INSERT,
                [scope, key, fingerprint, kind, self._lease, self._retention],
            )
            if claimed is not None:
                # The key was free (2.3), or the record on it had aged out and
                # this statement has just replaced it (2.7).
                return Proceed(taken_over=False)
            record = await ex.fetch_one(_sql.CLAIM_READ, [scope, key])
            if record is None:
                continue  # Removed between the two statements; claim it again.
            return await self._decide(ex, record, scope=scope, key=key, fingerprint=fingerprint)
        raise HephError("HEPH-IDEMP-409")

    async def _decide(
        self,
        ex: Executor,
        record: Mapping[str, Any],
        *,
        scope: str,
        key: str,
        fingerprint: str,
    ) -> Proceed | Replay:
        """Answer for a record that already exists, in the spec's order.

        **The order of these branches is the spec's order of precedence, not a
        convenience.** 2.6 is tested first because it applies "whatever its
        state and whether or not an in_flight lease has expired", and it beats
        2.5: a changed payload names a client bug, where a live lease would only
        have said retry later. Checking the state first and the fingerprint
        inside each branch answers the same way everywhere except that one case,
        where it tells a client to retry a request that can never succeed under
        this key -- and every happy-path test still passes.
        """
        if record["fingerprint"] != fingerprint:
            raise HephError("HEPH-IDEMP-422")  # 2.6
        if record["state"] == "completed":
            body = record["response_body"]
            return Replay(
                status=record["response_status"],
                body=bytes(body) if body is not None else b"",
                media_type=record["response_media_type"],
            )
        if not record["lease_expired"]:
            raise HephError("HEPH-IDEMP-409")  # 2.5
        taken = await ex.fetch_one(_sql.CLAIM_TAKE_OVER, [scope, key, fingerprint, self._lease])
        if taken is None:
            # The lease was live again by the time the update ran, so another
            # request took the record over first. That is 2.5 for this one.
            raise HephError("HEPH-IDEMP-409")
        return Proceed(taken_over=True)  # 2.8
