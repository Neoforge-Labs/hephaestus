# Docs Site and Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `hephkit.dev` — a command-first landing page and the Phase 1 docs — as one Nextra app whose every claim is generated from `spec/` or from the tutorial script CI runs.

**Architecture:** One Nextra 4 app at `docs/site/`, static-exported, with the landing page as its index route and MDX docs under `content/`. Nothing on the site is hand-typed where it can be derived: error pages come from `spec/errors.yaml`, the maturity ledger from `spec/modules.yaml`, the budget tiles from `tools/dx_budget.json`, and the hero's commands from markers inside `examples/hello/tutorial_test.sh`. Python generators own every derived page and all run `--check` in CI, so a stale page fails the build.

**Tech Stack:** Nextra 4 + `nextra-theme-docs` on Next.js App Router, bun 1.4.4 workspaces, Pagefind search, static export to Vercel; Python 3.12 generators via `uv` (PEP 723 inline deps, matching `tools/gen_errors.py`); FastAPI + `hephkit` for `examples/hello`.

**Spec:** `docs/superpowers/specs/2026-11-05-docs-site-and-landing-page-design.md`

## Global Constraints

- Tool versions are pinned and must not be changed: bun 1.4.4, node 26, python 3.12, uv 0.13.6 (`.prototools`); Rust via `rust-toolchain.toml`.
- Error-page URLs are `https://hephkit.dev/errors/<code>` — `heph-spec` §1.4 MUST, already shipped as `hephkit.errors.TYPE_BASE_URL`. Pages live at `docs/site/content/errors/<code>.mdx`; nothing else may own that path.
- Error codes match `^HEPH-[A-Z]{2,6}-\d{3}$` and live only in `spec/errors.yaml`. Registry entries are permanent (§1.8).
- Generated files are never edited by hand: `_codes.py`, `conventions.py`, and every page produced by `gen_error_pages.py` and `gen_site_pages.py`. Each carries a "GENERATED FILE - do not edit by hand" header and a `--check` mode.
- Maturity levels are `experimental`, `beta`, `stable`. New work starts `experimental`; nothing below `stable` goes in a money path.
- Local host ports stay in the 54xxx block: Grafana 54300, OTLP 54317/54318, Postgres 54320, S3 54333, Redis 54379, Mailpit 54025/54825.
- Python generators declare dependencies inline (PEP 723) and run under `uv run`, like every existing tool.
- GitHub Actions are pinned by commit SHA with a version comment, and every `actions/checkout` sets `persist-credentials: false`.
- Conventional Commits; branch `work/docs-site`; no AI attribution in commits, PR bodies or branch names.
- Budget values live only in `tools/dx_budget.json`: 60 seconds to healthy, 5 MB wheel (manylinux x86_64).
- `hephkit` has no `money` extra — money is in the base package. Extras are `fastapi`, `settings`, `observability`.

## Review Focus

Failure modes the design implies that no task's happy path exercises. Each has a test in the task that owns the code.

1. **A code added to `spec/errors.yaml` with no page** — a production problem+json body would 404. Test in Task 5: the link check fails when the registry has a code with no `content/errors/<code>.mdx`.
2. **`tools/dx_budget.json` edited without the page changing** — the page advertises a number CI no longer enforces. Test in Task 8: the built `out/index.html` contains the values read from `dx_budget.json`.
3. **A command in `tutorial_test.sh` changed without the hero changing** — the page prints something no script runs. Test in Task 7: `quickstart.json` is generated from the script's markers, and Task 8 asserts the page renders exactly those lines.
4. **A new Compose fragment or Python submodule with no `spec/modules.yaml` entry** — the maturity ledger silently omits shipped code. Test in Task 2: `check_modules.py` fails on an on-disk module with no entry.
5. **Static export without the Pagefind postbuild** — search returns "failed to load search index" with a green build. Test in Task 4: the build smoke test asserts `out/_pagefind/pagefind.js` exists.

---

### Task 1: Cut the `0.1` release

Everything the landing page prints must resolve, so the release comes first. This task is operational, not TDD: it has a manual prerequisite only Kelyn can do.

**Files:**
- Modify: none. `release-please-config.json` and `.release-please-manifest.json` (already `0.1.0` across all five components) drive it.

**Interfaces:**
- Produces: `hephkit` 0.1.0 on PyPI; tags `v0.1.0` and `go/v0.1.0`; `heph` installable with `go install github.com/Neoforge-Labs/hephaestus/go/cmd/heph@v0.1.0`.

