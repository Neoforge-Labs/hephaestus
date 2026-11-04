# Hephaestus Phase 1 — Core and Local Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `Neoforge-Labs/hephaestus` monorepo with heph-spec v0.1, the Rust correctness core (money, hashing, webhook signatures) shipped to Python as `hephkit`, the Python errors/settings/observability modules, base images, Compose fragments, a minimal `heph` CLI, reusable CI, and a five-minute tutorial — ending with Collie importing `hephkit.money` and running on `heph dev up` with traces in Grafana.

**Architecture:** Spec first: `spec/` and `conformance/` are written before any implementation, and every implementation (Rust now, Go/TS later) is tested against the same JSON vectors. The Rust crate `hephkit-core` holds all money, hashing and signature logic with no I/O; `hephkit-py` exposes it to Python through PyO3 (abi3), and the pure-Python `hephkit` package wraps it with typed APIs. The Go `heph` CLI embeds Compose fragments and drives `docker compose`.

**Tech Stack:** Rust (stable, edition 2021), PyO3 + maturin (abi3-py312), Python ≥ 3.12 with uv, FastAPI, pydantic-settings, OpenTelemetry, structlog, Go (version from Domus: 1.26.2) with cobra, moonrepo + proto, Docker Compose v2, grafana/otel-lgtm, GitHub Actions, release-please.

**Spec:** `docs/superpowers/specs/2026-11-04-hephaestus-design.md` (exported from the approved Claude doc "Hephaestus — NeoForge's full-stack component and package suite", rev 107). Phase 1 = Rollout step 1, "Weeks 1–2: Core and local stack".

## Global Constraints

- Licence: MIT, public repo `Neoforge-Labs/hephaestus`.
- Package names: PyPI `hephkit`, crates.io `hephkit-core`, npm scope `@hephkit`, Go module `github.com/Neoforge-Labs/hephaestus/go`, CLI binary `heph`, images `ghcr.io/neoforge-labs/heph-<runtime>`.
- Python floor `>=3.12`; wheels are abi3 (`abi3-py312`), built for Linux x86_64 and aarch64 (glibc and musl) and macOS arm64.
- Rust core: no I/O, no global state, no `unsafe` outside PyO3 glue; every public function returns `Result` rather than panicking.
- Money is integer minor units (`i64`); floating point never touches money.
- Error codes match `^HEPH-[A-Z]{2,6}-\d{3}$`; problem `type` URL is `https://heph.neoforgelabs.tech/errors/<code>`.
- Canonical JSON is RFC 8785 (JCS). Content hashes are `sha256:` + lowercase hex.
- Webhook signing follows Standard Webhooks (`webhook-id`, `webhook-timestamp`, `webhook-signature`, `v1,<base64>`), tolerance 300 s.
- Local host ports live in the 54xxx block so Hephaestus stacks never fight other local stacks (Grafana on 3000 collides with Docker on this machine, per Domus).
- Every module ships labelled `experimental` in this phase; nothing is `stable` until the promotion criteria in the spec are met.
- Commits use Conventional Commits; branches are `work/<topic>`. No AI attribution in commits, PR bodies or branch names (the rule Kelyn applies to Collie and Domus).
- Coverage gate: ≥ 90% line coverage on `hephkit-core` and on `hephkit.money`, `hephkit.hashing`, `hephkit.signatures`; ≥ 80% on the other Python modules.

## Review Focus

1. **Locale-formatted or non-ASCII amounts** (`"1,000.50"`, `"١٠٠"`, Unicode minus `"−5"`, full-width digits) must be rejected with `HEPH-MONEY-422`, never silently misparsed. → vectors in Task 3, exercised by Tasks 4 and 7.
2. **Rotated webhook secrets:** a `webhook-signature` header carrying several space-separated signatures (and unknown versions such as `v1a,…`) verifies if any `v1` signature matches; unknown versions are ignored, not errors. → vectors in Task 3, tests in Task 6.
3. **Future-dated webhook timestamps** beyond the 300 s tolerance are rejected the same as stale ones (replay window is symmetric). → test in Task 6.
4. **JCS edge values** — non-ASCII strings, `1e21`, `-0`, integers above 2^53, nested key ordering by UTF-16 code units — hash identically in every language. → vectors in Task 3, tests in Task 5.
5. **`heph dev up` without a working Docker, or with a port already taken,** exits non-zero with a message naming the missing tool or the port and the fragment that wants it. → tests in Task 13.

---

### Task 1: Repository bootstrap, toolchain and decision records

**Files:**
- Create: `LICENSE`, `README.md`, `.gitignore`, `.editorconfig`, `.prototools`, `.moon/workspace.yml`, `.moon/toolchain.yml`, `.github/workflows/ci.yml`
- Create: `docs/adr/0000-template.md`, `docs/adr/0001-record-decisions.md` … `docs/adr/0015-maturity-levels.md`
- Create: `tools/check_adrs.py`, `tools/tests/test_check_adrs.py`

**Interfaces:**
- Produces: moon projects `spec`, `conformance`, `core`, `hephkit`, `heph-cli`, `docker`, `compose`, `docs`, `examples-hello` (each later task adds its `moon.yml`); CI entry `.github/workflows/ci.yml` that later tasks extend.

