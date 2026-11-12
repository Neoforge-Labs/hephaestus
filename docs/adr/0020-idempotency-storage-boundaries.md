# 0020. Idempotency storage boundaries

## Status

Accepted. Date: 2026-11-12. Design: `docs/superpowers/specs/2026-11-11-idempotency-store-design.md`.

## Context

`spec/heph-spec.md` section 2 settles what "the client retried, do not charge twice" means, down to which error wins when a request is both in flight and carries a different body. Sections 2.1 and 2.2 — key syntax and the request fingerprint — are pure functions and already shipped. Sections 2.3 to 2.8 are a record that outlives a request: unique on `(scope, key)`, `in_flight` under a lease, then `completed` with the response to replay. That record is the first thing in the kit that has to remember anything, which makes `hephkit.idempotency` the first correctness module to need storage, and rule 6 puts it in SQL with constraints rather than in application code. ADR 0013 already fixes Postgres as the relational default.

The decisions below are therefore not local to this module. Ledger, outbox and audit are the next three correctness modules, and they will land on whatever shape this one establishes. The shape was not obvious: the implementation a reader would reach for first is wrong twice over, and in both cases every happy-path test passes while only the failure case — the case the module exists for — breaks. Two spikes, recorded in the design, found them.

**The raw driver handle is not in the caller's transaction.** The obvious way to write inside a caller's transaction is to take their SQLAlchemy connection and use the asyncpg handle underneath it (`get_raw_connection().driver_connection`). A spike wrote through both and then rolled back:

```
after rollback, rows = ['raw-rolled-back']
after commit, rows   = ['orm-committed', 'raw-committed', 'raw-rolled-back']
```

The control row written through SQLAlchemy is correctly absent, so the transaction was real; the raw write survived it. SQLAlchemy's asyncpg dialect drives transactions itself, so statements sent to the driver handle commit on their own.

**A record written inside the handler's transaction is invisible to everyone else.** The first draft of the design put the whole claim in the caller's transaction. A spike then ran two concurrent claims on one key:

```
[A] claim returned: 'in_flight'  -> proceeds
[B] claiming the same key while A is still in flight...
[A] committed after holding 2.0s
[B] unblocked after 1.89s and saw: {'state': 'completed', 'response_status': 201}
```

B was never told "in flight". It blocked for A's entire handler and then saw a `completed` record. An uncommitted row is invisible to other transactions, so 2.5's `HEPH-IDEMP-409` is unreachable, the lease protects nothing, 2.8's takeover can never fire, and the retention sweep has nothing to sweep. A single-transaction design is not an implementation of section 2; it is a design that passes its tests.

One more thing had to be measured rather than reasoned about, because the design asserted it and was wrong. It claimed that `INSERT ... ON CONFLICT DO UPDATE` rather than `DO NOTHING` is what makes two concurrent first requests serialise, by taking a row lock on the conflicting path, and it said so while instructing the builder to prove it with a concurrency test rather than by reading the manual. The test disproved it. A spike ran two connections against one key on Postgres 17.11 — A inserting and then holding its transaction open for 0.5 seconds, B inserting the same key concurrently — under both conflict actions and under both of A's outcomes:

```
DO UPDATE : A=row A_commits    | B=no row waited=0.5s B_sees='in_flight'
DO NOTHING: A=row A_commits    | B=no row waited=0.5s B_sees='in_flight'
DO UPDATE : A=row A_rolls back | B=row    waited=0.5s B_sees='in_flight'
DO NOTHING: A=row A_rolls back | B=row    waited=0.5s B_sees='in_flight'
```

B waits for exactly as long as A holds its transaction in all four rows, and then gets the right answer: no row when A committed, the key itself when A rolled back. `DO NOTHING` serialises identically, so the exclusion is not the `DO UPDATE` clause's, and the advisory lock the design held in reserve is not needed.

## Decision

**The transaction boundaries are split per operation, and a single transaction is not an option.** `claim()` runs on a connection with *no* transaction open, so each of its statements commits as it runs and the `in_flight` record is visible to the next request at once. `complete()` runs inside the caller's own transaction, so a stored response and the work it describes commit together or neither does — a replay can never describe work that was rolled back. `release()` is its own transaction again, because by then the handler's transaction has been abandoned, and a delete inside it would be abandoned with it. If the process dies mid-handler, the work rolls back and an `in_flight` record survives with its lease, which is exactly the state 2.8 describes: a genuine retry takes it over once the lease expires. The failure mode is a short delay, not a duplicated charge.

