-- The idempotency record table (spec section 2.3). Safe to run repeatedly.
--
-- Correctness lives in the constraints, not in application code (CLAUDE.md
-- rule 6): a row that breaks one of these is refused by the database no matter
-- which adapter wrote it.
CREATE TABLE IF NOT EXISTS heph_idempotency (
    scope               text        NOT NULL,
    key                 text        NOT NULL,
    fingerprint         text        NOT NULL,
    kind                text        NOT NULL,
    -- Which attempt holds the record (spec 2.8). Set fresh on creation and
    -- replaced on takeover, so a superseded attempt's token goes stale. The
    -- store always supplies it; the default only keeps hand-written rows valid.
    attempt_id          uuid        NOT NULL DEFAULT gen_random_uuid(),
    state               text        NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    lease_expires_at    timestamptz,
    response_status     int,
    -- bytea, not jsonb: a replay returns exactly what the client saw, with no
    -- round trip through a JSON parser.
    response_body       bytea,
    response_media_type text,
    PRIMARY KEY (scope, key),
    CHECK (kind IN ('http', 'event')),
    CHECK (state IN ('in_flight', 'completed')),
    -- An in-flight record without a lease could never be reclaimed.
    CHECK (state <> 'in_flight' OR lease_expires_at IS NOT NULL),
    -- A completed HTTP record must have something to replay.
    CHECK (NOT (state = 'completed' AND kind = 'http') OR response_status IS NOT NULL)
);

-- A table created before attempt_id existed gains it; a no-op otherwise.
ALTER TABLE heph_idempotency
    ADD COLUMN IF NOT EXISTS attempt_id uuid NOT NULL DEFAULT gen_random_uuid();

-- The retention sweep deletes by age.
CREATE INDEX IF NOT EXISTS heph_idempotency_created_at_idx
    ON heph_idempotency (created_at);
