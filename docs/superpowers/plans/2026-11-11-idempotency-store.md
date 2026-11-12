# Idempotency store, middleware and worker decorator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `hephkit.idempotency` — the record store of spec 2.3–2.8, the FastAPI route integration that drives it from an `Idempotency-Key` header, and `@idempotent` for workers keyed on an event id.

**Architecture:** Three layers, bottom-up. A tiny `Executor` Protocol that runs hephkit's own SQL inside *the caller's* transaction, with an adapter per driver stack (asyncpg, SQLAlchemy) — never the raw driver handle, which does not join the caller's transaction. On top of it a store with three separately-committed phases: `claim()` commits alone so the `in_flight` row is visible to concurrent requests, the handler's work and `complete()` share one transaction so a stored response always describes work that committed, and `release()` is its own. On top of that, two consumers: a per-route FastAPI integration and a worker decorator, which share the store and differ only in how they derive the key and the fingerprint.

**Tech Stack:** Python 3.12, async only. `asyncpg` and `SQLAlchemy[asyncio]` behind extras; PostgreSQL (real, in CI) for the contract suite; pytest with `pytest-asyncio`; FastAPI for the route integration; the existing `hephkit.hashing`, `hephkit.errors` and `hephkit.conventions`.

**Spec:** `docs/superpowers/specs/2026-11-11-idempotency-store-design.md` (approved 2026-11-11), implementing `spec/heph-spec.md` §2.3–2.8.

**Branch:** a fresh `work/idempotency-store`, per CLAUDE.md.

## Global Constraints

- Conventional Commits. Branches `work/<topic>`. **No AI attribution** in commit messages, PR bodies or branch names.
- Error codes live only in `spec/errors.yaml` and match `^HEPH-[A-Z]{2,6}-\d{3}$`. This plan adds **no new code**: `HEPH-IDEMP-400`, `HEPH-IDEMP-409`, `HEPH-IDEMP-422` and `HEPH-VAL-422` all exist. Raising `HephError` is sufficient — `install_error_handlers` already renders problem+json. **No task builds an error response body.**
- Rule 3: Python is this capability's home — no Go, TypeScript or Rust port. Nothing in this plan touches `core/`.
- Rule 6: this is a correctness module. Every state transition goes through SQL with constraints; no in-memory store ships, not even for tests.
- Rule 7: ships `maturity: experimental`, with `Maturity: experimental.` in every new module's docstring (`tools/check_modules.py` holds the two equal). `spec/modules.yaml` already records `idempotency` as `shipped`/`experimental` — **do not edit it**; the docs page and `site-data.json` are regenerated instead (Task 8).
- Hephkit never opens a connection, never owns a pool, and never runs a background task. The caller supplies an executor per call.
- `scope` is always an explicit argument. Never inferred, never read from a header or body field (2.3).
- Spec defaults, exact: retention **24 hours** from creation, lease **60 seconds**. Retention may only be configured *longer* (2.7); the lease is configurable in either direction.
- The claim requires `READ COMMITTED`. No adapter retries a `40001`: re-running a claim means re-running a handler. It surfaces to the caller.
- Telemetry belongs to the consumers, not the store: the store imports no OpenTelemetry. The attribute name is `hephkit.conventions.IDEMPOTENCY_KEY` (`"idempotency.key"`) — never a string literal.
- Local Postgres for tests is `heph dev up` → `postgresql://heph:heph@localhost:54320/heph`. CI uses a `services: postgres` on 5432. Both come from `HEPH_TEST_DATABASE_URL`, defaulting to the local-stack DSN.

## Review Focus

Five failure modes §2 implies that no task's obvious tests would reach. Each line's test is added to the task that owns the code.

1. **A key containing `:` or `%`** — both are VCHAR and so valid under 2.1. SQLAlchemy `text()` binds `:name`, and `%` is a format character in several drivers. A key is a *value*, never interpolated. (Task 2)
2. **A 4xx outcome is stored and replayed, not released** — 2.8 says so explicitly, and it is equally true when the handler *raises* a sub-500 `HephError` rather than returning one. `except Exception: release` loses this. (Task 5)
3. **Replay returns the stored body byte-for-byte**, with its original status and content type. Re-serialising JSON on the way out changes bytes the client already saw. (Task 6)
4. **Retention configured shorter than 24h is refused at construction.** 2.7 permits *longer* only; silently accepting a shorter value weakens the guarantee with no error anywhere. (Task 4)
5. **`scope=""` is a real scope, not "no scope".** Two untenanted principals sharing a key must collide as 2.3 requires, and `None` must not be silently coerced to `""`. (Task 3)

