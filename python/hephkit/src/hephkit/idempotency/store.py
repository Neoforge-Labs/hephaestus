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

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Final, Literal

from hephkit.errors import HephError
from hephkit.hashing import new_uuid7
# `hephkit.idempotency` imports this module from its own body, so the parent
# package is in sys.modules but only partly populated when this line runs.
# Importing a *submodule* is safe there: with the attribute not yet set, the
# import system falls back to importing (or finding in sys.modules)
# `hephkit.idempotency._sql` itself. As it happens `__init__` imports `_sql`
# ahead of `store`, so the attribute is already present either way. Importing a
# *name* would not be safe: `from hephkit.idempotency import fingerprint` here
# has no such fallback and would raise on the partially initialised parent.
from hephkit.idempotency import _sql
from hephkit.idempotency.ports import Executor, Proceed, Replay

__all__ = ["IdempotencyStateError", "IdempotencyStore", "Record"]


class IdempotencyStateError(RuntimeError):
    """``complete()`` found the record is not the caller's to complete.

    A server-side invariant failure, not a client-facing one, so it is not a
    ``HephError`` and has no registry code. Raised when the record is gone, is
    already completed, or is held by another attempt, which after a 2.8
    takeover means this attempt has been superseded.
    """


class Record:
    """What ``idempotent_record()`` hands the block: whether to run, and how to say how it went.

    ``replay`` is not ``None`` when a completed record already answers the
    request: the block did not claim anything, so it returns that response and
    does the work no further. ``taken_over`` is the claim's flag, for telemetry.

    The attempt token (2.8) never reaches the caller: ``idempotent_record``
    holds it between the claim and the finish.
    """

    def __init__(self, *, replay: Replay | None, taken_over: bool) -> None:
        self.replay = replay
        self.taken_over = taken_over
        self._outcome: tuple[int, bytes, str | None] | None = None

    def finish(self, status: int, body: bytes, media_type: str | None = None) -> None:
        """State the outcome. It is written when the block exits cleanly.

        A ``status`` of 500 or above is an outcome that releases the record
        rather than storing it (2.8), so the client can retry. A later call
        replaces an earlier one.
        """
        if self.replay is not None:
            raise RuntimeError("this record is a replay: return the stored response, do not finish it")
        self._outcome = (status, body, media_type)


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
        # All four are NOT NULL text columns, and every one of them answers a
        # `None` differently without this guard: scope and key as a driver's NOT
        # NULL violation on the insert path, kind as a CHECK violation,
        # fingerprint as a NOT NULL violation when the key is free but a plain
        # HEPH-IDEMP-422 when it is not. One caller mistake, four answers, two
        # of which read as the client's fault. `scope` is the one that matters
        # most: coerced to "" it would quietly merge every tenant's keys.
        for name, value in (
            ("scope", scope),
            ("key", key),
            ("fingerprint", fingerprint),
            ("kind", kind),
        ):
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a str, not {type(value).__name__}")

        for _ in range(_PASSES):
            attempt_id = new_uuid7()
            claimed = await ex.fetch_one(
                _sql.CLAIM_INSERT,
                [scope, key, fingerprint, kind, self._lease, self._retention, attempt_id],
            )
            if claimed is not None:
                # The key was free (2.3), or the record on it had aged out and
                # this statement has just replaced it (2.7).
                return Proceed(taken_over=False, attempt_id=attempt_id)
            record = await ex.fetch_one(_sql.CLAIM_READ, [scope, key])
            if record is None:
                continue  # Removed between the two statements; claim it again.
            return await self._answer_existing_record(
                ex, record, scope=scope, key=key, fingerprint=fingerprint
            )
        # Not 2.5: nothing is holding this key, something is removing it as fast
        # as it is created. 409 is still the answer the client can act on, so
        # the detail says what actually happened rather than the registry's
        # "still being processed".
        raise HephError(
            "HEPH-IDEMP-409",
            "The record for this key was removed while it was being claimed. Retry the request.",
        )

    async def _answer_existing_record(
        self,
        ex: Executor,
        record: Mapping[str, Any],
        *,
        scope: str,
        key: str,
        fingerprint: str,
    ) -> Proceed | Replay:
        """Answer for a record that already exists, in the spec's order.

        Not a pure decision: the 2.8 branch writes, because taking the record
        over is part of answering.

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
        attempt_id = new_uuid7()
        taken = await ex.fetch_one(
            _sql.CLAIM_TAKE_OVER, [scope, key, fingerprint, self._lease, attempt_id]
        )
        if taken is None:
            # The lease was live again by the time the update ran, so another
            # request took the record over first. That is 2.5 for this one.
            raise HephError("HEPH-IDEMP-409")
        return Proceed(taken_over=True, attempt_id=attempt_id)  # 2.8

    async def complete(
        self,
        ex: Executor,
        *,
        scope: str,
        key: str,
        attempt_id: str,
        status: int,
        body: bytes,
        media_type: str | None = None,
    ) -> None:
        """Store the response and mark the record ``completed`` (spec 2.8).

        **``ex`` must be on the connection the handler's own writes went through,
        with its transaction still open, and the caller commits.** That is the
        point of the call: the stored response and the work it describes commit
        together or not at all, so a replay can never describe work that was
        rolled back. ``claim()`` is the opposite, and the difference is
        deliberate (see :mod:`hephkit.idempotency.ports`).

        Always stores a status. A record for an event has no HTTP response, and
        a caller with nothing to say stores ``204`` and ``b""``. A 4xx is stored
        like any other outcome. ``status`` of 500 or above is refused, because
        2.8 answers that with :meth:`release`.

        ``attempt_id`` is the one :class:`Proceed` carried. The record is written
        only while it is ``in_flight`` and still held by that attempt (2.8: a
        takeover transfers ownership). **When it is not, this raises
        :class:`IdempotencyStateError`, and the raise is deliberate:** the
        caller's transaction rolls back, and with it the handler's work. The
        alternative, a silent no-op, would commit the work while nothing
        recorded it, and the next retry would run it again. Undoing it is the
        safe direction: the attempt that owns the key does it once.

        Contrast :meth:`release`, which does not raise.

        One deliberate exception to the transaction rule above:
        :meth:`idempotent_record` stores a raised 4xx through the claim
        executor, outside the handler's transaction, because that transaction is
        about to roll back and there is no work for the response to describe.
        """
        for name, value in (("scope", scope), ("key", key), ("attempt_id", attempt_id)):
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a str, not {type(value).__name__}")
        if not isinstance(body, bytes):
            raise TypeError(f"body must be bytes, not {type(body).__name__}")
        if not 100 <= status < 500:
            raise ValueError(
                f"status {status} is not stored: 2.8 stores below 500 and releases at 500 "
                "and above, so call release() for a failed attempt"
            )
        updated = await ex.execute(_sql.COMPLETE, [scope, key, status, body, media_type, attempt_id])
        if updated != 1:
            raise IdempotencyStateError(
                f"cannot complete {key!r} in scope {scope!r}: the record is gone, already "
                f"completed, or held by another attempt than {attempt_id}. The caller's "
                "transaction must roll back."
            )

    async def release(self, ex: Executor, *, scope: str, key: str, attempt_id: str) -> None:
        """Remove an ``in_flight`` record so the client can retry (spec 2.8).

        For a 5xx or a handler that raised. **Like ``claim()``, ``ex`` must be on
        a connection with no transaction open**, so the delete commits on its
        own: the handler's transaction has been rolled back or abandoned, and a
        release that joined it would be undone with it and leave the key wedged
        until the lease ran out.

        Removes the record only while it is ``in_flight`` and still held by
        ``attempt_id`` (2.8). **Unlike** :meth:`complete`, **it does not raise
        when nothing matches.** This runs on the failure path, where raising
        would mask the original error, and a no-op is the correct outcome: a
        superseded attempt's key legitimately belongs to someone else now, and
        deleting it would let a third request run beside the owner. A completed
        record is never removed.
        """
        for name, value in (("scope", scope), ("key", key), ("attempt_id", attempt_id)):
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a str, not {type(value).__name__}")
        await ex.execute(_sql.RELEASE, [scope, key, attempt_id])

    async def purge_expired(self, ex: Executor) -> int:
        """Delete records past retention and return how many were removed (spec 2.7).

        A function for the consumer to schedule: hephkit starts no task. A record
        whose ``in_flight`` lease is still live is left alone however old it is,
        because retention expiry applies only when no attempt holds the key.
        """
        return await ex.execute(_sql.PURGE_EXPIRED, [self._retention])

    @asynccontextmanager
    async def idempotent_record(
        self,
        *,
        claim_ex: Executor,
        work_ex: Executor,
        scope: str,
        key: str,
        fingerprint: str,
        kind: Literal["http", "event"] = "http",
        render_error: Callable[[HephError], tuple[bytes, str | None]] | None = None,
    ) -> AsyncIterator[Record]:
        """Claim a key around a block, so that finishing the record cannot be forgotten.

        Python cannot make a forgotten ``finish`` a type error, so the way out
        is made safe instead: **the default is release, never leave-in-flight.**
        A record whose outcome nobody stated is an unknown outcome, and 2.8 says
        unknown means removed.

        Two executors, because the boundaries differ (see
        :mod:`hephkit.idempotency.ports`). ``claim_ex`` has no transaction open:
        it claims, and it releases. ``work_ex`` is the handler's own transaction,
        still open when the block exits, and a ``finish`` is written to it so the
        stored response and the work commit together. Open this inside that
        transaction.

        A claim that answers :class:`Replay` still enters the block, once, with
        ``record.replay`` set and nothing held; the caller returns that response.
        A claim that raises (2.5, 2.6) raises from here and the block never runs.

        On the way out:

        * clean exit after ``finish`` below 500: ``complete()`` on ``work_ex``;
        * clean exit with no ``finish``, or ``finish`` at 500 or above: release;
        * a raised ``HephError`` **below 500**, for ``kind="http"``: stored, as a 4xx the operation
          really produced (2.8), with that status and an empty body, because
          building a body is the layer above's job. This is the exception to
          "an exception releases", and the rule is the registry's status, not
          the exception type. It goes through ``claim_ex`` rather than
          ``work_ex``: the exception is about to roll the handler's transaction
          back, which would take a record written there with it and leave the
          key in flight. A 4xx has no work to keep, so committing it alone is
          right;
        * any other exception, a ``HephError`` of 500 or above, a cancellation, or
          **any** ``HephError`` when ``kind="event"``: release, and the exception
          propagates. The asymmetry is deliberate. 2.8 stores a 4xx *response* so
          a retrying *client* gets the same answer; a broker is not a client and
          has no use for a stored 422. Storing it would make the redelivery
          replay as a no-op, and the broker would ack work that never happened.
          Released, a poison event fails repeatedly and reaches the broker's own
          dead-letter queue, where an operator sees it.

        ``render_error`` turns a raised sub-500 ``HephError`` into the
        ``(body, media_type)`` that is stored with its status, so a replay returns
        what the first client got. The store still builds no response body: it
        calls a renderer the web layer handed it. It must be supplied here
        because the record is sealed at this point (``complete()`` refuses a
        second write), so nothing above can amend it later. ``None`` stores an
        empty body and no media type, which is right for an event with no HTTP
        response.

        The rule keys on the exception *type*: a 4xx ``HephError`` raised inside
        an ``ExceptionGroup`` (a handler using ``asyncio.TaskGroup``) is not
        recognised and releases. That is the conservative direction, and the
        limitation is deliberate; there is no ``except*`` arm.

        If writing the record fails, the record is released and that error
        propagates, replacing the 4xx being raised: an outcome that could not be
        recorded must not reach the client as a settled result, and the retry it
        gets from the connection or state error is the honest answer. A raised
        :class:`IdempotencyStateError` there means this attempt was superseded;
        its release is a no-op by the attempt guard.

        If ``render_error`` raises, the record is released too, and the
        renderer's exception is the one that propagates (the original
        ``HephError`` stays chained as its ``__context__``). Left unguarded it
        would escape this handler without a release and wedge the key in flight
        until the lease lapsed. The renderer runs on ``claim_ex``, between the
        claim and the store, so a renderer that does I/O does it on that
        connection.
        """
        proceed = await self.claim(
            claim_ex, scope=scope, key=key, fingerprint=fingerprint, kind=kind
        )
        if isinstance(proceed, Replay):
            yield Record(replay=proceed, taken_over=False)
            return
        record = Record(replay=None, taken_over=proceed.taken_over)
        attempt = proceed.attempt_id
        try:
            yield record
        except HephError as exc:
            if exc.status >= 500 or kind == "event":
                await self.release(claim_ex, scope=scope, key=key, attempt_id=attempt)
                raise
            try:
                body, media_type = (
                    render_error(exc) if render_error is not None else (b"", None)
                )
            except BaseException:
                # Raised inside this arm, so the arm below would not see it.
                await self.release(claim_ex, scope=scope, key=key, attempt_id=attempt)
                raise
            await self._store_or_release(
                claim_ex, claim_ex, scope, key, attempt, (exc.status, body, media_type)
            )
            raise
        except BaseException:
            await self.release(claim_ex, scope=scope, key=key, attempt_id=attempt)
            raise
        outcome = record._outcome
        if outcome is None or outcome[0] >= 500:
            await self.release(claim_ex, scope=scope, key=key, attempt_id=attempt)
            return
        await self._store_or_release(work_ex, claim_ex, scope, key, attempt, outcome)

    async def _store_or_release(
        self,
        write_ex: Executor,
        claim_ex: Executor,
        scope: str,
        key: str,
        attempt_id: str,
        outcome: tuple[int, bytes, str | None],
    ) -> None:
        status, body, media_type = outcome
        try:
            await self.complete(
                write_ex,
                scope=scope,
                key=key,
                attempt_id=attempt_id,
                status=status,
                body=body,
                media_type=media_type,
            )
        except BaseException:
            await self.release(claim_ex, scope=scope, key=key, attempt_id=attempt_id)
            raise