- [ ] **Step 1: Prerequisite (Kelyn, manual)** — configure the PyPI trusted publisher for `hephkit`, pointing at `Neoforge-Labs/hephaestus` and the `release.yml` workflow. Nothing downstream works until this exists; stop and ask rather than working around it.
- [ ] **Step 2: Merge `work/phase-1` to `main`** so release-please opens its release PR. Confirm `compose/` is committed first (Task 12 of the Phase 1 plan — the design's blocking prerequisite).
- [ ] **Step 3: Merge the release PR** and confirm the tags `v0.1.0` and `go/v0.1.0` exist, and that `release.yml` published wheels.
- [ ] **Step 4: Verify** — in an empty directory: `uv venv && uv pip install hephkit==0.1.0 && python -c "import hephkit.money"` → succeeds; `go install github.com/Neoforge-Labs/hephaestus/go/cmd/heph@v0.1.0 && heph version` → prints `0.1.0`. Paste both outputs; if either fails, the hero's copy is still a lie and later tasks must not assume it.

---

### Task 2: `spec/modules.yaml` and `tools/check_modules.py`

**Files:**
- Create: `spec/modules.yaml`, `tools/check_modules.py`, `tools/tests/test_check_modules.py`
- Modify: `.github/workflows/ci.yml` (`repo-checks` job)

**Interfaces:**
- Produces: `check_modules(repo_root: Path) -> list[str]` returning human-readable errors, empty when valid — same shape as `check_errors` in `tools/check_registry.py`. Entry schema: `name`, `home` (`rust|python|go|ts|compose|docker`), `status` (`shipped|planned`), `maturity` (`experimental|beta|stable`, required iff `shipped`), `spec_section` (string or null), `phase` (int, required iff `planned`).
- Consumed by: Task 6 (`gen_site_pages.py` renders `reference/modules`), Task 8 (the front-page ledger).

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_check_modules.py`:
  - `test_registry_is_valid` — `check_modules(REPO_ROOT)` returns `[]`.
  - `test_every_on_disk_module_has_an_entry` — every `python/hephkit/src/hephkit/*.py` submodule (excluding `_`-prefixed and `conventions.py`), every `core/*/` crate, every `go/internal/*/` package, every `compose/*.yaml` and every `docker/<runtime>/` has a `shipped` entry; a temp tree with an extra `compose/kafka.yaml` and no entry returns an error naming `kafka`.
  - `test_maturity_matches_compose_header` — a fragment whose header comment says `maturity: beta` while the entry says `experimental` returns an error naming the fragment.
  - `test_shipped_requires_maturity_planned_requires_phase` — a `shipped` entry without `maturity`, and a `planned` entry with one, both error.
  - `test_spec_section_resolves` — `spec_section: "9"` returns an error, since `spec/heph-spec.md` has sections 1–7.
  - `test_ledger_has_both_sides` — at least one `planned` entry exists, so the front-page ledger cannot render empty.
- [ ] **Step 2: Run to verify failure** — `uv run --with pyyaml pytest tools/tests/test_check_modules.py -v` → FAIL (no module named `check_modules`).
- [ ] **Step 3: Implement** `spec/modules.yaml` and `check_modules.py`. The registry lists, as `shipped`: `money`, `hashing`, `signatures`, `errors`, `settings`, `observability`, the `hephkit-core` and `hephkit-py` crates, the Go CLI and its `internal/*` packages, all six Compose fragments, both base images — each `experimental`, each with its `spec_section` where one exists (money §3, hashing §4, signatures §5, errors §1, telemetry §6) and `null` for `settings`, `observability`, the CLI, the fragments and the images. As `planned`, with phases from the parent design's rollout: `idempotency` (§2) and `auth` phase 2, `ledger`, `outbox`, `webhooks` (§5) and `billing` phase 4, the UI `registry` phase 4, `heph new` phase 5, `lab.repro` (§7) phase 6.
- [ ] **Step 4: Run tests to verify they pass** — same command → PASS.
- [ ] **Step 5: Wire CI** — add `- run: uv run --with pyyaml python tools/check_modules.py` to `repo-checks`, after `check_registry.py`.
- [ ] **Step 6: Commit** — `feat(spec): module inventory with enforced maturity levels`

---

### Task 3: `guidance:` on the error registry

**Files:**
- Modify: `spec/errors.yaml` (all 12 codes), `tools/check_registry.py`, `tools/tests/test_check_registry.py`
- Modify: `spec/heph-spec.md` §1.8 (one sentence: registry entries carry caller-facing `detail_hint` and developer-facing `guidance`)

**Interfaces:**
- Produces: every registry entry gains a non-empty `guidance` string. Consumed by Task 5.

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_check_registry.py`:
  - `test_every_code_has_guidance` — every entry has a non-empty `guidance`.
  - `test_guidance_differs_from_detail_hint` — the two strings are never equal, so caller copy cannot be pasted into the developer section.
  - `test_guidance_required` — an entry without `guidance` returns an error naming the code.
- [ ] **Step 2: Run to verify failure** — `uv run --with pyyaml pytest tools/tests/test_check_registry.py -v` → FAIL.
- [ ] **Step 3: Implement** — add `guidance` to the 12 codes (`HEPH-GEN-500`, `HEPH-VAL-422`, `HEPH-NF-404`, `HEPH-AUTH-401`, `HEPH-AUTH-403`, `HEPH-RATE-429`, `HEPH-IDEMP-400`, `HEPH-IDEMP-409`, `HEPH-IDEMP-422`, `HEPH-MONEY-422`, `HEPH-MONEY-409`, `HEPH-WH-401`) and the validation to `check_errors`. Write `guidance` to the implementer: what causes the code, what to change. The registry header already says this prose belongs on the generated pages — update that comment to name the field.
- [ ] **Step 4: Run tests and the generator check** — tests PASS; `uv run tools/gen_errors.py --check` → exit 0 (the constants file is unaffected, and must stay byte-identical).
- [ ] **Step 5: Commit** — `feat(spec): developer guidance per error code`

---

### Task 4: Nextra app scaffold, bun workspace and moon project

**Files:**
- Create: `package.json`, `bun.lock`, `docs/site/package.json`, `docs/site/next.config.mjs`, `docs/site/mdx-components.tsx`, `docs/site/tsconfig.json`, `docs/site/app/layout.tsx`, `docs/site/app/[[...mdxPath]]/page.tsx`, `docs/site/content/index.mdx`, `docs/site/content/_meta.ts`, `docs/site/moon.yml`, `docs/site/public/r/.gitkeep`
- Modify: `.moon/workspace.yml`, `.gitignore`

**Interfaces:**
- Produces: `bun run --cwd docs/site build` → static export in `docs/site/out/`, including `out/_pagefind/pagefind.js`. moon project `docs-site` with `build`, `dev` and `check` tasks.
- Consumed by: Tasks 5–8 write MDX into `docs/site/content/`.

- [ ] **Step 1: Write the failing smoke test** — `docs/site/tests/build.test.ts` (bun test): after a build, `out/index.html` exists and contains the string `heph`; `out/_pagefind/pagefind.js` exists; `out/errors/` is absent for now. Name it `test_static_export_includes_search_index`.
- [ ] **Step 2: Run to verify failure** — `bun test --cwd docs/site` → FAIL (no build output).
- [ ] **Step 3: Implement** the scaffold. Root `package.json` declares `workspaces: ["docs/site"]` and nothing else; the lockfile lives at the root. `next.config.mjs` sets `output: 'export'` and `images.unoptimized: true` (mandatory for export) and wraps the config in `nextra({})`. `docs/site/package.json` scripts: `build` → `next build`, `postbuild` → `pagefind --site .next/server/app --output-path out/_pagefind`, `dev` → `next dev`. `app/layout.tsx` renders `nextra-theme-docs`' `Layout` with `Navbar` (links: Docs, Spec, ADRs, GitHub), `getPageMap()`, `docsRepositoryBase` pointing at this repo's `docs/site`, and a `Footer` reading `MIT © NeoForge Labs`. `app/[[...mdxPath]]/page.tsx` is the catch-all from Nextra's content-directory convention (`generateStaticParamsFor('mdxPath')`, `importPage`). Add `docs/site/out/` and `docs/site/.next/` to `.gitignore`. In `.moon/workspace.yml`, add `docs-site: 'docs/site'` and delete the stale bare `docs: 'docs'` entry, which has no `moon.yml`.
- [ ] **Step 4: Run the test to verify it passes** — `bun run --cwd docs/site build && bun test --cwd docs/site` → PASS.
- [ ] **Step 5: Commit** — `feat(docs): nextra site scaffold with static export`

---

### Task 5: Generated error pages

**Files:**
- Create: `tools/gen_error_pages.py`, `tools/tests/test_gen_error_pages.py`, `docs/site/content/errors/_meta.ts`, `docs/site/content/reference/errors.mdx`
- Generated: `docs/site/content/errors/HEPH-*.mdx` (12 files, committed)

**Interfaces:**
- Consumes: `spec/errors.yaml` including `guidance` (Task 3); `check_errors` from `tools/check_registry.py`.
- Produces: `generate(repo_root: Path) -> dict[Path, str]` mapping output path to content, and a `--check` mode exiting 1 on drift — the same contract as `tools/gen_errors.py`.

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_gen_error_pages.py`:
  - `test_one_page_per_code` — `generate(REPO_ROOT)` has exactly one entry per registry code, at `docs/site/content/errors/<code>.mdx`, so the URL is `/errors/<code>` as §1.4 requires.
  - `test_page_contains_registry_fields` — the `HEPH-IDEMP-409` page contains its title, `409`, its `detail_hint` verbatim and its `guidance` verbatim.
  - `test_pages_carry_generated_header` — every page starts with a comment naming `spec/errors.yaml` and saying not to edit by hand.
  - `test_check_detects_drift` — mutating one committed page makes `--check` exit 1 and name that file.
  - `test_output_is_deterministic` — two calls produce identical bytes (no timestamps).
  - `test_every_registry_code_has_a_committed_page` — **Review Focus 1**: the committed `content/errors/` set equals the registry's code set; a registry code with no file fails.
- [ ] **Step 2: Run to verify failure** — `uv run --with pyyaml pytest tools/tests/test_gen_error_pages.py -v` → FAIL.
- [ ] **Step 3: Implement** the generator and run it to write the 12 pages. Each page: front-matter `title: <code> — <title>`, then the status, the caller-facing `detail_hint`, the developer `guidance`, and a link back to `spec/heph-spec.md` §1. Write `content/reference/errors.mdx` as a hand-written index that links to all twelve by code; `content/errors/_meta.ts` orders them by registry order.
- [ ] **Step 4: Run tests to verify they pass** — same command → PASS; `uv run tools/gen_error_pages.py --check` → exit 0.
- [ ] **Step 5: Commit** — `feat(docs): generate one page per error code`

---

### Task 6: Generated conventions, spec, ADR and roadmap pages

**Files:**
- Create: `tools/gen_site_pages.py`, `tools/tests/test_gen_site_pages.py`
- Generated: `docs/site/content/reference/conventions.mdx`, `docs/site/content/reference/modules.mdx`, `docs/site/content/spec/index.mdx`, `docs/site/content/adrs/<nnnn>-<slug>.mdx` + `_meta.ts`, `docs/site/content/roadmap.mdx`

**Interfaces:**
- Consumes: `conventions/attributes.yaml`, `spec/heph-spec.md`, `spec/modules.yaml` (Task 2), `docs/adr/*.md`, the parent design's Rollout section.
- Produces: `generate(repo_root: Path) -> dict[Path, str]` and `--check`, same contract as Task 5.

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_gen_site_pages.py`:
  - `test_conventions_page_lists_every_attribute` — every name in `conventions/attributes.yaml` appears, and `user.id` is marked PII.
  - `test_modules_page_splits_shipped_and_planned` — the page has both a shipped table with maturity and a planned table with phases.
  - `test_adr_pages_match_sources` — one page per `docs/adr/NNNN-*.md` except `0000-template.md`; each page's body is its source's body unchanged; `_meta.ts` orders them numerically.
  - `test_roadmap_derives_from_the_design` — the seven rollout steps appear in order, and no page in the output contains `Collie`, `Domus`, `SAWA` or `NeoRx` (the design's call: phases are named by capability).
  - `test_check_detects_drift` — adding an ADR without regenerating makes `--check` exit 1.
- [ ] **Step 2: Run to verify failure** — `uv run --with pyyaml pytest tools/tests/test_gen_site_pages.py -v` → FAIL.
- [ ] **Step 3: Implement** the generator and run it. Sync pages carry front-matter plus the generated-file header; ADR bodies are copied verbatim (the repo is public, so no redaction is needed) with relative links rewritten to site paths.
- [ ] **Step 4: Run tests and build** — tests PASS; `uv run tools/gen_site_pages.py --check` → exit 0; `bun run --cwd docs/site build` → succeeds with the new pages.
- [ ] **Step 5: Commit** — `feat(docs): generate convention, module, spec, ADR and roadmap pages`

---

### Task 7: `examples/hello`, the tutorial script and the budget gate

**Files:**
- Create: `examples/hello/{heph.toml,pyproject.toml,app.py,moon.yml}`, `examples/hello/tests/test_app.py`, `examples/hello/tutorial_test.sh`, `tools/dx_budget.json`, `tools/dx_budget.sh`, `tools/gen_quickstart.py`, `tools/tests/test_gen_quickstart.py`
- Create (generated): `docs/site/content/tutorial/first-five-minutes.mdx`, `docs/site/content/_snippets/quickstart.json`
- Modify: `docs/superpowers/plans/2026-11-04-phase-1-core-and-local-stack.md` (Task 15's stale `docs/site/pages/...` path)

**Interfaces:**
- Consumes: `hephkit==0.1.0` with the `fastapi` and `observability` extras (Task 1); `heph dev up` from the CLI; the `telemetry` fragment.
- Produces: `GET /price?amount=&currency=` → `{"price": {"amount": "<minor units>", "currency": "<code>"}}`; `GET /split?amount=&currency=&ways=` → `{"parts": [...]}`; `heph.toml` with `[ingot] name = "hello"` and `[dev] fragments = ["telemetry"]`; `quickstart.json` as `{"commands": [...], "output": "..."}` extracted from the script's `# >>> quickstart` / `# <<< quickstart` markers.

- [ ] **Step 1: Write the failing tests** — `examples/hello/tests/test_app.py`:
  - `/price?amount=10.2&currency=KES` → 200 `{"price": {"amount": "1020", "currency": "KES"}}`
  - `/price?amount=1,000&currency=KES` → 422 problem+json with `code == "HEPH-MONEY-422"` and `type == "https://hephkit.dev/errors/HEPH-MONEY-422"`
  - `/split?amount=1.00&currency=KES&ways=3` → `parts == ["34","33","33"]`
  - a request emits a span carrying `money.currency == "KES"`
  And `tools/tests/test_gen_quickstart.py`: `test_commands_come_from_the_script` — the extracted commands equal the lines between the markers in `tutorial_test.sh`; `test_marker_missing_is_an_error`; `test_check_detects_drift`.
- [ ] **Step 2: Run to verify failure** — `cd examples/hello && uv run pytest -v` → FAIL; `uv run pytest tools/tests/test_gen_quickstart.py -v` → FAIL.
- [ ] **Step 3: Implement** the app (calling `setup_observability` and `install_error_handlers` from `hephkit`), `tutorial_test.sh`, `tools/dx_budget.json` (`{"boot_seconds": 60, "wheel_mb": 5, "wheel_target": "manylinux x86_64"}`), `tools/dx_budget.sh` (reads the JSON; `--enforce` fails on breach, otherwise reports), and `gen_quickstart.py`. The tutorial page is generated from the same markers, so page and script cannot disagree. Inside the markers, the commands are `uv add "hephkit[fastapi,observability]"` and `heph dev up` — **note:** the design says the hero prints `uv add hephkit`, but the example needs both extras, and the design's stronger rule is that the hero is verbatim from this script. The extras form wins; the design's line is the one to correct.
- [ ] **Step 4: Verify** — `cd examples/hello && uv run pytest -v` → PASS; `bash examples/hello/tutorial_test.sh` → passes and prints the trace id it found via `curl localhost:54300/api/datasources/proxy/uid/tempo/api/search?tags=service.name%3Dhello`; `bash tools/dx_budget.sh` → reports both numbers; `bash tools/dx_budget.sh --enforce` → PASS locally with images pre-pulled.
- [ ] **Step 5: Commit** — `feat(examples): hello app, five-minute tutorial and DX budget`

---

### Task 8: The landing page

**Files:**
- Create: `docs/site/app/(home)/page.tsx`, `docs/site/app/(home)/layout.tsx`, `docs/site/components/{ProofBlock,BudgetTiles,ModuleLedger,RoadmapStrip}.tsx`, `docs/site/tests/landing.test.ts`
- Modify: `docs/site/content/index.mdx` (becomes the *docs* home, not the site root)

**Interfaces:**
- Consumes: `docs/site/content/_snippets/quickstart.json` (Task 7), `tools/dx_budget.json` (Task 7), `spec/modules.yaml` (Task 2) — all imported at build time, never retyped.
- Produces: the site root, outside the docs layout, in its own route group so the hero is not wrapped in the sidebar chrome.

- [ ] **Step 1: Write the failing tests** — `docs/site/tests/landing.test.ts`, run against the built `out/index.html`:
  - `test_proof_block_matches_the_tutorial_script` — **Review Focus 3**: every command in `quickstart.json` appears verbatim.
  - `test_budget_tiles_match_dx_budget_json` — **Review Focus 2**: the rendered page contains `60` and `5 MB` as read from the JSON, not as literals in the component.
  - `test_ledger_shows_both_sides` — a shipped module and a planned one both appear, each with its maturity or phase.
  - `test_page_does_not_claim_heph_new` — the string `heph new` appears only inside the roadmap's planned section.
  - `test_no_private_product_names` — `Collie`, `Domus`, `SAWA`, `NeoRx` are absent.
- [ ] **Step 2: Run to verify failure** — `bun run --cwd docs/site build && bun test --cwd docs/site` → FAIL.
- [ ] **Step 3: Implement** the page in the order the design fixes: nav; hero line "Stop setting up. Start building." with the one-sentence subhead; `ProofBlock`; `BudgetTiles`; `ModuleLedger` (runs today / not yet); the one-line maturity rule citing ADR 0015; `RoadmapStrip` with "you are here" on Phase 1; footer. Styling uses the theme's own tokens plus minimal custom CSS — brand presets are Phase 4.
- [ ] **Step 4: Run the tests to verify they pass** — same command → PASS.
- [ ] **Step 5: Commit** — `feat(docs): command-first landing page`

---

### Task 9: Docs home and the five guides

The only substantial hand-written prose on the site. It comes after the landing page so the guides can link the components the hero already proves, and before CI so the link check has nothing dangling to find.

**Files:**
- Modify: `docs/site/content/index.mdx` (the docs home, stubbed in Task 4)
- Create: `docs/site/content/guides/{local-stack,observability,money,errors,settings}.mdx`, `docs/site/content/guides/_meta.ts`, `docs/site/tests/guides.test.ts`

**Interfaces:**
- Consumes: the generated pages from Tasks 5 and 6 (guides link to `/errors/<code>` and `/reference/conventions`, never restating their content); `examples/hello` (Task 7) for runnable snippets.
- Produces: the pages the docs home and the landing page's nav link to.

- [ ] **Step 1: Write the failing tests** — `docs/site/tests/guides.test.ts`, against the built `out/`:
  - `test_every_guide_is_reachable_from_the_docs_home` — `out/index.html` for the docs home links all five guides.
  - `test_guides_link_generated_pages_rather_than_restating` — the errors guide links `/errors/HEPH-MONEY-422` and does not inline its `detail_hint`; the observability guide links `/reference/conventions` and does not list attribute names.
  - `test_no_guide_claims_an_unbuilt_module` — no guide mentions `ledger`, `outbox`, `auth` or `heph new` outside a sentence naming it as planned.
- [ ] **Step 2: Run to verify failure** — `bun run --cwd docs/site build && bun test --cwd docs/site` → FAIL.
- [ ] **Step 3: Implement** the five guides, each opening with a runnable snippet taken from `examples/hello` and each ending with a link to the generated reference it relies on: **local-stack** (`heph dev up`, the fragments, the 54xxx ports, `heph doctor`), **observability** (`setup_observability`, finding a trace in Grafana at `http://localhost:54300`, the attribute conventions), **money** (integer minor units, strict ASCII parsing, `/price` and `/split` from the example, why floats never touch money), **errors** (problem+json shape, the `type` URL contract from §1.4, `install_error_handlers`), **settings** (fail-fast settings, prod-required secrets). Rewrite `content/index.mdx` as the docs home: install per language, then where to go next.
- [ ] **Step 4: Run the tests to verify they pass** — same command → PASS.
- [ ] **Step 5: Commit** — `docs: module guides and docs home`

---

### Task 10: CI, deploy and the repo's own docs

**Files:**
- Create: `.github/workflows/docs-ci.yml`, `docs/site/vercel.json`
- Modify: `.github/workflows/ci.yml`, `.github/workflows/compose-boot.yml`, `CLAUDE.md`, `README.md`

**Interfaces:**
- Consumes: every generator's `--check` from Tasks 2, 3, 5, 6, 7; the built `out/` from Tasks 4–9.
- Produces: a `docs` job in `ci.yml`; `compose-boot.yml` gains a `workflow_call` input `enforce-budget` (boolean, default `false`).

- [ ] **Step 1: Write the failing test** — extend `tools/tests/test_release_config.py` (which already asserts CI shape) with `test_docs_job_runs_every_generator_check`: `ci.yml` has a `docs` job, and `docs-ci.yml` runs `gen_error_pages.py --check`, `gen_site_pages.py --check`, `gen_quickstart.py --check` and the site build.
- [ ] **Step 2: Run to verify failure** — `uv run --with pyyaml pytest tools/tests/test_release_config.py -v` → FAIL.
- [ ] **Step 3: Implement** — `docs-ci.yml`: checkout with `persist-credentials: false`, `oven-sh/setup-bun` pinned by SHA at 1.4.4, `bun install --frozen-lockfile` at the root, the four checks above, `bun test --cwd docs/site`, an internal-link check over `docs/site/out/` that fails on any relative href with no file behind it (the design's link check; Task 5 already covers the `/errors/<code>` set specifically), and upload `docs/site/out` as an artifact. In `ci.yml`, add `docs: uses: ./.github/workflows/docs-ci.yml`, and pass `enforce-budget: ${{ github.event_name == 'schedule' }}` to `compose-boot`, which runs `tools/dx_budget.sh` with `--enforce` only when true — a 60-second assertion on a shared runner would otherwise make the advertised number flaky. Add `docs/site/vercel.json` and document the project settings Kelyn must create (root directory `docs/site`, build command `bun run build`, output directory `out`, plus an apex A or ALIAS record for `hephkit.dev` (not a CNAME: the site sits at the apex, and an apex cannot be a CNAME)); the Git integration builds it, so no deploy token is added to this repo.
- [ ] **Step 4: Verify** — tests PASS; `uv run tools/gen_error_pages.py --check && uv run tools/gen_site_pages.py --check && uv run tools/gen_quickstart.py --check` → all exit 0; `bun run --cwd docs/site build && bun test --cwd docs/site` → PASS.
- [ ] **Step 5: Update the repo's docs** — add the site's `check` and build to `CLAUDE.md`'s "Verify before you claim" list; add the site URL to `README.md`'s "Where to look"; amend the Phase 1 plan's Task 15 to point at `content/` rather than the stale `pages/`.
- [ ] **Step 6: Commit** — `ci(docs): build, check and deploy the docs site`

---

## Self-review notes

- **Spec coverage.** Goals 1–7 map to tasks: the command-first front page and its proof (Task 8), honest claims and the roadmap (Tasks 2, 6, 8), the docs tree (Tasks 4–7 and 9), one app and one domain (Tasks 4, 10), the CI gate (Task 10), nothing hand-maintained (Tasks 5, 6, 7), and `/errors/<code>` resolving (Tasks 5, 10). The design's three decisions map to Task 1 (release), Task 10 (deploy) and the Task 1 Step 2 check (Task 12 lands first). The first pass of this plan had no task for the design's `guides/` tree or the docs home — that gap is now Task 9. Everything the design left to the builder — component decomposition, Tailwind versus theme tokens, the link checker's implementation, `dx_budget.json`'s shape beyond the two thresholds, copy polish — is left open here too.
- **Interface consistency.** Every generator exposes `generate(repo_root) -> dict[Path, str]` plus `--check`, matching `tools/gen_errors.py`. `check_modules(repo_root) -> list[str]` matches `check_errors`. Page paths are written once, in the task that generates them, and referenced by path elsewhere.
- **Review Focus coverage.** All five lines have a named test in the owning task: 1 → Task 5, 2 and 3 → Task 8 (sourced in Task 7), 4 → Task 2, 5 → Task 4.
- **Known deviation from the design**, flagged in Task 7 Step 3: the hero prints `uv add "hephkit[fastapi,observability]"`, not `uv add hephkit`, because the example needs both extras and the design's stronger rule is that the hero matches the script verbatim.
- **Proportion.** Ten tasks, no function bodies, test names and assertions in place of test code where the assertion is the decision. The plan is about as long as the design it implements, which is the right order of magnitude.