**There is one exception to "`complete()` runs in the caller's transaction", and it is the one a reimplementer will miss.** When an HTTP handler raises a `HephError` below 500, that 4xx *is* the response the client receives, so 2.8 stores it — but it is stored through the **claim** executor, not the handler's. The exception is about to roll the handler's transaction back, and a record written inside it would be rolled back with it, leaving the key `in_flight` until the lease lapsed: a client told "422, your payload is wrong" would then be told "409, still processing" for the next sixty seconds. A 4xx has no committed work for the record to describe, so committing it on its own is both safe and correct. So the boundaries are three, not two: claim and release on their own, completion with the work it describes, and a raised 4xx on its own because there is no work to tie it to.

**The serialisation of two concurrent first requests comes from the unique index, not from the `ON CONFLICT` action.** Postgres's speculative insertion makes a conflicting inserter wait for the first transaction's outcome before it conflicts, which is what the four measured rows above show happening under `DO NOTHING` and `DO UPDATE` alike. So 2.3's "exactly one proceeds" is the primary key's doing, and it is not weakened by the choice of action. `DO UPDATE` is kept for a different and real reason: it folds 2.7 into the same atomic statement. A record past retention is "treated as new", and `DO UPDATE ... WHERE` the row is past retention and no attempt holds it reuses that row — clearing the old response, replacing the fingerprint — without a second round trip and without a window in which two requests both decide the key had aged out. `DO NOTHING` would need a separate statement for that, and a rule for what happens between the two. Either way the guarantee is pinned by a concurrency test that runs two first requests at once, not by this paragraph.

**hephkit owns the SQL text, and the port is "run my statements in your transaction".** Not "give me a connection": the first finding rules that out, because a connection handed over is a connection whose transaction the lender no longer controls. `Executor` is a two-method `Protocol` — `fetch_one` and `execute`, `$1` placeholders, values only ever in parameters — and the adapters for asyncpg and SQLAlchemy are thin. The SQLAlchemy adapter goes through `conn.execute(text(...))` and never touches the raw handle. hephkit opens no connection, owns no pool and runs no background task; the one statement that must be atomic is written once, in hephkit, instead of being rewritten per project.

**The schema ships as DDL text, not as a migration.** `schema.sql` is the single copy, read into `SCHEMA_SQL`, idempotent through `IF NOT EXISTS`, and shipped in the wheel. The repo has no migration tooling, and choosing one is a larger decision than this module should make — it would bind every ingot, not just this table. Consumers run the text at startup or paste it into whatever they already use. There is no `create_schema` helper: the DDL is a multi-statement script while the port deliberately runs one parameterised statement at a time, so a helper would either bypass the port or widen it for the one case that does not need it.

**Async-only, and `READ COMMITTED` is a requirement rather than a preference.** Both adapters are async, matching the consumers. Raise the isolation level and the claim breaks in two different ways, because a row a concurrent transaction committed after the statement's snapshot was taken is simply not there. Under `REPEATABLE READ` or `SERIALIZABLE` the insert cannot ignore the row it physically collided with and raises a serialization failure (`40001`) rather than blocking, while the `SELECT ... FOR UPDATE` that reads the record a claim conflicted with can quietly find nothing, because that row is invisible to its snapshot. Nothing in the store retries a `40001`, because re-running a claim means re-running a handler, so it surfaces to the caller. The required level is Postgres's own default, so the correct configuration is the one nobody had to choose — but it is a requirement, not an assumption, and a consumer that sets a session-wide `default_transaction_isolation` has broken it.

**An attempt owns the record, and the two ends of that ownership are asymmetric on purpose.** 2.8 now says that taking over a record transfers ownership of it, so a `uuid` `attempt_id` is minted on claim, re-minted on takeover, and carried by the `Proceed` the caller got; `complete()` and `release()` match on it. When `complete()` does not own the record it raises `IdempotencyStateError`, which rolls the caller's transaction back and with it the handler's work. That is the safe direction: committing work that nothing recorded is the double-charge path, and the attempt that does own the key will do the work once. `release()` in the same situation does nothing at all. It runs on the failure path, where raising would mask the original error, and a no-op is also the correct answer — a superseded attempt's key legitimately belongs to someone else now, and deleting it would let a third request run beside the owner.

