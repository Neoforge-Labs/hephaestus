"""``idempotent``: the record of 2.3 to 2.8, keyed on an event id instead of an HTTP request. Maturity: experimental.

The second consumer of ``IdempotencyStore.idempotent_record``, and the simpler
one. It wraps a message handler for a broker that delivers at least once::

    @idempotent(store, scope=tenant_of, event_id=lambda e: e["id"], executors=db_executors)
    async def handle(event: dict[str, Any]) -> None: ...

The decorated handler is called with the event as its first positional
argument; ``scope``, ``event_id`` and ``executors`` each receive that event.
``executors`` has the same shape and the same obligations as for
``hephkit.idempotency.fastapi.idempotent_route`` (see its module docstring):
``Executors(claim, work)``, with ``claim`` on a connection with no transaction
open and ``work`` on the handler's own transaction.
``hephkit.idempotency.adapters.asyncpg_event_executors(pool)`` builds one
correctly; use it unless you have a reason not to. It is the route factory for
this path, and it hands the handler its own connection through
``asyncpg_event_work_connection()`` rather than ``request.state``, which an
event has none of. **Write through that connection**, or the work and the record
no longer commit together.

The key is the event id. The fingerprint is ``content_hash(event)``, so the event
must be JSON-compatible. It is the 2.2 canonicaliser, so a redelivery of the same
event replays, and the same id carrying a different payload is ``HEPH-IDEMP-422``.
``scope`` comes from the application; hephkit never infers a tenant.

**A replayed event is a no-op that returns normally** (``None``). A worker must
not see an exception for a message it already handled, which would send a
successfully processed message to a dead-letter queue. A handler that raises
releases the record, so the broker's redelivery runs it again, **including a
sub-500 ``HephError``**. An HTTP route stores a 4xx (2.8) so a retrying client
gets the same answer; a broker is not a client, and a stored 4xx would make the
redelivery a no-op that acks work never done. A poison event instead fails
repeatedly and reaches the broker's own dead-letter queue, where an operator sees
it. The store keys this off ``kind="event"``.

A concurrent duplicate delivery of an event still in flight raises
``HEPH-IDEMP-409``; it is the broker's to retry. An event that is not
JSON-compatible raises from ``content_hash`` before any connection is opened.

Records are written with ``kind="event"``; completion stores status 204 and an
empty body, because there is no response. That is also why nothing here catches
``RecordReleased``: an event handler that returns states 204, never a status of
500 or above and never no outcome at all, so the store's two release-on-a-clean-
exit paths are unreachable from this decorator. A handler that fails raises, and
the exception rolls the work back on its way out, as it does on a route.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from hephkit.hashing import content_hash
from hephkit.idempotency.ports import Executors
from hephkit.idempotency.store import IdempotencyStore

__all__ = ["idempotent"]

Handler = Callable[..., Awaitable[Any]]


def idempotent(
    store: IdempotencyStore,
    *,
    scope: Callable[[Any], str],
    event_id: Callable[[Any], str],
    executors: Callable[[Any], AbstractAsyncContextManager[Executors]],
) -> Callable[[Handler], Handler]:
    """Make an event handler idempotent on its event id."""

    def decorate(handler: Handler) -> Handler:
        @functools.wraps(handler)
        async def wrapper(event: Any, *args: Any, **kwargs: Any) -> Any:
            fp = content_hash(event)  # before any connection or transaction is opened
            async with (
                executors(event) as ex,
                store.idempotent_record(
                    claim_ex=ex.claim,
                    work_ex=ex.work,
                    scope=scope(event),
                    key=event_id(event),
                    fingerprint=fp,
                    kind="event",
                ) as record,
            ):
                if record.replay is not None:
                    return None
                result = await handler(event, *args, **kwargs)
                record.finish(204, b"")
                return result

        return wrapper

    return decorate