---

## File Structure

| File | Responsibility |
| --- | --- |
| `python/hephkit/src/hephkit/idempotency/__init__.py` | Public surface. Keeps 2.1/2.2 as they are; re-exports the store names. Docstring stops saying 2.3–2.8 are absent. |
| `python/hephkit/src/hephkit/idempotency/_sql.py` | Every SQL string, and the DDL constant. No logic. |
| `python/hephkit/src/hephkit/idempotency/schema.sql` | The DDL as a file, for consumers with their own migration tool. |
| `python/hephkit/src/hephkit/idempotency/ports.py` | The `Executor` Protocol and the outcome types. No driver import. |
| `python/hephkit/src/hephkit/idempotency/adapters.py` | `AsyncpgExecutor`, `SQLAlchemyExecutor`. The only file that imports a driver. |
| `python/hephkit/src/hephkit/idempotency/store.py` | `IdempotencyStore`: `claim`, `complete`, `release`, `purge_expired`, and the `idempotent_record` context manager. **No `create_schema`:** the DDL is a multi-statement script and the `Executor` port runs one parameterised statement at a time, so the schema is published as text (`SCHEMA_SQL`, the contents of `schema.sql`) for the caller to run on its own connection or paste into its own migration. |
| `python/hephkit/src/hephkit/idempotency/fastapi.py` | Per-route integration. The only file importing FastAPI or OpenTelemetry. |
| `python/hephkit/src/hephkit/idempotency/worker.py` | `@idempotent` for event handlers. |
| `python/hephkit/tests/conftest.py` | The Postgres fixtures and the adapter parametrisation. |
| `python/hephkit/tests/test_idempotency_store.py` | The contract suite: 2.3–2.8 against a real Postgres, run once per adapter. |
| `python/hephkit/tests/test_idempotency_fastapi.py` | Route integration. |
| `python/hephkit/tests/test_idempotency_worker.py` | Decorator. |
| `python/hephkit/pyproject.toml` | The `postgres` and `sqlalchemy` extras; `pytest-asyncio` in the dev group. |
| `.github/workflows/python-ci.yml` | `services: postgres` for the `python` job. |
| `docs/adr/0020-idempotency-storage-boundaries.md` | The decisions that outlive the module. |
| `docs/site/content/modules/idempotency.mdx` | The docs page with a runnable example (CLAUDE.md requires one per module). |

Task 1 lands the table and the harness; 2 the port; 3–5 the store; 6–7 the two consumers; 8 the record.

---

### Task 1: The table, the DDL and a real Postgres in CI

**Files:**
- Create: `python/hephkit/src/hephkit/idempotency/_sql.py`, `python/hephkit/src/hephkit/idempotency/schema.sql`
- Create: `python/hephkit/tests/conftest.py`
- Modify: `python/hephkit/pyproject.toml` (the `postgres` and `sqlalchemy` extras; `asyncpg`, `sqlalchemy[asyncio]`, `pytest-asyncio` in the dev group)
- Modify: `.github/workflows/python-ci.yml` (the `python` job gains `services: postgres`)
- Test: `python/hephkit/tests/test_idempotency_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_sql.DDL: str` (the `CREATE TABLE` plus index, idempotent via `IF NOT EXISTS`); a session-scoped `postgres_dsn` fixture reading `HEPH_TEST_DATABASE_URL` and defaulting to `postgresql://heph:heph@localhost:54320/heph`; a function-scoped `clean_table` fixture truncating `heph_idempotency`.

The table, exactly: primary key `(scope text NOT NULL, key text NOT NULL)`; `fingerprint text NOT NULL`; `kind text NOT NULL`; `state text NOT NULL`; `created_at timestamptz NOT NULL DEFAULT now()`; `lease_expires_at timestamptz`; `response_status int`; `response_body bytea`; `response_media_type text`. The constraints rule 6 asks for: `CHECK (kind IN ('http','event'))`, `CHECK (state IN ('in_flight','completed'))`, `CHECK (state <> 'in_flight' OR lease_expires_at IS NOT NULL)`, `CHECK (NOT (state = 'completed' AND kind = 'http') OR response_status IS NOT NULL)`. Index `heph_idempotency_created_at_idx` on `(created_at)` for the retention sweep.