**On the event path, a raised error always releases the record.** 2.8 stores a sub-500 outcome and replays it, and on an HTTP route a raised `HephError` below 500 *is* the response the client receives, so it is stored like any other 4xx — on the claim executor, for the reason given above. An event handler answers no client. A broker is not a client and has no use for a stored 422: the record would make the next redelivery replay as a no-op, and the broker would ack work that never happened. Released, a poison event fails repeatedly and reaches the broker's own dead-letter queue, where an operator sees it. The store keys this off the record's `kind`, which also exists because a completed event record has no response to store.

**Two MUST sentences were added to the spec, which moves to `0.4.0`.** 2.7 now says a record whose `in_flight` lease has not expired MUST NOT be treated as new even once its retention has elapsed, because 2.8's takeover deliberately does not reset the creation time: without the carve-out, a record taken over near the retention boundary could be reset while its handler was still running, and two handlers would hold one key. 2.8 now says ownership transfers on takeover, and that a superseded attempt MUST NOT complete or release the record. Both forbid behaviour the spec previously left open, and a conforming implementation written against `0.3.0` could have had either bug. By the reasoning of ADR 0019 — "a minor bump because a MUST changed" — that is `0.4.0`, and every conformance vector's `spec` field moves with it.

**The module ships `experimental`** (rule 7, ADR 0015), so it may not sit in a production money path until it is `stable`. The first adopter is off the money path or in staging.

## Consequences

The caller must not wrap a claim in an outer transaction, and that cannot be detected through the port: an executor does not know what transaction it is in, and the forbidden arrangement — one pooled connection, a transaction begun, wrapped twice and handed over as both executors — type-checks, passes every single-request test, and silently disables 2.5 and 2.8. Nothing fails. The answer is to take that arrangement out of application hands: the `executors` factory, supplied once per route, owns the connection setup; the shipped factories do it correctly; and the two executors travel as a named `Executors(claim, work)` pair, so the roles cannot be swapped positionally.

The price is two pooled connections per in-flight request, one of them held while waiting for the other. A single pool therefore needs twice the route's peak concurrency, or it deadlocks at that boundary — every request holding a claim connection while waiting for a work connection nobody will release. The acquire waits are bounded, so exhaustion raises instead of hanging for good, and a separate `claim_pool` removes the deadlock entirely. This is a real operational cost of the split boundaries, and it is the thing an adopter is most likely to get wrong.

Replay is byte-exact, so the handler must return a fully built response: a framework that applies a status code and serialises a model *after* the endpoint returns leaves nothing for a decorator under the route to capture. On FastAPI that means an idempotent route returns a `Response`, and a streaming or file response is refused when the route is decorated rather than stored as empty. Only status, body and content type are stored, which is what 2.4 asks for and no more, so a replayed 201 carries no `Location` and no handler-set `ETag`.

Reading the record a claim failed to insert takes `FOR UPDATE`, which buys no mutual exclusion across statements — the lock dies with the statement's implicit transaction — but does buy a wait: a duplicate request blocks until the original's `complete()` or `release()` commits, and then gets a replay, instead of being told "retry later" and sent away. The cost is that the wait is unbounded on the hot path. A caller that needs a bound sets `lock_timeout` on its own connection; the right bound is a property of a workload, not of the statement.

Nothing sweeps the table on its own. `purge_expired()` implements 2.7 and is the consumer's to schedule, as the schema is the consumer's to create. A kit that started a background task would own a lifecycle it cannot see the end of.

2.3 to 2.8 is pinned by a Postgres contract suite rather than by new conformance vectors: a record state machine over time does not fit the vector schema's single `input`/`expect` shape, and rule 2 forbids deriving vectors from our own implementation when no RFC or reference package covers the machine. ADR 0013 independently requires a contract suite that every adapter must pass, and the two adapters here are its first two passes. So a second implementation of section 2 — in another language, or against another database — inherits the suite and these boundaries, and has to re-derive nothing but the SQL.

CI gained a real Postgres service for the Python job, and the adapter tests require it rather than skipping, so the coverage gate stays honest. `python-ci.yml` is a reusable workflow other repositories consume at `@v0`; adding a service is additive, but it is not a private file.
