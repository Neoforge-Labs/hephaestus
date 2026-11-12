# Idempotency design: store, middleware and worker decorator

Date: 2026-11-11. Spec: `spec/heph-spec.md` section 2 (2.3–2.8).
Completes `hephkit.idempotency`, whose pure half (2.1, 2.2) already ships.

## Intent

A client that retries a payment must not be charged twice. Section 2 settles
exactly what that means, down to which error wins when a request is both in
flight and carries a different body. The kit ships the pure half — key syntax
and the request fingerprint — and nothing that remembers anything. This design
covers the half that remembers, plus the two surfaces the parent design
promises on top of it.

This is the first Phase 2 module and the first correctness module to need
storage, so the shape chosen here is the shape ledger, outbox and audit will
land on. That is why it gets a design rather than an afternoon.

## Scope

The 2026-11-04 design (source of truth, line 274) promises `hephkit.idempotency`
as "`Idempotency-Key` middleware: stores request hash and response, replays a
repeated key, rejects the same key with a different body. `@idempotent` for
workers, keyed on event id". All three ship here:

1. **The store** — 2.3–2.8, over a port with a Postgres adapter.
2. **The FastAPI integration** — `Idempotency-Key` handling for a route.
3. **`@idempotent` for workers** — the same record keyed on an event id.

## Goals

- Implement 2.3–2.8 exactly, including 2.6's precedence over 2.5.
- Keep the guarantee real under failure: a stored response and the work it
  describes must never disagree, including when the process dies mid-request.
- Make the correct use the easy one. Forgetting to finish a record must be hard.
- Give ledger, outbox and audit a storage port they can reuse.

## Non-goals

- A second database backend. ADR 0013 fixes Postgres as the relational default
  and rule 6 keeps correctness modules there. The port exists so a second one
  is *possible*, not because one is planned.
- Global middleware that makes every route idempotent. 2.1 distinguishes
  endpoints that require a key from endpoints that do not, so this is per-route.
- Migration tooling. The repo has none; see "Calls I made".
- Go, TypeScript or Rust implementations. Python is this capability's home.

## Anti-goals

- **A guarantee that holds only on the happy path.** If a crash can leave a key
  that replays work which never happened, the module is worse than nothing: it
  converts a visible failure into a silent one.
- **An API that looks right and is not.** Two spikes below; both found exactly
  this, and neither would have been caught by a passing test suite.
- **Reimplementing hashing, canonicalisation or error rendering.** Those have
  homes already.

## Constraints

- 2.3–2.8 is normative and is not being changed.
- Rule 6: correctness modules require SQL transactions and constraints.
- Rule 3: one home per capability; no hand-porting.
- Errors are registry codes only. `HEPH-IDEMP-400`, `-409` and `-422` exist with
  published pages, and `install_error_handlers` already renders `HephError` as
  problem+json, so raising is sufficient and no response-building belongs here.

## Two findings that shaped this design

### 1. The raw driver handle is not in the caller's transaction

The obvious way to run inside the caller's transaction is to take their
SQLAlchemy connection and use the asyncpg handle underneath
(`get_raw_connection().driver_connection`). It silently does not work:

```
after rollback, rows = ['raw-rolled-back']
after commit, rows   = ['orm-committed', 'raw-committed', 'raw-rolled-back']
```

The control (`orm-rolled-back`) is correctly absent, so SQLAlchemy's transaction
is real; the raw write survived it. SQLAlchemy's asyncpg dialect drives
transactions itself, so statements sent to the driver handle commit on their
own. Every happy-path test would have passed; the breakage appears only on
rollback, which is the case the module exists for.

**Consequence:** the port is not "give me an asyncpg connection". It is "give me
something that runs my statements inside your transaction", with an adapter per
driver stack.

### 2. An in-flight record written in the handler's transaction is invisible

The first draft of this design put the whole claim in the caller's transaction.
A spike ran two concurrent claims on one key:

```
[A] claim returned: 'in_flight'  -> proceeds
[B] claiming the same key while A is still in flight...
[A] committed after holding 2.0s
[B] unblocked after 1.89s and saw: {'state': 'completed', 'response_status': 201}
```

B was never told "in flight". It blocked for A's entire handler, then saw a
completed record. An uncommitted row is invisible to other transactions, so
**2.5's 409 is unreachable, the lease protects nothing, 2.8's takeover can never
fire, and the retention sweep has nothing to sweep.** A single-transaction
design is not an implementation of section 2.