- [ ] **Step 1: Write the failing test** — `tools/tests/test_check_adrs.py::test_adr_files_are_numbered_and_complete` asserts every `docs/adr/NNNN-*.md` has a four-digit prefix, numbers are contiguous from 0001, and each file contains the headings `## Status`, `## Context`, `## Decision`, `## Consequences`; `test_rejects_gap` feeds a temp dir with 0001 and 0003 and asserts `check_adrs(path)` returns an error mentioning `0002`.
- [ ] **Step 2: Run it to verify it fails** — `uv run --with pytest pytest tools/tests -v` → FAIL (`check_adrs` not defined).
- [ ] **Step 3: Implement `check_adrs(root: Path) -> list[str]` in `tools/check_adrs.py`** (returns error strings; CLI exits 1 if any).
- [ ] **Step 4: Write ADRs 0001–0015**, one per settled decision in the spec's Decisions and Adopt-or-build sections: 0001 record decisions as ADRs; 0002 MIT licence; 0003 name Hephaestus / `hephkit`; 0004 Rust core with bindings; 0005 heph-spec profiles existing standards; 0006 Procrastinate jobs, Celery adapter; 0007 MLflow; 0008 LangGraph; 0009 Grafana Cloud over OTLP; 0010 HCP Terraform state; 0011 Hono and Express on Bun; 0012 modular monolith in a monorepo by default; 0013 pluggable brokers and stores (NATS, Postgres, pgvector defaults); 0014 adopt-or-build list (Keycloak, Svix, Restate/Temporal, Dapr spike, Inspect, moonrepo, Atlas); 0015 maturity levels. Status `Accepted`, date 2026-11-04.
- [ ] **Step 5: Configure toolchain** — `.prototools` pins go `1.26.2`, python `3.12`, uv, node (current Active LTS), bun; Rust is pinned in `rust-toolchain.toml` (stable channel, components `clippy`, `rustfmt`) if proto has no stable Rust plugin, and that choice is noted in ADR 0004. `.moon/workspace.yml` lists the projects above.
- [ ] **Step 6: Verify** — `uv run --with pytest pytest tools/tests -v` → PASS; `python tools/check_adrs.py` → exit 0; `moon query projects` lists the workspace without error.
- [ ] **Step 7: Commit** — `chore: bootstrap monorepo, toolchain and ADRs 0001-0015`

---

### Task 2: heph-spec v0.1, error registry and telemetry conventions

**Files:**
- Create: `spec/heph-spec.md`, `spec/errors.yaml`, `conventions/attributes.yaml`, `spec/moon.yml`
- Create: `tools/check_registry.py`, `tools/tests/test_check_registry.py`

**Interfaces:**
- Produces: `spec/errors.yaml` entries `{code, status, title, area, detail_hint}`; `conventions/attributes.yaml` entries `{name, type, description, pii: bool}`. Tasks 8 and 10 generate code from these files; Task 15 generates docs pages from them.

- [ ] **Step 1: Write the failing tests** — `test_registry_codes_valid` loads `spec/errors.yaml` and asserts every code matches `^HEPH-[A-Z]{2,6}-\d{3}$`, codes are unique, `status` is 400–599, `area` equals the code's middle segment. `test_registry_has_v01_codes` asserts these codes exist with these statuses: `HEPH-GEN-500` 500, `HEPH-VAL-422` 422, `HEPH-NF-404` 404, `HEPH-AUTH-401` 401, `HEPH-AUTH-403` 403, `HEPH-RATE-429` 429, `HEPH-IDEMP-400` 400 (key missing), `HEPH-IDEMP-409` 409 (original still in flight), `HEPH-IDEMP-422` 422 (key reused with a different payload), `HEPH-MONEY-422` 422 (invalid amount), `HEPH-MONEY-409` 409 (currency mismatch), `HEPH-WH-401` 401 (webhook signature invalid or expired). `test_attributes_valid` asserts attribute names are dotted lowercase, unique, and include `tenant.id`, `user.id`, `idempotency.key`, `job.name`, `webhook.provider`, `money.currency`, `heph.error.code`, with `user.id` marked `pii: true`.
- [ ] **Step 2: Run to verify failure** — `uv run --with pytest,pyyaml pytest tools/tests/test_check_registry.py -v` → FAIL.
- [ ] **Step 3: Write `spec/heph-spec.md` v0.1** with these sections, each naming the standard it profiles: Errors (RFC 9457; `type` URL pattern; `code` extension member; `trace_id` extension member); Idempotency (IETF `Idempotency-Key` draft: fingerprint = `sha256:` hash of JCS of `{"method","path","body"}`; replay returns stored status and body plus header `Idempotent-Replayed: true`; 409/422/400 as in the registry; default retention 24 h); Money on the wire (`{"amount": "<minor units as base-10 string>", "currency": "<ISO 4217>"}`, string to survive JavaScript numbers); Canonical JSON and hashing (RFC 8785; `sha256:` prefix); Webhooks (Standard Webhooks; tolerance 300 s; multiple signatures; unknown versions ignored); Telemetry (OpenTelemetry semconv plus `conventions/attributes.yaml`); Provenance record (marked `draft`, fields `run_id`, `config_hash`, `data_hash`, `code_sha`, `class: deterministic|provenance-only`). Header states `Version: 0.1.0`.
- [ ] **Step 4: Write `spec/errors.yaml` and `conventions/attributes.yaml`, then implement `check_registry(errors: Path, attributes: Path) -> list[str]`** in `tools/check_registry.py`.
- [ ] **Step 5: Verify** — tests PASS; `python tools/check_registry.py` exit 0.
- [ ] **Step 6: Commit** — `docs(spec): heph-spec v0.1, error registry and telemetry conventions`

---

### Task 3: Conformance vectors

**Files:**
- Create: `conformance/schema/vector-file.schema.json`, `conformance/money/{currency,parse,format,arith,allocate}.json`, `conformance/hashing/{jcs,content}.json`, `conformance/signatures/{sign,verify}.json`
- Create: `tools/gen_signature_vectors.py`, `tools/check_vectors.py`, `tools/tests/test_check_vectors.py`

