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

The key is the event id. The fingerprint is ``content_hash(event)``, so the event
must be JSON-compatible. It is the 2.2 canonicaliser, so a redelivery of the same
event replays, and the same id carrying a different payload is ``HEPH-IDEMP-422``.
``scope`` comes from the application; hephkit never infers a tenant.

**A replayed event is a no-op that returns normally** (``None``). A worker must
not see an exception for a message it already handled, which would send a
successfully processed message to a dead-letter queue. A handler that raises
releases the record, so the broker's redelivery runs it again. Records are
written with ``kind="event"``; completion stores status 204 and an empty body,
because there is no response.
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
            async with (
                executors(event) as ex,
                store.idempotent_record(
                    claim_ex=ex.claim,
                    work_ex=ex.work,
                    scope=scope(event),
                    key=event_id(event),
                    fingerprint=content_hash(event),
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
