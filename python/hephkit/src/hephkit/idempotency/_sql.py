"""SQL for the idempotency record store (spec 2.3 to 2.8).

Every statement the store runs lives here, so the SQL can be read in one place
and the module that decides with it stays about the decision.

``DDL`` is read from ``schema.sql`` rather than repeated here, so the file and
the constant cannot drift. It is idempotent (``IF NOT EXISTS``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

__all__ = ["CLAIM_INSERT", "CLAIM_READ", "CLAIM_TAKE_OVER", "DDL"]

DDL: Final = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


# --- claim() (2.3 to 2.8) ---------------------------------------------------
#
# Three statements, each of which decides something on its own, because claim
# runs them on a connection with no transaction around them: an interval is
# always a parameter (`$5::interval`), never text formatted into the statement.

# 2.3: "record creation MUST be atomic with the uniqueness check: of two
# concurrent first requests with the same (scope, key), exactly one proceeds."
# The unique index does that: the second inserter waits on the first's outcome
# and then conflicts, so a returned row means this request has the key. The
# `exactly one of two concurrent first requests` test is what pins it, and a
# spike measured `DO NOTHING` waiting the same way, so the serialisation is the
# index's rather than this clause's row lock.
#
# `DO UPDATE` rather than `DO NOTHING` so that 2.7 is part of the same atomic
# statement: a record past retention is "treated as new", and the WHERE is what
# distinguishes it from a live one. The old record's response is cleared and its
# fingerprint replaced, because this is a new record in an old row -- which is
# not 2.8's takeover, where the fingerprint is never replaced.
CLAIM_INSERT: Final = """
INSERT INTO heph_idempotency
    (scope, key, fingerprint, kind, state, created_at, lease_expires_at)
VALUES ($1, $2, $3, $4, 'in_flight', now(), now() + $5::interval)
ON CONFLICT (scope, key) DO UPDATE SET
    fingerprint         = excluded.fingerprint,
    kind                = excluded.kind,
    state               = 'in_flight',
    created_at          = excluded.created_at,
    lease_expires_at    = excluded.lease_expires_at,
    response_status     = NULL,
    response_body       = NULL,
    response_media_type = NULL
WHERE heph_idempotency.created_at < now() - $6::interval
RETURNING scope, key
"""

# The live record the insert conflicted with, for the 2.4 to 2.8 decision.
# `FOR UPDATE` waits for a concurrent transaction that holds the row -- a
# caller's complete() or release() -- so the decision is made on the record's
# settled state rather than on one that is about to change.
CLAIM_READ: Final = """
SELECT fingerprint,
       state,
       lease_expires_at <= now() AS lease_expired,
       response_status,
       response_body,
       response_media_type
FROM heph_idempotency
WHERE scope = $1 AND key = $2
FOR UPDATE
"""

# 2.8's takeover. Every condition the decision was made on is re-checked here,
# so the lease moves only if the record is still the one that was read: of two
# requests taking over the same expired lease, the second updates no row and is
# answered by 2.5 instead. The fingerprint is matched, never assigned ("the
# stored fingerprint is never replaced for the life of the record"), and
# created_at is left alone so retention keeps running from the original.
CLAIM_TAKE_OVER: Final = """
UPDATE heph_idempotency
SET lease_expires_at = now() + $4::interval
WHERE scope = $1
  AND key = $2
  AND fingerprint = $3
  AND state = 'in_flight'
  AND lease_expires_at <= now()
RETURNING scope, key
"""