`response_body` is `bytea`: a replay must return what the client saw, and bytes do that without a round trip through a JSON parser.

- [ ] **Step 1: Write the failing tests**

```python
async def test_ddl_creates_a_table_with_the_section_2_columns(pg_conn):
    await pg_conn.execute(_sql.DDL)
    cols = {r["column_name"]: r["data_type"] for r in await pg_conn.fetch(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'heph_idempotency'")}
    assert cols["scope"] == "text" and cols["key"] == "text"
    assert cols["fingerprint"] == "text" and cols["kind"] == "text"
    assert cols["state"] == "text"
    assert cols["created_at"] == "timestamp with time zone"
    assert cols["lease_expires_at"] == "timestamp with time zone"
    assert cols["response_status"] == "integer"
    assert cols["response_body"] == "bytea"


async def test_an_in_flight_row_without_a_lease_is_refused(pg_conn):
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pg_conn.execute(
            "INSERT INTO heph_idempotency (scope, key, fingerprint, kind, state) "
            "VALUES ('', 'k', 'sha256:x', 'http', 'in_flight')")


def test_the_ddl_file_and_the_constant_are_the_same_sql():
    ...  # whitespace-normalised equality; two copies of DDL is what drifts
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_store.py -v`
Expected: FAIL — `hephkit.idempotency._sql` does not exist. (`heph dev up` first if Postgres is not running.)

- [ ] **Step 3: Write `schema.sql`, and `_sql.py` that reads it**

`DDL` is `(Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")`. One copy, not two, so the drift test passes by construction. Add `"*.sql"` to the wheel's package data so the file ships.

- [ ] **Step 4: Add the extras and the CI service**

`[project.optional-dependencies]`: `postgres = ["asyncpg>=0.30"]`, `sqlalchemy = ["sqlalchemy[asyncio]>=2.0"]`. The dev group gains `asyncpg`, `sqlalchemy[asyncio]`, `pytest-asyncio>=0.24`; `[tool.pytest.ini_options]` gains `asyncio_mode = "auto"`.

In `python-ci.yml`, the `python` job gains:

```yaml
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_USER: heph
          POSTGRES_PASSWORD: heph
          POSTGRES_DB: heph
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready --health-interval 5s
          --health-timeout 5s --health-retries 10
```

and `HEPH_TEST_DATABASE_URL: postgresql://heph:heph@localhost:5432/heph` in the job `env`. The adapter tests **require** Postgres rather than skipping: a skipped test still counts against the 90% coverage gate, and these are the paths the module exists for.

This file is a reusable workflow other repos consume at `@v0`. Adding a service is additive, but say so in the commit message.

- [ ] **Step 5: Run the tests and the repo checks**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_store.py -v`
Then: `cd ../.. && uv run --with pytest --with pyyaml --with jsonschema --with rfc8785==0.1.4 pytest tools/tests -q`
Expected: PASS, and the tool tests still green.

- [ ] **Step 6: Commit**

```bash
git add python/hephkit/src/hephkit/idempotency/_sql.py python/hephkit/src/hephkit/idempotency/schema.sql python/hephkit/tests/conftest.py python/hephkit/tests/test_idempotency_store.py python/hephkit/pyproject.toml .github/workflows/python-ci.yml
git commit -m "feat(idempotency): the record table, its constraints and a real Postgres in CI"
```

---

### Task 2: The executor port and the two adapters

**Files:**
- Create: `python/hephkit/src/hephkit/idempotency/ports.py`, `python/hephkit/src/hephkit/idempotency/adapters.py`
- Test: `python/hephkit/tests/test_idempotency_store.py` (adds the transaction-scope contract)

**Interfaces:**
- Consumes: `_sql.DDL`.
- Produces:
  ```python
  class Executor(Protocol):
      async def fetch_one(self, sql: str, params: Sequence[Any]) -> Mapping[str, Any] | None: ...
      async def execute(self, sql: str, params: Sequence[Any]) -> int: ...
  ```
  `sql` is always written with `$1`-style placeholders — asyncpg's native form. `SQLAlchemyExecutor` rewrites those to `:p1`-style bind parameters itself; **no caller ever formats a value into a statement.** `AsyncpgExecutor(conn)` and `SQLAlchemyExecutor(conn)` each take an object the caller already has a transaction open on. An `adapter` fixture in `conftest.py` parametrises every store test over both.

- [ ] **Step 1: Write the failing tests — the contract both adapters must pass**

This is finding 1 of the design, pinned as a test. It is the reason the port exists at all.

```python
async def test_a_rolled_back_transaction_takes_the_executors_writes_with_it(adapter):
    async with adapter.transaction() as ex:
        await ex.execute(INSERT_SQL, ["", "rolled-back", "sha256:x"])
        await adapter.rollback()
    assert await adapter.count_keys() == 0