**Interfaces:**
- Produces: vector files of shape `{"suite": str, "spec": "0.1.0", "cases": [{"name": str, "input": {...}, "expect": {...}}]}` where an error expectation is `{"error": "<HEPH code>"}`. Suites and their `input`/`expect` keys:
  - `money.currency`: `{code}` → `{exponent}`
  - `money.parse`: `{amount, currency, rounding: "reject"|"half_up"|"half_even"|"down"}` → `{minor}` or error
  - `money.format`: `{minor, currency}` → `{amount}`
  - `money.arith`: `{op: "add"|"sub"|"neg", a: wire, b?: wire}` → `{result: wire}` or error
  - `money.allocate`: `{money: wire, ratios: [int]}` → `{parts: [wire]}` or error
  - `hashing.jcs`: `{json: str}` → `{canonical: str}`
  - `hashing.content`: `{json: str}` → `{hash: str}`
  - `signatures.sign`: `{secret, msg_id, timestamp, payload_b64}` → `{signature}`
  - `signatures.verify`: `{secret, headers: {webhook-id, webhook-timestamp, webhook-signature}, payload_b64, now}` → `{ok: true}` or error

- [ ] **Step 1: Write the failing test** — `test_all_vector_files_match_schema` validates every `conformance/**/*.json` against the schema; `test_minimum_case_counts` asserts at least: currency 12, parse 30, format 10, arith 8, allocate 10, jcs 12, content 6, sign 4, verify 10.
- [ ] **Step 2: Run to verify failure** — `uv run --with pytest,jsonschema pytest tools/tests/test_check_vectors.py -v` → FAIL.
- [ ] **Step 3: Write the money vectors.** Currency exponents: USD 2, EUR 2, GBP 2, KES 2, TZS 2, NGN 2, ZAR 2, UGX 0, JPY 0, BHD 3, KWD 3, OMR 3; unknown `XYZ` → `HEPH-MONEY-422`. Parse cases include, for KES with `reject`: `"10"`→1000, `"0.01"`→1, `"10.29"`→1029, `"10.2"`→1020, `"0"`→0, `"-5"`→-500; errors (`HEPH-MONEY-422`) for `""`, `"."`, `".5"`, `"1."`, `"10.299"`, `" 1.00"`, `"1.00 "`, `"+5"`, `"1e3"`, `"abc"`, `"1,000.50"`, `"١٠٠"`, `"−5"` (U+2212), `"１０"` (full-width), `"184467440737095517"` (overflow). Rounding: KES `"10.295"` half_up→1030, half_even→1030, down→1029; `"10.285"` half_even→1028; `"-10.295"` half_up→-1030. JPY `"10"`→10, `"10.5"` reject→error. BHD `"1.234"`→1234. Format: KES 1020→`"10.20"`, -5→`"-0.05"`, JPY 1000→`"1000"`, BHD 1→`"0.001"`. Arith: KES+USD → `HEPH-MONEY-409`; add overflow near `i64::MAX` → `HEPH-MONEY-422`. Allocate: KES 100 minor by `[1,1,1]` → `[34,33,33]`; 5 by `[1,1]` → `[3,2]`; -100 by `[1,1,1]` → `[-34,-33,-33]`; 100 by `[0,1]` → `[0,100]`; 100 by `[0,0]` → error; 100 by `[]` → error; 1 by `[1,1,1]` → `[1,0,0]`.
- [ ] **Step 4: Write the hashing vectors** from RFC 8785 Appendix B and the cyberphone `json-canonicalization` test data, including non-ASCII strings, `1e21`, `-0`, `9007199254740993`, and nested objects whose keys sort differently by UTF-16 code unit than by code point. Content hashes are computed by `tools/gen_signature_vectors.py --hashing` using Python's `hashlib` over JCS produced by the reference `rfc8785` package, not by our code.
- [ ] **Step 5: Write `tools/gen_signature_vectors.py`** generating sign/verify vectors with the reference `standardwebhooks` package (secret `whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw`, ids `msg_p5jXN8AQM9LWM0D4loKWxJek`, fixed timestamps). Verify cases: valid; payload tampered → `HEPH-WH-401`; timestamp 301 s old → `HEPH-WH-401`; timestamp 301 s in the future → `HEPH-WH-401`; header with two signatures where only the second matches → ok; header containing `v1a,abc v1,<valid>` → ok; missing `webhook-id` → `HEPH-WH-401`; malformed signature (no comma) → `HEPH-WH-401`; wrong secret → `HEPH-WH-401`; secret without `whsec_` prefix accepted as raw base64 → ok. Run it once and commit the output; the generator is never run against our own implementation.
- [ ] **Step 6: Verify** — tests PASS; `python tools/check_vectors.py` exit 0.
- [ ] **Step 7: Commit** — `test(conformance): v0.1 vectors for money, hashing and signatures`

---

### Task 4: `hephkit-core` money

**Files:**
- Create: `core/Cargo.toml` (workspace), `core/hephkit-core/Cargo.toml`, `core/hephkit-core/src/lib.rs`, `core/hephkit-core/src/money/{mod.rs,currency.rs,parse.rs,allocate.rs}`, `core/hephkit-core/src/error.rs`
- Create: `core/hephkit-core/tests/conformance_money.rs`, `core/hephkit-core/tests/prop_money.rs`, `core/fuzz/fuzz_targets/money_parse.rs`, `core/moon.yml`

**Interfaces:**
- Produces (Rust, re-exported at crate root):
  - `pub enum CoreError { Money { code: &'static str, message: String }, Signature { code: &'static str, message: String }, Hashing { message: String } }` — `code` is the HEPH code string from `spec/errors.yaml`.
  - `pub struct Currency { pub code: [u8; 3], pub exponent: u8 }`; `Currency::from_code(&str) -> Result<Currency, CoreError>`
  - `pub enum Rounding { Reject, HalfUp, HalfEven, Down }`
  - `pub struct Money { pub minor: i64, pub currency: Currency }` with `Money::new(minor, Currency)`, `Money::parse(&str, Currency, Rounding) -> Result<Money, CoreError>`, `fn to_decimal_string(&self) -> String`, `fn checked_add(&self, &Money) -> Result<Money, CoreError>`, `fn checked_sub`, `fn checked_neg`, `fn allocate(&self, ratios: &[u64]) -> Result<Vec<Money>, CoreError>`.

