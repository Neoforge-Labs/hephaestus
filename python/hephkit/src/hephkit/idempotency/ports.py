"""The port the idempotency store runs its SQL through, and what a claim answers.

This module imports no driver, so ``hephkit.idempotency`` stays dependency-free.
hephkit never opens a connection, owns a pool or runs a background task: the
caller hands the store an executor over a connection the caller owns.

**The transaction boundary differs per call, and the two are not
interchangeable** (design findings 1 and 2):

* ``claim()`` takes an executor on a connection with **no outer transaction**,
  so its statements commit as they run. A record that is still invisible
  protects nothing: 2.5's 409, the lease and 2.8's takeover all need the record
  to be readable by the next request.
* ``complete()`` takes an executor on a connection the caller **has a
  transaction open on**, so a stored response and the work it describes commit
  together, or neither does.
* ``release()`` takes one with **no outer transaction**, like ``claim()``: the
  handler's transaction has been abandoned, and a release inside it would be
  abandoned too.

Whichever it is, the store never begins, commits or rolls back a transaction itself:
there is nothing on this port that could, which is deliberate, because a
connection's transaction state belongs to whoever owns the connection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = ["Executor", "Proceed", "Replay"]


@dataclass(frozen=True)
class Proceed:
    """The caller runs the operation: no live record stood in the way.

    ``taken_over`` is false for a key that was free or had aged out (2.3, 2.7)
    and true when this request took over an ``in_flight`` record whose lease had
    expired (2.8). The operation runs either way; the flag is there for the
    caller's telemetry, because a takeover means an earlier attempt's outcome is
    unknown.
    """

    taken_over: bool


@dataclass(frozen=True)
class Replay:
    """The stored response of a completed record (2.4): do not run the operation.

    The caller returns this status and body and adds ``Idempotent-Replayed:
    true``. ``body`` is the exact bytes that were stored, empty for a response
    that had none, and ``media_type`` is ``None`` when none was recorded.

    Only an HTTP record carries a response: the table requires a status on a
    completed ``http`` record, while a completed ``event`` record has none. A
    caller claiming with ``kind="event"`` therefore reads a ``Replay`` as "this
    one is already handled" and takes nothing off it.
    """

    status: int
    body: bytes
    media_type: str | None


class Executor(Protocol):
    """Runs one statement on the caller's connection, in whatever transaction it is in.

    ``sql`` is always written with ``$1``-style placeholders, asyncpg's native
    form, and values travel only in ``params``. No caller formats a value into
    a statement. An adapter for a driver with another placeholder style
    rewrites the statement, never the values.
    """

    async def fetch_one(self, sql: str, params: Sequence[Any]) -> Mapping[str, Any] | None:
        """The first row as a mapping, or ``None`` when there is none."""
        ...

    async def execute(self, sql: str, params: Sequence[Any]) -> int:
        """Run an INSERT, UPDATE or DELETE and return the number of rows it affected.

        DML only. On a SELECT the adapters disagree (asyncpg's status yields the
        row count, SQLAlchemy's ``rowcount`` is typically -1); use ``fetch_one``.
        """
        ...