async def test_a_committed_transaction_keeps_them(adapter):
    ...


async def test_a_key_containing_a_colon_and_a_percent_is_a_value_not_a_template(adapter):
    key = "urn:uuid:7b%2Dff:name"        # every character is VCHAR, so 2.1 allows it
    async with adapter.transaction() as ex:
        await ex.execute(INSERT_SQL, ["", key, "sha256:x"])
    assert (await adapter.fetch_key("", key))["key"] == key
```

The third is Review Focus 1. `:name` is SQLAlchemy's own bind syntax; if the rewrite touches parameter *values* rather than only the statement, this key is mangled or the statement fails to compile.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_store.py -k "transaction or colon" -v`
Expected: FAIL — `hephkit.idempotency.ports` does not exist.

- [ ] **Step 3: Implement `ports.Executor` and both adapters**

`ports.py` imports no driver, so `hephkit.idempotency` stays dependency-free. `adapters.py` imports asyncpg and SQLAlchemy lazily inside each class and raises `ImportError` naming the extra (`pip install "hephkit[postgres]"`) when one is missing — the pattern `hephkit.settings` already uses.

`SQLAlchemyExecutor` uses `conn.execute(text(...))` — **never** `get_raw_connection().driver_connection`, which does not join the caller's transaction. Put that sentence in the class docstring with a pointer to the design's finding 1; it is the single most expensive thing here to rediscover.

The `$1` → `:p1` rewrite is a regex over the statement only, with the params zipped into a dict. Statements are hephkit's own constants, so no untrusted text reaches the rewrite.

- [ ] **Step 4: Run and confirm green on both adapters**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_store.py -v`
Expected: PASS, each test twice (once per adapter).

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(idempotency): an executor port with asyncpg and SQLAlchemy adapters"
```

---

### Task 3: `claim()` — 2.3–2.8's decision table

**Files:**
- Create: `python/hephkit/src/hephkit/idempotency/store.py`
- Modify: `python/hephkit/src/hephkit/idempotency/ports.py` (the outcome types), `_sql.py`
- Test: `python/hephkit/tests/test_idempotency_store.py`

**Interfaces:**
- Consumes: `Executor`, `_sql`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class Proceed:
      taken_over: bool

  @dataclass(frozen=True)
  class Replay:
      status: int
      body: bytes
      media_type: str | None

  class IdempotencyStore:
      def __init__(self, *, retention: timedelta = timedelta(hours=24),
                   lease: timedelta = timedelta(seconds=60)) -> None: ...
      async def claim(self, ex: Executor, *, scope: str, key: str,
                      fingerprint: str, kind: Literal["http", "event"] = "http",
                      ) -> Proceed | Replay: ...
  ```
  `claim` **commits on its own** — the caller passes an executor on a connection with no outer transaction, and the store opens and commits one. Say that in the docstring's first line.

The decision table, from the design:

| Spec | Condition | Outcome |
|---|---|---|
| 2.3 | no live record | `Proceed(taken_over=False)` |
| 2.6 | fingerprint differs | raise `HephError("HEPH-IDEMP-422", ...)` — **whatever the state**, ahead of 2.5 |
| 2.4 | `completed`, fingerprint matches | `Replay(status, body, media_type)` |
| 2.5 | `in_flight`, lease live, fingerprint matches | raise `HephError("HEPH-IDEMP-409", ...)` |
| 2.8 | `in_flight`, lease expired, fingerprint matches | `Proceed(taken_over=True)`, new lease |
| 2.7 | record older than retention | treated as new → `Proceed(taken_over=False)` |

The algorithm: `INSERT ... ON CONFLICT (scope, key) DO UPDATE SET ... WHERE heph_idempotency.created_at < now() - $retention RETURNING *` — a returned row means the key was free or had aged out. `DO UPDATE` rather than `DO NOTHING` **because the conflicting path must take a row lock** so two concurrent first requests serialise. Otherwise `SELECT ... FOR UPDATE` and decide by the table, `UPDATE`-ing the lease on takeover. The stored fingerprint is **never** replaced (2.8's last sentence).

- [ ] **Step 1: Write the failing tests — one per row, then the three that matter most**

Six cases from the table, each asserting the outcome type or `exc.value.code`. Then:

```python
async def test_exactly_one_of_two_concurrent_first_requests_proceeds(adapter):
    """Spec 2.3. Two genuinely concurrent transactions, not two awaits on one."""
    outcomes = await asyncio.gather(
        claim_on_its_own_connection(scope="", key="k", fingerprint=FP),
        claim_on_its_own_connection(scope="", key="k", fingerprint=FP),
        return_exceptions=True)
    assert len([o for o in outcomes if isinstance(o, Proceed)]) == 1
    assert [o.code for o in outcomes if isinstance(o, HephError)] == ["HEPH-IDEMP-409"]