- [ ] **Step 1: Write the failing tests** — `conformance_money.rs` loads every case in `../../conformance/money/*.json` (path via `env!("CARGO_MANIFEST_DIR")`) and asserts the result or error code matches; one `#[test]` per suite. `prop_money.rs` (proptest): `allocate_preserves_total` (sum of parts == original for any `minor` in `i64::MIN/2..i64::MAX/2` and 1–20 ratios in `0..1000` with at least one non-zero), `allocate_parts_differ_by_at_most_one_unit_per_ratio_weight`, `parse_format_roundtrip` for every exponent.
- [ ] **Step 2: Run to verify failure** — `cargo test -p hephkit-core` → FAIL (unresolved items).
- [ ] **Step 3: Implement.** Parse grammar is ASCII only: optional `-`, one or more `0-9`, optional `.` followed by one or more `0-9`; anything else is `HEPH-MONEY-422`. Overflow is checked before multiplying, as Domus `pkg/money` does. Allocation uses largest remainder: floor each share, then hand the leftover units one at a time to the parts with the largest remainder, ties to the lower index; negative amounts allocate the absolute value and negate each part.
- [ ] **Step 4: Add fuzz target** `money_parse` (cargo-fuzz) that asserts `parse` never panics and that any `Ok` round-trips through `to_decimal_string`.
- [ ] **Step 5: Verify** — `cargo test -p hephkit-core` PASS; `cargo clippy -p hephkit-core -- -D warnings` clean; `cargo +nightly fuzz run money_parse -- -max_total_time=60` finds nothing.
- [ ] **Step 6: Commit** — `feat(core): money with currency exponents, strict parsing and allocation`

---

### Task 5: `hephkit-core` canonical JSON, content hashing and UUIDv7

**Files:**
- Create: `core/hephkit-core/src/hashing.rs`, `core/hephkit-core/tests/conformance_hashing.rs`

**Interfaces:**
- Produces: `pub fn canonical_json(json: &str) -> Result<String, CoreError>`, `pub fn content_hash_json(json: &str) -> Result<String, CoreError>` (returns `sha256:<64 hex>`), `pub fn content_hash_bytes(bytes: &[u8]) -> String`, `pub fn new_uuid7() -> String` (lowercase hyphenated).

- [ ] **Step 1: Write the failing tests** — `conformance_hashing.rs` runs `hashing.jcs` and `hashing.content` vectors; `uuid7_is_version_7_and_time_ordered` generates 1,000 ids and asserts version nibble `7`, variant `10xx`, and lexicographic order equals generation order across a 2 ms sleep.
- [ ] **Step 2: Run to verify failure** — `cargo test -p hephkit-core hashing` → FAIL.
- [ ] **Step 3: Implement** with `sha2`, `uuid` (feature `v7`) and an RFC 8785 serializer (an existing crate such as `serde_json_canonicalizer` is acceptable only if it passes every vector; otherwise implement number serialization per ECMAScript `Number.prototype.toString` and key sorting by UTF-16 code units).
- [ ] **Step 4: Verify** — `cargo test -p hephkit-core` PASS.
- [ ] **Step 5: Commit** — `feat(core): RFC 8785 canonical JSON, content hashes and UUIDv7`

---

### Task 6: `hephkit-core` Standard Webhooks signatures

**Files:**
- Create: `core/hephkit-core/src/signatures.rs`, `core/hephkit-core/tests/conformance_signatures.rs`, `core/fuzz/fuzz_targets/signature_header.rs`

**Interfaces:**
- Produces: `pub fn sign(secret: &str, msg_id: &str, timestamp: i64, payload: &[u8]) -> Result<String, CoreError>` (returns `v1,<base64>`); `pub fn verify(secret: &str, msg_id: &str, timestamp_header: &str, signature_header: &str, payload: &[u8], now: i64, tolerance_secs: i64) -> Result<(), CoreError>`; `pub const DEFAULT_TOLERANCE_SECS: i64 = 300;`

- [ ] **Step 1: Write the failing tests** — run `signatures.sign` and `signatures.verify` vectors; `equal_length_mismatch_rejected` flips one byte of a valid signature and expects `HEPH-WH-401`.
- [ ] **Step 2: Run to verify failure** — `cargo test -p hephkit-core signatures` → FAIL.
- [ ] **Step 3: Implement** with `hmac`, `sha2`, `base64`; compare with `hmac::Mac::verify_slice` (constant time), never `==`; strip an optional `whsec_` prefix before base64-decoding the secret; signed content is `{msg_id}.{timestamp}.{payload}`; split the header on spaces, ignore entries whose version is not exactly `v1`, accept if any `v1` matches; reject when `|now - timestamp| > tolerance_secs`.
- [ ] **Step 4: Add fuzz target** `signature_header` asserting `verify` never panics on arbitrary headers.
- [ ] **Step 5: Verify** — `cargo test -p hephkit-core` PASS; clippy clean; coverage `cargo llvm-cov -p hephkit-core --fail-under-lines 90` passes.
- [ ] **Step 6: Commit** — `feat(core): Standard Webhooks signing and verification`

---

### Task 7: Python package `hephkit` with the Rust bindings

**Files:**
- Create: `core/hephkit-py/Cargo.toml`, `core/hephkit-py/src/lib.rs`
- Create: `python/hephkit/pyproject.toml`, `python/hephkit/src/hephkit/{__init__.py,py.typed,_core.pyi,money.py,hashing.py,signatures.py}`, `python/hephkit/moon.yml`
- Test: `python/hephkit/tests/{test_conformance.py,test_money_props.py,test_money_decimal.py}`

