# CLAUDE.md — Hephaestus

Standing context for every session in this repo. Read it fully before starting.
If something you are about to do conflicts with this file or with the design,
stop and say so rather than working around it.

## What this repo is

Hephaestus (`heph`) is NeoForge Labs' full-stack kit: the forge every NeoForge
product and research project is built from. Each project it creates is an
**ingot**. It spans Rust, Go, Python, TypeScript, Terraform, Compose and CI.

- Design (source of truth): `docs/superpowers/specs/2026-11-04-hephaestus-design.md`
- Current plan: `docs/superpowers/plans/` (newest file wins)
- Decisions: `docs/adr/` — numbered, never edited after acceptance; supersede instead

## Non-negotiable rules

1. **Spec first.** Behaviour is defined in `spec/heph-spec.md` and pinned by
   `conformance/` vectors before any implementation exists. Changing behaviour
   means changing the spec and vectors in the same PR, plus an ADR if a
   decision changed.
2. **Vectors come from independent sources.** Never generate or "fix" a vector
   by running our own implementation. Sources are RFCs, reference packages
   (`standardwebhooks`, `rfc8785`) or hand-derived values. If our code disagrees
   with a vector, the code is wrong until proven otherwise.
3. **One home per capability.** Each capability has one home language and one
   spec. Other languages bind to the Rust core, use a thin service kit, or call
   it as a service. Never hand-port logic between languages.
4. **The Rust core does no I/O**, holds no global state, never panics on input,
   and returns `Result` everywhere.
5. **Money is integer minor units.** Floating point never touches money. Parsing
   is strict ASCII and rejects excess precision unless a rounding mode is given.
6. **Correctness modules stay relational.** Money, ledger, audit, outbox,
   idempotency and auth require SQL transactions and constraints.
7. **Maturity levels are enforced.** Every module is `experimental`, `beta` or
   `stable` (criteria in the design). New work starts `experimental`. Nothing
   in a production money path may be below `stable`.
8. **Adopt before building.** Check the Adopt-or-build table before writing a
   commodity component (auth, outbound webhooks, workflows, eval runners,
   monorepo tooling, migrations, brokers).
9. **IP boundary.** Code from DataQRL and Backbone is not ours to copy. Patterns
   learned there are rewritten from scratch. Harvest only from NeoForge and
   cod3smith repos.

## Layout

```
spec/            heph-spec, error registry (errors.yaml)
conventions/     telemetry attribute names (generates per-language constants)
conformance/     JSON vectors shared by every implementation
core/            Rust: hephkit-core, hephkit-py (PyO3), fuzz targets
python/hephkit/  Python package (maturin, abi3-py312)
go/              heph CLI, Go service kit
packages/        @hephkit/* TypeScript packages
registry/        shadcn-format UI components and brand presets
docker/ compose/ terraform/   infrastructure
templates/       Copier templates (saas, research)
docs/            ADRs, specs, plans, Nextra site
tools/           repo checks and generators (all have tests)
examples/hello/  the five-minute path; CI runs its tutorial verbatim
```

## Verify before you claim

Run the checks for what you touched and read the output. Paste failures, don't
summarise them away. Done means green.

- Rust: `cargo test -p hephkit-core && cargo clippy --all-targets -- -D warnings && cargo llvm-cov -p hephkit-core --fail-under-lines 90`
- Python: `cd python/hephkit && uv run maturin develop --uv && uv run pytest --cov=hephkit && uv run mypy --strict src`
- Go: `cd go && go test ./... && go vet ./... && staticcheck ./...`
- Generators: `python tools/gen_errors.py --check && python tools/gen_conventions.py --check && uv run tools/gen_brand_raster.py --check`
  (The brand-raster `--check` is the enforced gate and runs in `tools/tests`: it hashes
  the brand SVGs, `palette.json` and the two PNGs against `tools/brand-provenance.txt`.
  It is platform-independent because text rasterisation is not. `--check-render`
  re-renders and compares bytes; it is a local convenience that can differ across platforms.)
- Repo checks: `python tools/check_adrs.py && python tools/check_registry.py && python tools/check_vectors.py`
- Local stack: `bash compose/test/boot_test.sh`
- Five-minute path: `bash examples/hello/tutorial_test.sh`

## Conventions

- Conventional Commits; branches `work/<topic>`.
- No AI attribution in commits, PR bodies or branch names.
- Local host ports use the 54xxx block (Grafana 54300, OTLP 54317/54318,
  Postgres 54320, S3 54333, Redis 54379, Mailpit 54025/54825).
- Error codes match `^HEPH-[A-Z]{2,6}-\d{3}$` and live only in `spec/errors.yaml`.
- Generated files (`_codes.py`, `conventions.py`, synced Compose fragments, and
  the brand PNGs `apple-touch-icon.png` and `og-card.png`) are never edited by
  hand. After editing a brand SVG or `palette.json`, run
  `uv run tools/gen_brand_raster.py` and commit the PNGs with the updated
  `tools/brand-provenance.txt`.
- Every new module ships with: spec section, vectors or contract tests, a docs
  page with a runnable example, a maturity label, and an entry in ecosystem CI
  once an ingot uses it.

## When you're unsure

If the design or the plan doesn't answer a question that changes what gets
built, stop and ask. Don't invent an answer and build on it.