async def test_a_mismatched_fingerprint_beats_a_live_lease(adapter):
    """Spec 2.6 takes precedence over 2.5: a client bug, not a retry-later."""
    assert exc.value.code == "HEPH-IDEMP-422"


async def test_the_empty_scope_is_a_scope(adapter):
    """Review Focus 5. Two untenanted principals sharing a key still collide."""
    assert isinstance(await claim(scope="", key="k", fingerprint=FP), Proceed)
    with pytest.raises(HephError) as exc:
        await claim_on_another_connection(scope="", key="k", fingerprint=FP)
    assert exc.value.code == "HEPH-IDEMP-409"
    assert isinstance(await claim(scope="t1", key="k", fingerprint=FP), Proceed)


async def test_scope_none_is_a_type_error_not_an_empty_scope(adapter):
    ...
```

The concurrency test must use **two separate connections**, each in its own transaction, gathered. Two sequential awaits on one connection prove nothing — the design's finding 2 is exactly that mistake. If `ON CONFLICT DO UPDATE ... WHERE false` turns out not to take the lock, fall back to `pg_advisory_xact_lock(hashtext(scope || key))` before the insert, and keep this test as the thing that decides.

- [ ] **Step 2: Run and watch them fail**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_store.py -k claim -v`
Expected: FAIL — `IdempotencyStore` is not defined.

- [ ] **Step 3: Implement `IdempotencyStore.claim`**

Order the branches as the table orders them: mismatch first, then state. Writing it state-first and checking the fingerprint inside each branch is how 2.6's precedence gets lost. Retention and lease reach SQL as interval parameters, never as formatted strings.

- [ ] **Step 4: Run every claim test on both adapters**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_store.py -v`
Expected: PASS. Run the concurrency test 20 times in a loop before believing it.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(idempotency): claim a key, with 2.6 ahead of 2.5 and a proven atomic insert"
```

---

### Task 4: `complete()`, `release()`, `purge_expired()` and the retention floor

**Files:**
- Modify: `python/hephkit/src/hephkit/idempotency/store.py`, `_sql.py`
- Test: `python/hephkit/tests/test_idempotency_store.py`

**Interfaces:**
- Consumes: Task 3's `IdempotencyStore`.
- Produces:
  ```python
  async def complete(self, ex: Executor, *, scope: str, key: str,
                     status: int, body: bytes, media_type: str | None = None) -> None: ...
  async def release(self, ex: Executor, *, scope: str, key: str) -> None: ...
  async def purge_expired(self, ex: Executor) -> int: ...   # rows removed
  ```
  `complete` runs in **the caller's** transaction — the handler's work and the record move together or not at all. `release` runs in its own. `purge_expired` deletes rows past retention and returns the count; it is for the consumer to schedule, and hephkit starts nothing.

`__init__` raises `ValueError` when `retention < timedelta(hours=24)`: 2.7 permits longer only.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_4xx_is_stored_and_replayed_like_any_other_outcome(adapter):
    """Spec 2.8: 4xx responses are real outcomes of the operation."""
    await store.complete(ex, scope="", key="k", status=422, body=b'{"detail":"no"}')
    assert await store.claim(ex2, scope="", key="k", fingerprint=FP) == Replay(
        422, b'{"detail":"no"}', None)