**Interfaces:**
- Consumes: Tasks 4–6 Rust API.
- Produces (Python):
  - `hephkit.money`: `Rounding = Literal["reject","half_up","half_even","down"]`; `@final class Money` (immutable, hashable) with `Money.parse(amount: str, currency: str, rounding: Rounding = "reject") -> Money`, `Money.from_decimal(value: Decimal, currency: str, rounding: Rounding = "reject") -> Money`, `.minor: int`, `.currency: str`, `.to_decimal() -> Decimal`, `.to_wire() -> dict[str, str]`, `Money.from_wire(d: Mapping[str, str]) -> Money`, `__add__`, `__sub__`, `__neg__`, `__eq__`, `.allocate(ratios: Sequence[int]) -> list[Money]`, `__str__` → `"KES 10.20"`; `class MoneyError(ValueError)` with `.code: str`.
  - `hephkit.hashing`: `canonical_json(obj: Any) -> str`, `content_hash(obj: Any) -> str`, `content_hash_bytes(data: bytes) -> str`, `new_uuid7() -> str`.
  - `hephkit.signatures`: `sign(secret: str, msg_id: str, timestamp: int, payload: bytes) -> str`, `verify(secret: str, headers: Mapping[str, str], payload: bytes, *, now: int | None = None, tolerance: int = 300) -> None`, `class SignatureError(ValueError)` with `.code`.

- [ ] **Step 1: Write the failing tests** — `test_conformance.py` parametrizes over every vector file and calls the Python API (wire dicts in, wire dicts out); `test_money_props.py` (Hypothesis) mirrors the Rust properties; `test_money_decimal.py`: `Money.from_decimal(Decimal("5000.00"), "KES").minor == 500000`, `Money.from_decimal(Decimal("0.005"), "KES")` raises `MoneyError` with `code == "HEPH-MONEY-422"`, `Money.from_decimal(Decimal("0.005"), "KES", "half_up").minor == 1`, `Money.parse("10.20","KES").to_decimal() == Decimal("10.20")`, `float` arguments raise `TypeError`.
- [ ] **Step 2: Run to verify failure** — `cd python/hephkit && uv sync && uv run pytest -v` → FAIL (import error).
- [ ] **Step 3: Implement** the PyO3 module `hephkit._core` (`abi3-py312`, maturin `python-source = "src"`, `manifest-path = "../../core/hephkit-py/Cargo.toml"`) mapping `CoreError` codes onto `MoneyError`/`SignatureError`; write `_core.pyi`; Python wrappers convert `Decimal` via `str(value)` with exponent normalization, never via `float`.
- [ ] **Step 4: Verify** — `uv run maturin develop --uv && uv run pytest --cov=hephkit --cov-fail-under=90 -v` PASS; `uv run mypy --strict src` clean; `uv run maturin build --release` produces an `abi3` wheel.
- [ ] **Step 5: Commit** — `feat(python): hephkit money, hashing and signatures over the Rust core`

---

### Task 8: `hephkit.errors`

**Files:**
- Create: `tools/gen_errors.py`, `python/hephkit/src/hephkit/errors/{__init__.py,_codes.py,fastapi.py}`
- Test: `python/hephkit/tests/test_errors.py`, `tools/tests/test_gen_errors.py`

**Interfaces:**
- Consumes: `spec/errors.yaml` (Task 2); `MoneyError`, `SignatureError` (Task 7).
- Produces: `class HephError(Exception)` with `__init__(self, code: str, detail: str | None = None, **extensions: Any)` and properties `code`, `status`, `title`, `type_url`; generated constants in `_codes.py` (e.g. `IDEMP_409 = "HEPH-IDEMP-409"`); `def install_error_handlers(app: FastAPI) -> None`.

- [ ] **Step 1: Write the failing tests** — `test_gen_errors.py`: running the generator twice produces identical output, and `--check` exits 1 when `_codes.py` is stale. `test_errors.py`: raising `HephError("HEPH-IDEMP-409")` inside a FastAPI route returns status 409, `content-type: application/problem+json`, body `{"type": "https://heph.neoforgelabs.tech/errors/HEPH-IDEMP-409", "title": <registry title>, "status": 409, "code": "HEPH-IDEMP-409"}` plus `trace_id` when a span is active; an unknown code raises `ValueError` at construction; a raised `MoneyError` maps to 422 `HEPH-MONEY-422`; an unhandled exception maps to 500 `HEPH-GEN-500` without leaking the exception message; FastAPI request validation errors map to 422 `HEPH-VAL-422` with the field errors under `errors`.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_errors.py -v` → FAIL.
- [ ] **Step 3: Implement** `tools/gen_errors.py` (YAML → `_codes.py` with a `REGISTRY: dict[str, tuple[int, str]]`), `HephError`, and `install_error_handlers`.
- [ ] **Step 4: Verify** — tests PASS; `python tools/gen_errors.py --check` exit 0; mypy strict clean.
- [ ] **Step 5: Commit** — `feat(python): problem+json errors generated from the registry`

---

### Task 9: `hephkit.settings`

**Files:**
- Create: `python/hephkit/src/hephkit/settings.py`
- Test: `python/hephkit/tests/test_settings.py`

**Interfaces:**
- Produces: `class HephSettings(BaseSettings)` (env prefix `HEPH_`) with fields `env: Literal["dev","test","prod"] = "dev"`, `service_name: str`, `otlp_endpoint: str = "http://localhost:54318"`, `database_url: SecretStr | None = None`, `log_level: str = "INFO"`; class var `required_in_prod: ClassVar[tuple[str, ...]] = ("database_url",)` that subclasses extend; `class SettingsError(RuntimeError)` with `.missing: list[str]`.

- [ ] **Step 1: Write the failing tests** — `HEPH_SERVICE_NAME=x` alone loads in dev; in prod with `database_url` unset and a subclass adding `stripe_key: SecretStr | None` to `required_in_prod`, construction raises `SettingsError` whose `.missing == ["database_url", "stripe_key"]` (all reported at once, in declaration order); `repr(settings)` and `settings.model_dump_json()` never contain the secret value.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_settings.py -v` → FAIL.
- [ ] **Step 3: Implement** with a pydantic `model_validator(mode="after")`.
- [ ] **Step 4: Verify** — PASS; mypy strict clean.
- [ ] **Step 5: Commit** — `feat(python): fail-fast settings with prod-required secrets`