**Consequence:** the transaction boundaries are split, below.

## Approaches

### The storage port

| | Approach | Trade-off |
|---|---|---|
| **A (chosen)** | hephkit owns the SQL text; a small executor port; thin adapters for asyncpg and SQLAlchemy | SQL is Postgres-flavoured, so a second database is a second set of statements |
| B | hephkit builds statements with SQLAlchemy Core | One portable code path, but every consumer takes a SQLAlchemy dependency |
| C | Port only; each consumer writes the SQL | Zero dependency, but the atomic claim, lease takeover and retention get rewritten per project |

A: the risk here is transaction scope, not SQL portability, and A puts the one
statement that must be atomic in hephkit's hands, written once. B's portability
buys little when ADR 0013 already fixes Postgres. C hands away the hard part.
Borrowing the caller's raw driver handle was eliminated by finding 1.

### The transaction boundaries

| | Approach | Trade-off |
|---|---|---|
| **Split (chosen)** | Claim commits on its own; handler work and completion share a transaction; release is its own | Three boundaries to get right, and the caller must not wrap them in one outer transaction |
| One transaction | Everything in the handler's transaction | Genuinely atomic, but 2.5, 2.7 and 2.8 become unimplementable — it stops being section 2 (finding 2) |

## What was decided

### Transaction boundaries

1. **`claim()` commits on its own.** The `in_flight` record becomes visible, so a
   concurrent duplicate gets `HEPH-IDEMP-409` immediately rather than blocking,
   and leases and takeover mean something.
2. **The handler's work and `complete()` share one transaction.** These two can
   never disagree, which is the guarantee worth having: a stored response always
   describes work that actually committed.
3. **`release()` is its own transaction.** On a 5xx or a raised handler, the
   work rolls back and the record is removed so the client can retry.

If the process dies mid-handler, the work rolls back and an `in_flight` record
survives with its lease; a genuine retry takes it over once the lease expires,
which is exactly 2.8. The failure mode is a short delay, not a lost or
duplicated charge.

hephkit never opens a connection and never owns a pool. The caller supplies an
executor per call; the context manager and the middleware enforce the order.

### The port

A `Protocol` with the few methods the statements need. Two adapters:

- **asyncpg**, behind `hephkit[postgres]`.
- **SQLAlchemy**, via `conn.execute(text(...))` — never the raw handle.

The core package keeps no database dependency.

### Outcomes

`claim()` returns `Proceed` or `Replay(status, body)` and *raises* `HephError`
for the two conflict cases, which `install_error_handlers` already renders:

| Spec | Condition | Outcome |
|---|---|---|
| 2.3 | no live record | `Proceed` (created, `in_flight`, leased) |
| 2.6 | fingerprint differs | raise `HEPH-IDEMP-422` — **whatever the state**, ahead of 2.5 |
| 2.4 | completed, fingerprint matches | `Replay(status, body)`; caller adds `Idempotent-Replayed: true` |
| 2.5 | `in_flight`, lease live, fingerprint matches | raise `HEPH-IDEMP-409` |
| 2.8 | `in_flight`, lease expired, fingerprint matches | `Proceed` (taken over, new lease) |
| 2.7 | record older than retention | treated as new → `Proceed` |

### The claim algorithm

1. `INSERT ... ON CONFLICT (scope, key) DO UPDATE ... WHERE <row is past
   retention> RETURNING` — a returned row means the key was free or had aged
   out: proceed.
2. Otherwise `SELECT ... FOR UPDATE` and decide by the table above, updating the
   lease on takeover.

`DO UPDATE` rather than `DO NOTHING` so the conflicting path takes a row lock
and two concurrent first requests serialise. **This must be proven by a
concurrency test, not by reading the manual.** Fallback: an advisory lock on
`hash(scope, key)`.

> **Settled 2026-11-12, ADR 0020.** The concurrency test was written and it
> disproved this paragraph. A conflicting insert waits for the first
> transaction's outcome under `DO NOTHING` and `DO UPDATE` alike, so the
> serialisation 2.3 demands is the unique index's speculative-insertion wait and
> not this clause's row lock. `DO UPDATE` was kept for a different reason — it
> folds 2.7's aged-out reuse into the same atomic statement — and no advisory
> lock was needed. The measurement is quoted in the ADR.

### Storage