async def test_a_500_releases_the_record_so_the_client_can_retry(adapter):
    await store.release(ex, scope="", key="k")
    assert isinstance(await store.claim(ex2, scope="", key="k", fingerprint=FP), Proceed)


async def test_completing_in_the_callers_transaction_rolls_back_with_it(adapter):
    """The guarantee worth having: a stored response describes committed work."""
    async with adapter.transaction() as ex:
        await store.complete(ex, scope="", key="k", status=201, body=b"{}")
        await adapter.rollback()
    assert (await adapter.fetch_key("", "k"))["state"] == "in_flight"


def test_retention_shorter_than_24_hours_is_refused():
    """Review Focus 4. Spec 2.7 permits longer only."""
    with pytest.raises(ValueError, match="24"):
        IdempotencyStore(retention=timedelta(hours=1))
    IdempotencyStore(retention=timedelta(days=30))      # longer is fine


async def test_purge_expired_removes_only_rows_past_retention(adapter):
    ...
```

The third test is the one that would have caught the design's finding 1 had the adapter been wrong.

- [ ] **Step 2: Run and watch them fail**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_store.py -k "complete or release or purge or retention" -v`
Expected: FAIL — `complete` is not defined.

- [ ] **Step 3: Implement the three methods and the retention floor**

- [ ] **Step 4: Run the full store suite**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_store.py -v`
Expected: PASS on both adapters.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(idempotency): complete, release and the retention sweep"
```

---

### Task 5: `idempotent_record()` — making it impossible to forget to finish

**Files:**
- Modify: `python/hephkit/src/hephkit/idempotency/store.py`
- Test: `python/hephkit/tests/test_idempotency_store.py`

**Interfaces:**
- Consumes: `claim`, `complete`, `release`.
- Produces:
  ```python
  class Record:
      replay: Replay | None        # not None means the body did not run
      taken_over: bool
      def finish(self, status: int, body: bytes, media_type: str | None = None) -> None: ...

  @asynccontextmanager
  async def idempotent_record(self, *, claim_ex: Executor, work_ex: Executor,
                              scope: str, key: str, fingerprint: str,
                              kind: Literal["http", "event"] = "http",
                              ) -> AsyncIterator[Record]: ...
  ```
  Two executors because the boundaries differ: `claim_ex` commits alone, `work_ex` is the handler's own transaction. When `claim` returns a `Replay` the block still runs once, with `record.replay` set — the caller checks it and returns the stored response instead of doing the work. `finish` records the outcome; the write to `work_ex` happens on a clean exit. A block that exits without a `finish` **releases**, because a record whose outcome nobody stated is an unknown outcome, and 2.8 says unknown means removed.

This is the design's one named ergonomic constraint: forgetting to finish must be impossible. Python cannot make it a type error, so it is made *safe* instead — the default on the way out is release, never leave-in-flight.

- [ ] **Step 1: Write the failing tests**

```python
async def test_an_exception_inside_the_block_releases_the_record(adapter):
    ...

async def test_a_sub_500_HephError_is_stored_not_released(adapter):
    """Review Focus 2. A raised 422 is still a real outcome of the operation."""
    with pytest.raises(HephError):
        async with store.idempotent_record(...) as rec:
            raise HephError("HEPH-VAL-422", "bad field")
    row = await adapter.fetch_key("", "k")
    assert row["state"] == "completed" and row["response_status"] == 422


async def test_a_block_that_never_finishes_releases_rather_than_wedging(adapter):
    ...

async def test_a_replay_is_handed_to_the_caller_and_the_work_is_skipped(adapter):
    async with store.idempotent_record(...) as rec:
        assert rec.replay == Replay(201, b"{}", "application/json")
        work_ran = False
    assert work_ran is False
```

The second is the subtle one: `except Exception: release` is the obvious implementation and it is wrong. A `HephError` carries a registry status; below 500 it is an outcome to store, 500 and above is a release.

- [ ] **Step 2: Run and watch them fail**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_store.py -k record -v`
Expected: FAIL.

- [ ] **Step 3: Implement the context manager**

- [ ] **Step 4: Run and confirm**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(idempotency): a context manager whose default exit is release"
```

---

### Task 6: The FastAPI route integration

**Files:**
- Create: `python/hephkit/src/hephkit/idempotency/fastapi.py`
- Test: `python/hephkit/tests/test_idempotency_fastapi.py`