---

### Task 10: `hephkit.observability` and generated conventions

**Files:**
- Create: `tools/gen_conventions.py`, `python/hephkit/src/hephkit/conventions.py` (generated), `python/hephkit/src/hephkit/observability.py`
- Test: `python/hephkit/tests/test_observability.py`, `tools/tests/test_gen_conventions.py`

**Interfaces:**
- Consumes: `conventions/attributes.yaml` (Task 2), `HephSettings` (Task 9), `install_error_handlers` (Task 8).
- Produces: constants in `hephkit.conventions` (`TENANT_ID = "tenant.id"`, …, `PII_ATTRIBUTES: frozenset[str]`); `def setup_observability(settings: HephSettings, app: FastAPI | None = None, *, span_exporter: SpanExporter | None = None) -> Observability`; `class Observability` with `shutdown() -> None`; `def get_logger(name: str) -> structlog.BoundLogger`. Default redacted keys: `password`, `secret`, `token`, `authorization`, `api_key`, `card_number`, `cookie`, plus every attribute with `pii: true`.

- [ ] **Step 1: Write the failing tests** — with an `InMemorySpanExporter`, a request to an instrumented FastAPI app produces a server span whose resource has `service.name == settings.service_name` and `deployment.environment == "test"`; a log line emitted inside the request is JSON with `trace_id` and `span_id` matching the span; `get_logger("t").info("x", password="p", user_id="u", amount="10")` renders `password` and `user.id`-mapped field as `"[REDACTED]"` and leaves `amount`; calling `setup_observability` twice is a no-op the second time; `gen_conventions.py --check` exits 1 when stale.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_observability.py -v` → FAIL.
- [ ] **Step 3: Implement** with the OpenTelemetry SDK, OTLP HTTP exporter to `settings.otlp_endpoint`, `opentelemetry-instrumentation-fastapi`, and a structlog processor chain (contextvars → trace ids → redaction → JSON).
- [ ] **Step 4: Verify** — PASS; coverage ≥ 80% for the module; mypy strict clean.
- [ ] **Step 5: Commit** — `feat(python): one-call OpenTelemetry and structured logging with redaction`

---

### Task 11: Base images

**Files:**
- Create: `docker/python/Dockerfile`, `docker/node/Dockerfile`, `docker/moon.yml`, `docker/test/image_test.sh`

**Interfaces:**
- Produces: `ghcr.io/neoforge-labs/heph-python:<version>` (build arg `PYTHON_VERSION`, default `3.13`; uv on PATH; user `heph` uid 10001; workdir `/app`; `HEALTHCHECK` none — services define their own) and `ghcr.io/neoforge-labs/heph-node:<version>` (current Node Active LTS, Next.js standalone-ready, uid 10001). Base images pinned by digest.

- [ ] **Step 1: Write the failing test** — `docker/test/image_test.sh IMAGE` asserts `docker run --rm IMAGE id -u` prints `10001`, `uv --version` succeeds in heph-python, `node --version` succeeds in heph-node, and image size is under 250 MB for heph-python.
- [ ] **Step 2: Run to verify failure** — `bash docker/test/image_test.sh heph-python:dev` → FAIL (image missing).
- [ ] **Step 3: Write both Dockerfiles** (multi-stage, `--no-install-recommends`, apt lists removed).
- [ ] **Step 4: Verify** — `docker build -t heph-python:dev docker/python && bash docker/test/image_test.sh heph-python:dev` PASS; same for node; `trivy image --severity HIGH,CRITICAL --exit-code 1 heph-python:dev` passes or every finding is documented in `docker/TRIVY_EXCEPTIONS.md`.
- [ ] **Step 5: Commit** — `feat(docker): heph-python and heph-node base images`

---

### Task 12: Compose fragments

**Files:**
- Create: `compose/{postgres,objects,telemetry,mail,redis,stripe}.yaml`, `compose/seaweedfs-s3.json`, `compose/test/boot_test.sh`, `compose/moon.yml`

**Interfaces:**
- Produces: fragment files each defining one service with a healthcheck and named volume, mergeable with `docker compose -f a.yaml -f b.yaml`. Host ports: postgres `54320`; objects S3 `54333`, master UI `54334`; telemetry Grafana `54300`, OTLP gRPC `54317`, OTLP HTTP `54318`; mail SMTP `54025`, UI `54825`; redis `54379`. Images: `pgvector/pgvector:pg17`, `chrislusf/seaweedfs:3.99`, `grafana/otel-lgtm`, `axllent/mailpit`, `redis:7-alpine`, `stripe/stripe-cli` — each pinned to a version tag at implementation time.

- [ ] **Step 1: Write the failing test** — `compose/test/boot_test.sh` brings up each fragment alone with `docker compose -p heph-boot -f compose/<f>.yaml up -d --wait --wait-timeout 120`, asserts healthy, then tears down with `-v`; then brings up all except `stripe` together and asserts: `psql` on 54320 runs `select 1`; `aws --endpoint-url http://localhost:54333 s3 ls` returns (empty list or 403 both count as alive); `curl -sf localhost:54300/api/health`; `curl -s -o /dev/null -w '%{http_code}' -X POST localhost:54318/v1/traces -H 'content-type: application/json' -d '{}'` returns 200 or 400; Mailpit UI returns 200.
- [ ] **Step 2: Run to verify failure** — `bash compose/test/boot_test.sh` → FAIL.
- [ ] **Step 3: Write the fragments.** `objects.yaml` reuses Nocturna's SeaweedFS service verbatim in shape (command `server -dir=/data -ip=seaweedfs -s3 -s3.port=8333 -s3.config=/etc/seaweedfs/s3.json`, the two-probe healthcheck), including its comment on why MinIO is not used. `stripe.yaml` has no healthcheck dependency for others and requires `STRIPE_API_KEY`.
- [ ] **Step 4: Verify** — `bash compose/test/boot_test.sh` PASS.
- [ ] **Step 5: Commit** — `feat(compose): local-stack fragments with otel-lgtm and SeaweedFS`