One table, `heph_idempotency`, primary key `(scope, key)`: fingerprint, kind,
state, created_at, lease_expires_at, response_status, response_body. Rule 6 asks
for constraints, so `CHECK`s on the state and kind values, a `CHECK` that a
completed HTTP record has a response status, and a `CHECK` that an in-flight
record has a lease. An index on `created_at` serves the retention sweep.

Retention and lease are configuration with the spec's 24h and 60s defaults, and
retention may only be lengthened (2.7). A `purge_expired()` function is provided
for the consumer to schedule; nothing here runs a background task.

## Calls I made

Stated as mine, not agreed in conversation.

- **`scope` is a required explicit argument.** hephkit will not infer a tenant.
  2.3 says it is the authenticated principal's tenant and never a
  client-supplied field, and `auth` does not exist yet to supply it. A
  convenience that guessed would be this module's worst bug.
- **hephkit ships the DDL** as a function and an equivalent `.sql` file. The repo
  has no Atlas tooling and no migrations directory; inventing a migration system
  is a larger decision than this module should make.
- **`READ COMMITTED` is required for the claim.** Under `REPEATABLE READ` or
  `SERIALIZABLE`, `ON CONFLICT` and `FOR UPDATE` against a concurrently
  committed row raise `40001` instead of blocking. The adapter does not retry:
  re-running the claim would mean re-running the handler. A serialization
  failure surfaces to the caller, and the documented requirement is the
  default isolation level.
- **2.3–2.8 is pinned by a Postgres contract suite, not new conformance
  vectors.** CLAUDE.md allows "vectors **or** contract tests"; a record state
  machine over time does not fit the vector schema's single `input`/`expect`
  shape; and rule 2 forbids deriving vectors from our own implementation, with
  no RFC or reference package covering this machine. ADR 0013 independently
  requires a contract suite every adapter must pass. The two adapters are that
  suite's first two passes.
- **An ADR ships with the implementation**, covering the split transaction
  boundaries, hephkit owning the SQL, DDL instead of migrations, and async-only.
  These outlive the module.
- **CI gets a real Postgres.** `python-ci.yml` gains a `services: postgres`, and
  the adapter tests require it rather than skipping, so the 90% coverage gate
  stays honest. Flagged because `python-ci.yml` is a reusable workflow other
  repos consume at `@v0`: adding a service is additive, but it is not a private
  file.
- **Telemetry is the integration's job, not the store's.** 2.1 notes the key is
  recorded as `idempotency.key`; the middleware and the decorator set it, so the
  core keeps no OpenTelemetry dependency.
- **Async-only.** Both adapters are async, matching FastAPI and Collie.
- **Ships `experimental`** (rule 7, ADR 0015), which means it may not sit in a
  production money path until `stable`. The first adopter must therefore be
  off the money path or in staging. Reaching `beta`/`stable` is not in scope.

### For the worker path, which has no HTTP request

- **The key is the event id; the fingerprint is the content hash of the event
  payload**, via the existing `hephkit.hashing.content_hash`. Redelivery of the
  same event replays; the same event id carrying a different payload is
  `HEPH-IDEMP-422`, which is the same protection 2.6 gives HTTP.
- **A `kind` column distinguishes `http` from `event` records**, because an event
  has no response to store and the completed-record constraint differs.

### For the middleware

- **Per-route opt-in**, not global, following 2.1's distinction.
- **A streaming response is refused at setup**, not silently stored as empty. A
  route whose response cannot be captured cannot be replayed, and failing loudly
  at wiring time is better than a key that replays nothing.

## Left to the builder

- The exact ergonomics of the context manager, subject to one constraint:
  forgetting to finish a record must be impossible.
- The Protocol's method set — the smallest the statements need, including how
  the parameter-style difference between asyncpg (`$1`) and SQLAlchemy `text()`
  (`:name`) is absorbed.
- Whether `response_body` is `bytea` or `jsonb`. Bytes replay verbatim, which
  reads safer.
- Whether the SQLAlchemy adapter ships in `hephkit[postgres]` or its own extra.
- Test strategy beyond the requirement that 2.3's "exactly one proceeds" is
  proven with genuinely concurrent transactions against a real Postgres.

## Open, and deliberately not settled here

Where `scope` comes from once `auth` exists. This design takes it as a
parameter; when `auth` lands with a spec section, a follow-up should decide
whether hephkit offers a resolver rather than every consumer re-deriving the
tenant. That is an ADR, not a detail.