**Interfaces:**
- Consumes: `IdempotencyStore.idempotent_record`, the already-shipping `validate_key` and `fingerprint`, `hephkit.conventions.IDEMPOTENCY_KEY`.
- Produces:
  ```python
  def idempotent_route(store: IdempotencyStore, *, required: bool = True,
                       scope: Callable[[Request], str],
                       executors: Callable[[Request], AsyncContextManager[tuple[Executor, Executor]]],
                       ) -> Callable[[Handler], Handler]: ...
  ```
  Per-route, never global (2.1 distinguishes endpoints that require a key). `scope` is supplied by the application — hephkit does not infer a tenant. A route whose return annotation is `StreamingResponse` raises at **decoration time**, not per request.

Behaviour: validate the key (2.1); compute the fingerprint from the method, the **raw** request target (ASGI's `scope["raw_path"]` with any query stripped, plus `?` and `request.url.query` when a query is present — never a normalised path. **Not `request.url.path`,** which Starlette percent-decodes: that would make `/items/%41` and `/items/A` one request, which 2.2 forbids. A server that supplies no `raw_path` is refused with `RuntimeError` rather than fingerprinted from the decoded path) and the body bytes with their content type (2.2). Set `IDEMPOTENCY_KEY` on the current span. On `Replay`, return the stored bytes with the stored status, the stored content type and `Idempotent-Replayed: true`. `HephError`s propagate to `install_error_handlers`; this module builds no body.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_repeat_replays_the_stored_bytes_verbatim(client):
    """Review Focus 3. Byte-for-byte, not a re-serialised equivalent."""
    first = await client.post("/charges", json={"b": 1, "a": 2}, headers=KEY)
    again = await client.post("/charges", json={"b": 1, "a": 2}, headers=KEY)
    assert again.status_code == first.status_code
    assert again.content == first.content
    assert again.headers["idempotent-replayed"] == "true"
    assert again.headers["content-type"] == first.headers["content-type"]
    assert handler_calls == 1


async def test_the_same_key_with_a_different_body_is_422(client): ...
async def test_a_missing_key_on_a_required_route_is_400(client): ...


async def test_a_malformed_key_on_an_optional_route_is_ignored_not_rejected(client):
    """Spec 2.1: an endpoint that does not require a key MUST NOT fail over one."""


async def test_two_orderings_of_one_query_are_two_fingerprints(client):
    """Spec 2.2: the target is raw. ?a=1&b=2 and ?b=2&a=1 are different requests."""
    await client.post("/charges?a=1&b=2", json=BODY, headers=KEY)
    r = await client.post("/charges?b=2&a=1", json=BODY, headers=KEY)
    assert r.status_code == 422 and r.json()["code"] == "HEPH-IDEMP-422"


def test_a_streaming_route_is_refused_at_decoration(): ...
async def test_the_key_is_recorded_as_the_idempotency_key_attribute(span_exporter): ...
```

The query-ordering test is where a framework-normalised path gets caught. `examples/hello/app.py` shows the `span_exporter` fixture pattern for the last one.

- [ ] **Step 2: Run and watch them fail**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_fastapi.py -v`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Implement `idempotent_route`**

Reading the body consumes the stream; read it via `await request.body()`, which Starlette caches, before the handler runs.

- [ ] **Step 4: Run and confirm**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_fastapi.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(idempotency): per-route Idempotency-Key handling for FastAPI"
```

---

### Task 7: `@idempotent` for workers

**Files:**
- Create: `python/hephkit/src/hephkit/idempotency/worker.py`
- Test: `python/hephkit/tests/test_idempotency_worker.py`

**Interfaces:**
- Consumes: `IdempotencyStore.idempotent_record`, `hephkit.hashing.content_hash`.
- Produces:
  ```python
  def idempotent(store: IdempotencyStore, *, scope: Callable[[Any], str],
                 event_id: Callable[[Any], str],
                 executors: Callable[[Any], AsyncContextManager[tuple[Executor, Executor]]],
                 ) -> Callable[[Handler], Handler]: ...
  ```
  The key is the event id; the fingerprint is `content_hash(payload)` — the same canonicaliser as 2.2, so an identically redelivered event replays and the same id with a different payload is `HEPH-IDEMP-422`. Records are written with `kind="event"`: there is no response to store, so completion stores status 204 with an empty body and the `http`-only response-status constraint does not apply.

A replayed event is a **no-op that returns normally** — a worker must not see an exception for a message it already handled.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_redelivered_event_does_not_run_the_handler_again(adapter):
    await handle(event); await handle(event)
    assert calls == 1


async def test_the_same_event_id_with_a_different_payload_is_422(adapter): ...
async def test_a_raising_handler_releases_so_the_broker_can_redeliver(adapter): ...
async def test_an_event_record_stores_no_response_body(adapter): ...
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd python/hephkit && uv run pytest tests/test_idempotency_worker.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `idempotent`**

- [ ] **Step 4: Run the whole Python suite with the coverage gate**

Run: `cd python/hephkit && uv run maturin develop --uv && uv run pytest -m "not slow" --cov=hephkit --cov-fail-under=90`
Then: `uv run mypy --strict src`
Expected: PASS, both.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(idempotency): @idempotent for event handlers, keyed on event id"
```

---

### Task 8: The ADR, the docs page and the public surface

**Files:**
- Create: `docs/adr/0020-idempotency-storage-boundaries.md`
- Create: `docs/site/content/modules/idempotency.mdx`
- Modify: `python/hephkit/src/hephkit/idempotency/__init__.py` (re-exports; the "not here yet" paragraph goes)
- Modify: `docs/site/content/_snippets/site-data.json` and the generated reference page — **by running the generators, never by hand**

**Interfaces:**
- Consumes: everything above.
- Produces: `hephkit.idempotency` exporting `IdempotencyStore`, `Record`, `Proceed`, `Replay`, `Executor`, `AsyncpgExecutor`, `SQLAlchemyExecutor`, `idempotent_route` and `idempotent`, alongside the existing `validate_key`, `fingerprint`, `fingerprint_document`, `is_json_media_type` and `MAX_KEY_LENGTH`.

The ADR covers what outlives the module: the split transaction boundaries and why a single transaction is not an option, hephkit owning the SQL, DDL instead of migrations, async-only, and `READ COMMITTED` as a requirement rather than a preference. It cites both spikes as the evidence. Numbered `0020`, Accepted, dated, never edited after acceptance (CLAUDE.md).

The docs page needs a **runnable example** (CLAUDE.md's per-module list): create the schema, decorate one route, show a replay. It may use only names Task 6 actually exports.

- [ ] **Step 1: Run the checks and watch them fail**

Run: `python tools/check_adrs.py && python tools/check_modules.py && uv run tools/gen_site_pages.py --check`
Expected: FAIL — `gen_site_pages --check` reports stale generated pages; `check_adrs` objects until 0020 has a correct header.

- [ ] **Step 2: Write the ADR and the docs page; update the `__init__` docstring and `__all__`**

The docstring currently says 2.3–2.8 "is **not** here yet". That is now false and must go — a stale docstring on the module that *is* the public surface is worse than none.

- [ ] **Step 3: Regenerate, never hand-edit**

```bash
uv run tools/gen_site_pages.py && uv run tools/gen_error_pages.py && uv run tools/gen_quickstart.py
```

- [ ] **Step 4: Run every gate this branch touches**

```bash
python tools/check_adrs.py && python tools/check_registry.py && python tools/check_vectors.py && python tools/check_modules.py
uv run tools/gen_site_pages.py --check && uv run tools/gen_error_pages.py --check && uv run tools/gen_quickstart.py --check
bun install --frozen-lockfile && bun run --cwd docs/site build && bun test --cwd docs/site && uv run tools/check_site_links.py
uv run --with pytest --with pyyaml --with jsonschema --with rfc8785==0.1.4 pytest tools/tests -q
```
Expected: all PASS. Paste any failure; do not summarise it away.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0020-idempotency-storage-boundaries.md docs/site python/hephkit/src/hephkit/idempotency/__init__.py
git commit -m "docs(idempotency): ADR 0020, the module page and the regenerated site data"
```

---

## Verification before the PR

Everything CLAUDE.md lists for what this branch touches, run and read:

```bash
cd python/hephkit && uv run maturin develop --uv && uv run pytest --cov=hephkit && uv run mypy --strict src
cd ../.. && python tools/gen_errors.py --check && python tools/gen_conventions.py --check
python tools/check_adrs.py && python tools/check_registry.py && python tools/check_vectors.py && python tools/check_modules.py
```

The PR body states plainly that the module ships `experimental` and so may not sit in a production money path (rule 7), and that `python-ci.yml` — a reusable workflow consumed at `@v0` — gained a Postgres service.