---

### Task 13: `heph` CLI — `dev up|down|status`, `doctor`, `version`

**Files:**
- Create: `go/go.mod`, `go/cmd/heph/main.go`, `go/internal/cli/{root.go,dev.go,doctor.go,version.go}`, `go/internal/ingot/config.go`, `go/internal/fragments/{fragments.go,sync.go}`, `go/internal/compose/runner.go`, `go/moon.yml`
- Test: `go/internal/ingot/config_test.go`, `go/internal/fragments/fragments_test.go`, `go/internal/compose/runner_test.go`, `go/internal/cli/doctor_test.go`

**Interfaces:**
- Consumes: `compose/*.yaml` (Task 12), copied into `go/internal/fragments/files/` by the moon task `heph-cli:sync-fragments` (gitignored output; CI fails if the copy differs from `compose/`).
- Produces: `heph.toml` format `[ingot] name = "<name>"` and `[dev] fragments = ["telemetry", ...]`; `ingot.Load(dir string) (Config, error)`; `fragments.Resolve(names []string) ([]Fragment, error)` where `Fragment{Name string; Path string; Ports []int}`; `compose.Args(project string, files []string, verb string) []string`; `type Runner interface { Run(ctx, args []string) error }`; exit codes 0 success, 1 user error, 2 environment error.

- [ ] **Step 1: Write the failing tests** — `config_test`: missing `heph.toml` → error mentioning `heph.toml` and the directory; `fragments_test`: `Resolve([]string{"telemetry","nope"})` errors with text listing available fragments; ports are parsed from each fragment's `ports:`; `runner_test`: `Args("hello", ["/f/a.yaml","/f/b.yaml"], "up")` equals `["compose","-p","hello","-f","/f/a.yaml","-f","/f/b.yaml","up","-d","--wait"]`; `doctor_test` with a fake environment: no `docker` on PATH → exit 2 and message `docker not found`; docker present but compose v1 → exit 2 naming Compose v2; port 54318 already bound (test opens a listener) → `heph dev up` preflight exits 2 with message naming port `54318` and fragment `telemetry`.
- [ ] **Step 2: Run to verify failure** — `cd go && go test ./...` → FAIL.
- [ ] **Step 3: Implement** with `spf13/cobra` and `BurntSushi/toml`; `dev up` runs preflight (doctor + port check), writes fragments to a temp dir, runs `docker compose … up -d --wait`, then prints the Grafana URL `http://localhost:54300`; `dev status` runs `ps`; `dev down` runs `down` (keeps volumes unless `--volumes`).
- [ ] **Step 4: Verify** — `go test ./...` PASS; `go vet ./... && staticcheck ./...` clean; manual: in `examples/hello` (Task 15) `heph dev up` then `heph dev status` shows healthy services.
- [ ] **Step 5: Commit** — `feat(cli): heph dev up/down/status, doctor and version`

---

### Task 14: Reusable CI, wheels and release

**Files:**
- Create: `.github/workflows/{python-ci.yml,rust-ci.yml,go-ci.yml,rust-wheels.yml,docker-publish.yml,compose-boot.yml,ecosystem.yml,release.yml}`, `release-please-config.json`, `.release-please-manifest.json`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `workflow_call` workflows other repos use as `Neoforge-Labs/hephaestus/.github/workflows/<name>.yml@v0`. `rust-wheels.yml` outputs wheel artifacts for linux x86_64/aarch64 (manylinux and musllinux) and macOS arm64 via `PyO3/maturin-action`. `release.yml` (on release-please release) publishes to PyPI with trusted publishing (`id-token: write`, no tokens) and pushes signed images. `ecosystem.yml` runs a matrix of consumer repos at pinned refs; in this phase only `examples/hello` is enabled, with Collie, Domus, SAWA and NeoRx present but `enabled: false`.

- [ ] **Step 1: Write the failing check** — `actionlint` over `.github/workflows/` and a `tools/tests/test_release_config.py` asserting release-please uses the `linked-versions` plugin across `core/hephkit-core`, `core/hephkit-py`, `python/hephkit` and `go` so all share one version.
- [ ] **Step 2: Run to verify failure** — `actionlint && uv run --with pytest pytest tools/tests/test_release_config.py` → FAIL.
- [ ] **Step 3: Write the workflows.** `ci.yml` runs on every PR: ADR/registry/vector checks, `rust-ci` (test, clippy, `cargo llvm-cov --fail-under-lines 90`), `python-ci` (maturin develop, pytest with coverage gates, mypy strict, `gen_*.py --check`, pip-audit), `go-ci` (test, vet, staticcheck, govulncheck, fragment-sync check), `compose-boot`, image build plus Trivy, CodeQL. `docker-publish.yml` builds, generates a Syft SBOM, and signs with keyless cosign on `main` and releases only.
- [ ] **Step 4: Verify** — `actionlint` clean; test PASS; push a branch and confirm `ci.yml` is green on GitHub.
- [ ] **Step 5: Commit** — `ci: reusable workflows, abi3 wheels, signed images and lockstep releases`

Manual prerequisites for Kelyn (not automatable): create the public repo `Neoforge-Labs/hephaestus`; register a PyPI pending trusted publisher for `hephkit` pointing at `release.yml`; reserve `hephkit-core` on crates.io and the `@hephkit` npm scope.

---

### Task 15: Five-minute path — example app, tutorial and docs site

**Files:**
- Create: `examples/hello/{heph.toml,pyproject.toml,app.py,tests/test_app.py}`, `examples/hello/moon.yml`
- Create: `docs/site/` (Nextra), `docs/site/pages/tutorial/first-five-minutes.mdx`, `tools/gen_error_pages.py`, `tools/dx_budget.sh`

**Interfaces:**
- Consumes: `hephkit` (Tasks 7–10), `heph` CLI (Task 13), fragments (Task 12).
- Produces: `examples/hello` FastAPI app — `GET /price?amount=<str>&currency=<str>` returns `{"price": <money wire>}` and `GET /split?amount=&currency=&ways=` returns `{"parts": [<wire>…]}`; `heph.toml` with `fragments = ["telemetry"]`; one docs page per error code at `/errors/<code>`, generated from `spec/errors.yaml`.

- [ ] **Step 1: Write the failing tests** — `test_app.py`: `/price?amount=10.2&currency=KES` → 200 `{"price": {"amount": "1020", "currency": "KES"}}`; `/price?amount=1,000&currency=KES` → 422 problem+json with `code == "HEPH-MONEY-422"`; `/split?amount=1.00&currency=KES&ways=3` → parts `["34","33","33"]`; a request produces a span with attribute `money.currency == "KES"`. `tools/dx_budget.sh` asserts, on a machine with images pre-pulled, that `heph dev up` in `examples/hello` reaches healthy in under 60 s and that the `hephkit` wheel is under 5 MB.
- [ ] **Step 2: Run to verify failure** — `cd examples/hello && uv run pytest -v` → FAIL.
- [ ] **Step 3: Implement** the app (calls `setup_observability`, `install_error_handlers`), the generator for error pages, and the tutorial: install `heph` and `hephkit`, `heph dev up`, `uv run fastapi dev app.py`, curl `/price`, open Grafana at `http://localhost:54300` → Explore → Tempo and find the trace. Every command in the tutorial is copied into `examples/hello/tutorial_test.sh`, which CI runs.
- [ ] **Step 4: Verify** — tests PASS; `bash examples/hello/tutorial_test.sh` passes and prints the trace id it found via the Tempo API (`curl localhost:54300/api/datasources/proxy/uid/tempo/api/search?tags=service.name%3Dhello`); `bash tools/dx_budget.sh` PASS; `cd docs/site && bun run build` succeeds.
- [ ] **Step 5: Commit** — `docs: five-minute tutorial, hello example, generated error pages`

---

### Task 16: Phase gate — Collie on Hephaestus

**Files (in `cod3smith/autobillr_saas`, branch `work/hephkit-money`):**
- Create: `heph.toml`, `backend/utils/money.py`, `backend/tests/test_hephkit_money.py`
- Modify: `backend/pyproject.toml` (add `hephkit` as an editable path dependency on the local checkout until the first release), `backend/main.py` (call `setup_observability` and `install_error_handlers` at startup), `backend/intelligence/services/chase_engine.py` (compare against `HIGH_VALUE_THRESHOLD` through `Money` instead of raw `Decimal`)

**Interfaces:**
- Consumes: `hephkit.money.Money`, `setup_observability`, `install_error_handlers`, `HephSettings`.
- Produces: `backend/utils/money.py` with `to_money(amount: Decimal, currency: str) -> Money` and `is_high_value(amount: Money) -> bool`.

- [ ] **Step 1: Write the failing test** — `test_hephkit_money.py`: `is_high_value(to_money(Decimal("5000.00"), "KES"))` equals the current `Decimal` comparison result in `chase_engine` (inclusive or exclusive exactly as today — read the existing comparison and assert the same boundary), `is_high_value(to_money(Decimal("4999.99"), "KES")) is False`, and `to_money(Decimal("0.001"), "KES")` raises `MoneyError`.
- [ ] **Step 2: Run to verify failure** — `cd backend && uv run pytest tests/test_hephkit_money.py -v` → FAIL.
- [ ] **Step 3: Implement** the adapter and switch the one comparison; leave every other `Decimal` path untouched in this phase.
- [ ] **Step 4: Verify the gate** — Collie's full suite `uv run pytest` passes unchanged; `heph dev up` (fragments `postgres`, `redis`, `telemetry`, `mail`) reaches healthy; starting the API and hitting one endpoint shows a trace for `service.name=collie` in Grafana at `http://localhost:54300`.
- [ ] **Step 5: Commit in Collie** — `feat: adopt hephkit money and observability` (no AI attribution, per Collie's rule).

---

## Self-review notes

- Spec coverage for Phase 1: heph-spec v0.1 and tutorial first (Tasks 2, 15); moonrepo across cargo/uv/pnpm/Go (Task 1; pnpm/Bun workspaces start empty until Phase 4); docs site (Task 15); reusable CI with trusted publishing (Task 14); first ADRs (Task 1); `hephkit-core` money/hashing/signatures with Python wheels and conformance vectors (Tasks 3–7); errors, settings, observability (Tasks 8–10); base images (Task 11); Compose fragments with otel-lgtm (Task 12); gate (Task 16). The gate needs `heph dev up`, which the spec's rollout otherwise places in Weeks 9–10, so Task 13 pulls a minimal CLI forward; the full CLI (`new`, `add`, `deploy plan`) stays in Weeks 9–10.
- Deliberately out of Phase 1: Go/TS/Rust service kits, WASM and napi bindings, idempotency middleware (spec defined here, built in Weeks 3–4), crates.io publishing (name reserved only).
