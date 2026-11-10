# Hephaestus docs site and landing page — design

**Date:** 2026-11-05
**Status:** awaiting approval (builder check complete, decisions recorded; see
Review notes)
**Parent design:** `docs/superpowers/specs/2026-11-04-hephaestus-design.md` (lines 140, 365, 468)
**Plan slot:** Phase 1, Task 15 (`docs/superpowers/plans/2026-11-04-phase-1-core-and-local-stack.md`)

## Intent and why

Starting a NeoForge product currently costs weeks that have nothing to do with
the product: auth, money, idempotency, telemetry, Compose, CI, and a shadcn
folder that gets copied and then drifts. Hephaestus exists to delete that cost.
The parent design already treats setup time as the headline measurement rather
than a slogan: line 468 writes the tutorial before the code (`heph new`, then
`heph dev up`, then a running app with a trace in Grafana, under five minutes on
a clean machine) and line 45 extends it to a deployed app with auth, billing and
tenants in a day. `tools/dx_budget.sh` turns that into a CI gate: 60 seconds to
healthy, wheel under 5 MB.

So the two sites have two jobs:

- **The landing page** makes that promise legible in about ten seconds, and
  proves it with commands that actually run today plus numbers CI refuses to let
  drift.
- **The docs site** makes the promise true for whoever clicks through.

**Who is reading** (my call, from the brainstorming conversation): Kelyn in six
months casting the next ingot, plus whoever he hands a repo to. Outsiders are
welcome to find it and adopt it — it is MIT, the repo is public, and the
packages are headed for PyPI, crates.io and npm (ADR 0019). We address them in
plain copy, not marketing: while every module is `experimental`, the page
publishes an honest maturity table instead of adopting a pricing-page tone.

## Goals

1. `/` states the promise and proves it above the fold: the commands that work
   today, and the measured budgets.
2. Every claim on the site is either runnable today or explicitly marked as not
   yet built. The roadmap stays visible rather than implied.
3. The docs carry the five-minute path, the module guides, the rendered spec,
   one page per error code, the ADR index and the roadmap.
4. One Nextra app, one build, one domain (`hephkit.dev`), with
   `/r/*.json` reserved for the Phase 4 registry.
5. The site build is a CI gate, so docs cannot rot silently.
6. Nothing on the site is hand-maintained where a generator can derive it from
   `spec/` or `conventions/`.
7. **`/errors/<code>` resolves for every code in the registry.** `heph-spec`
   §1.4 is a MUST, and `hephkit.errors.TYPE_BASE_URL` already ships that URL in
   every problem+json body.

## Non-goals

- Marketing: no SEO campaign, no newsletter, no blog, no testimonials, no
  pricing. (The earlier blanket "courting external adopters" non-goal was
  reversed by ADR 0019; addressing adopters is in scope, marketing is not.)
- Versioned (multi-release) docs, i18n, or a search backend beyond Pagefind.
- The registry JSON itself and the UI component docs — Phase 4.
- Generated API reference for Go, TypeScript or Rust. Phase 1 documents what
  Phase 1 ships: `hephkit` (Python) and the `heph` CLI.

Deploy wiring was a non-goal in the first draft. The builder check killed that:
goal 7 cannot hold without a host, so the site goes live as part of this work
(decision 2 below).

## Anti-goals

These would make the work a failure even if the site builds and looks good:

- The page implying `heph new` works. It does not exist until Weeks 9–10.
- The page printing an install command that does not resolve. `hephkit` is not
  on PyPI, there are no git tags, and there is no install path for the `heph`
  binary. Whatever the hero prints must be a command the tutorial script runs
  and CI executes.
- Copy that drifts from `spec/`: a hand-typed error table, a hand-typed maturity
  table, or budget numbers written twice.
- Error `type` URLs that 404 — a production error body pointing at a dead page
  is worse than no page.
- A second app or a second dependency tree (the rejected approach B below).
- Hand-edited generated pages, which `CLAUDE.md` forbids outright.

## Constraints

- **`CLAUDE.md` rules.** Spec first; generated files (`_codes.py`,
  `conventions.py`, and now the error and convention pages) are never edited by
  hand; maturity levels are enforced; conventional commits; branch
  `work/<topic>`; no AI attribution; local ports in the 54xxx block.
- **The error-page URL is fixed by the spec.** `heph-spec` §1.4 MUSTs
  `https://hephkit.dev/errors/<code>`, §1.8 makes registry entries
  permanent, and `python/hephkit/src/hephkit/errors/__init__.py:17` ships the
  base URL. Generated pages therefore live at `content/errors/<code>.mdx` and
  serve `/errors/<code>`. `reference/` links to them; it does not own them. No
  spec change, no ADR.
- **There is no `money` extra.** `python/hephkit/pyproject.toml` has `fastapi`,
  `settings` and `observability`; money is in the base package. The hero prints
  `uv add hephkit`, not the parent design's aspirational
  `hephkit[money,idempotency,webhooks,auth]`. Inventing an empty alias extra
  would violate "one home per capability".
- **Nothing is published yet, so this work publishes.** No git tags, no
  `hephkit` on PyPI, no `heph` binary. Decision 1 below cuts `0.1` first; the
  hero's commands are only honest once it exists. `heph` installs via
  `go install github.com/Neoforge-Labs/hephaestus/go/cmd/heph@v0.1.0` (my call:
  cheapest path that resolves; release binaries and a tap can come later).
- **Toolchain is pinned.** `.prototools` gives bun 1.4.4 and node 26, and
  ADR 0011 is Bun-centric, so the site builds with bun (not the parent design's
  passing mention of pnpm workspaces).
- **Nextra 4 conventions, not Nextra 2/3.** Nextra 4 serves MDX from
  `content/` through a catch-all `app/[[...mdxPath]]/page.tsx`; the `pages/`
  directory is gone. Static export needs `output: 'export'`,
  `images.unoptimized: true`, and a `postbuild` Pagefind step
  (`pagefind --site .next/server/app --output-path out/_pagefind`).
  **The Phase 1 plan's path `docs/site/pages/tutorial/first-five-minutes.mdx`
  is therefore stale** and becomes
  `docs/site/content/tutorial/first-five-minutes.mdx`. No ADR is needed —
  Nextra was already the recorded decision — but the plan line wants amending in
  the same PR.
- **`ecosystem.yml` already runs the tutorial.** Its `examples/hello` row is
  `enabled: true` at `${{ github.sha }}` with
  `command: bash examples/hello/tutorial_test.sh`, in a job that sets up `uv`
  only — no Rust, no Go, no Docker login. Whatever the tutorial does must run in
  that job, or that job grows the steps it needs.
- **Prerequisites that do not exist yet.** `examples/hello` is unwritten, and
  `compose/` is untracked on `work/phase-1` (the only other dirty path is the
  `.moon/workspace.yml` line that registers it).

## Approaches

### Site structure (decided in conversation)

| | Approach | Trades off |
| --- | --- | --- |
| **A (picked)** | One Nextra app at `docs/site/`; the landing page is its index route with a custom layout, docs in the same tree | One build, one domain, no new ADR, `public/r/` ready for Phase 4. Cost: the hero is written inside a docs theme, so the look stays close to Nextra's |
| B | Separate Next app for the landing page, Nextra for docs | Total freedom on the front page, but two builds, two dependency trees, a rewrite layer for one domain, and it overrides a recorded design decision, so it needs an ADR. Unjustifiable for a single front page that a second app and a rewrite layer would only complicate |
| C | No landing page; the docs index does the job | Cheapest and finishes Task 15 today, but buries the ten-second promise in a tutorial, which is the thing the work is for |

### Front-page direction (decided from mockups)

| | Direction | Trades off |
| --- | --- | --- |
| **A (picked)** | Command first: one promise line, a paste-able block, budgets as three numbers | Spends the first screen proving the setup-time claim in the shortest honest form |
| B | The five-minute path walked as the hero, ending in a Grafana trace | Shows the payoff, but duplicates the tutorial the site already ships |
| C | Sober systems page: a definition and a runs-today/not-yet ledger, no hero | Honest and cheap, but declines to make the argument |

A absorbs C's honesty: the runs-today/not-yet ledger moves below the fold, which
happens regardless of direction.

### Keeping claims from drifting (my call)

The front page asserts numbers and maturity. Three ways to keep that true:

1. Hand-write them in MDX. Cheapest, and exactly the drift `CLAUDE.md` exists to
   prevent.
2. **Single-source them (picked).** Budget thresholds move into
   `tools/dx_budget.json`, read by both `tools/dx_budget.sh` and the site.
   Module maturity moves into `spec/modules.yaml`, rendered into both the
   front-page ledger and `reference/modules`.
3. Generate the whole page from the spec. Over-engineered for one page.

**`spec/modules.yaml` schema** (my call, from the builder check):

```yaml
- name: money
  home: rust            # rust | python | go | ts | compose | docker
  status: shipped       # shipped | planned
  maturity: experimental # required when shipped; experimental | beta | stable
  spec_section: "3"     # heph-spec section number, or null
  phase: 1              # rollout step it lands in
```

`tools/check_modules.py` asserts: every Python submodule under
`python/hephkit/src/hephkit/`, every Rust crate under `core/`, every Go package
under `go/`, every `compose/*.yaml` fragment and every `docker/` image has a
`shipped` entry; `maturity` is one of the three levels and matches the
`maturity:` comment already in each Compose fragment header; `spec_section`,
when non-null, resolves to a real heading in `spec/heph-spec.md`; and `planned`
entries carry a `phase` but no `maturity`. The ledger needs both sides, so
`planned` entries (auth, ledger, outbox, registry, `heph new`) live in the same
file — that is why `status` exists rather than the check demanding every entry be
built.

**Per-code developer guidance** (my call): `spec/errors.yaml` gains a
`guidance:` field, and `tools/gen_error_pages.py` renders `detail_hint` as the
caller-facing detail and `guidance` as the developer section. The file's own
header already promises that prose lives on the generated pages, and a second
hand-written source under `docs/` would be two sources of truth for one code.
This edits the registry schema, so `tools/check_registry.py` and its tests grow
a case, and `gen_errors.py` output must stay byte-identical. No behaviour
changes, so no ADR — but it is a spec-file edit inside this PR, which
`CLAUDE.md` wants said out loud: this is the one.

## What gets built

### Front page (`docs/site/app/page.tsx`, outside the docs layout)

Proposed copy, correctable:

1. **Nav:** `heph` · Docs · Spec · ADRs · GitHub, plus Pagefind search and the
   theme toggle.
2. **Hero line:** "Stop setting up. Start building." One sentence under it: the
   forge every NeoForge product and research project is cast from — money,
   idempotency, webhooks, telemetry and a local stack, already wired.
3. **Proof block:** `uv add hephkit`, then `heph dev up`, with the real healthy
   line as output — verbatim from `examples/hello/tutorial_test.sh`, and
   resolving against the published `0.1` (decision 1).
4. **Three budget tiles** from `tools/dx_budget.json`: under 60 s to healthy,
   wheel under 5 MB, four languages on one spec.
5. **Runs today / not yet**, rendered from `spec/modules.yaml`.
6. **Maturity rule**, one line: nothing below `stable` goes in a money path
   (ADR 0015).
7. **Roadmap**, the seven rollout steps condensed, with "you are here" on
   Phase 1. Phases are named by capability, not by product: the front page does
   not name Collie, Domus, SAWA or NeoRx (my call — they are in the public repo's
   ADRs already, but a public front page naming unreleased products invites
   questions nobody wants to field).
8. **Footer:** MIT, repo, ADR index.

### Docs tree (`docs/site/content/`)

- `index.mdx` — docs home: install per language, where to go next.
- `tutorial/first-five-minutes.mdx` — the CI-verified path. Every command is the
  one `examples/hello/tutorial_test.sh` runs, including Grafana on
  `http://localhost:54300` and the Tempo trace lookup.
- `guides/` — local stack (`heph dev up`), observability, money, errors,
  settings.
- `errors/<code>.mdx` — **generated** by `tools/gen_error_pages.py` from
  `spec/errors.yaml`: title, status, `detail_hint`, `guidance`. Serves the
  spec-mandated `/errors/<code>`. `--check` runs in CI.
- `reference/modules.mdx` — the maturity table from `spec/modules.yaml`.
- `reference/conventions.mdx` — **generated** from `conventions/`.
- `reference/errors.mdx` — an index that links to `/errors/<code>`; it does not
  duplicate the pages.
- `spec/` and `adrs/` — **synced** from `spec/heph-spec.md` and `docs/adr/` by
  the same generator pass, with front-matter added, so the rendered copies
  cannot drift. Synced verbatim: the repo is already public, so the site adds no
  exposure the ADRs do not already have. Marked generated; never hand-edited.
- `roadmap.mdx` — **generated** from the parent design's Rollout section, so the
  most drift-prone copy on the site has one source.
- `public/r/.gitkeep` — route reserved, empty until Phase 4, with a line in the
  docs saying so.

### Build, CI and budgets

- A root `package.json` with bun workspaces and a root `bun.lock`, with
  `docs/site` as its first member, so Phase 4's `@hephkit/*` packages inherit
  the workspace instead of retrofitting one (my call).
- `docs/site/moon.yml` registers a `docs-site` project with `build`, `dev` and
  `check` tasks; `.moon/workspace.yml` gains `docs-site: 'docs/site'` and drops
  the stale bare `docs: 'docs'` entry, which has no `moon.yml`.
- A `docs-site` CI job: `bun install --frozen-lockfile` at the root,
  `bun run build` (static export plus the Pagefind postbuild),
  `python tools/gen_error_pages.py --check`,
  `python tools/check_modules.py`, and an internal-link check that fails if any
  `/errors/<code>` in the registry has no page. The static export uploads as an
  artifact.
- `tools/dx_budget.sh` measures and reports in the existing `compose-boot` job
  and is a hard gate only locally and on a nightly schedule (my call): a
  60-second assertion on a shared GitHub runner would make the number the page
  advertises flaky, and a flaky public number is worse than a slower one. Wheel
  size is measured against the manylinux x86_64 wheel built in
  `rust-wheels.yml`, named as that target on the page.
- The verification commands in `CLAUDE.md` gain the site's `check`.

### Scope boundary

In scope: the Nextra app, the landing page, the docs tree above, the generators
and their `--check` modes, `spec/modules.yaml`, the `guidance:` field,
`tools/dx_budget.json`, the root bun workspace, the moon project and the CI job.
Plus, from the decisions below: cutting the `0.1` release, and the Vercel config
and deploy workflow that put the site on `hephkit.dev`.

Blocking prerequisite, not in scope: Task 12's `compose/` fragments land as
their own commit first (decision 3). The tutorial cannot be verified before
they do, so this work starts after.

**Also in scope, and this is the scope call to argue with:** `examples/hello`
(the FastAPI app, `tests/test_app.py`, `heph.toml`, `tutorial_test.sh`) and
`tools/dx_budget.sh`. They are the rest of Task 15, and the landing page cannot
honestly print a command or a number that no script runs. Cutting them means the
proof block and the tiles become assertions, which is the anti-goal above.

## Decisions (Kelyn, 2026-11-05)

1. **Cut `0.1` first.** The page prints `uv add hephkit` and `heph dev up`
   because both resolve. Consequences: this work tags and publishes `hephkit`
   `0.1` ahead of the site, Kelyn configures the PyPI trusted publisher (nobody
   else can), and `heph` is installed with `go install …/cmd/heph@v0.1.0`. The
   release also unblocks the Phase 1 gate, which needs Collie importing a real
   wheel.
2. **The site goes live.** Vercel config and a deploy workflow are in scope;
   Kelyn creates the Vercel project and points DNS at it. `/errors/<code>` must
   resolve before any service emits a problem+json body in anger.
3. **Task 12 lands first, as its own commit.** `compose/` is a prerequisite,
   not part of this PR.

## Left to the builder

- Component decomposition of the front page, and whether the tiles and the
  ledger become shared MDX components used by both `/` and the docs.
- How much Tailwind to add inside `nextra-theme-docs` versus styling with the
  theme's own tokens. Brand presets are Phase 4, so the page uses the theme's
  defaults plus minimal custom CSS.
- Test and task names, the exact link-checker, and the shape of
  `tools/dx_budget.json` beyond holding the two thresholds.
- Copy polish throughout. The proposed hero lines are a starting point.

## Review notes

A builder check read the first draft. Calls made in response, worth checking
while reading:

- Error pages moved from `reference/errors/<code>` to `/errors/<code>`, because
  spec §1.4 MUSTs that URL and `hephkit` already ships it. This was the check's
  most valuable catch: the first draft would have 404'd every production error
  body.
- `hephkit[money]` corrected to `uv add hephkit`; there is no `money` extra.
- `spec/modules.yaml` given a concrete schema with a `status` field, so the
  front-page ledger can show what is *not* built.
- `guidance:` added to `spec/errors.yaml` rather than a parallel prose source.
- bun layout settled as a root workspace; `dx_budget.sh` made report-only in PR
  CI; roadmap and front page stripped of private product names.
- Deploy moved from non-goal to in scope, and `0.1` from "someday" to a
  prerequisite of the hero copy — both via the decisions above.
- `heph` install path chosen as `go install`, since no release binaries exist.

The check also reported the currency-table work (`spec/currencies.yaml`,
ADR 0017, `tools/gen_currencies.py`) as uncommitted. It is not: those files are
committed on `work/phase-1`, and the only uncommitted paths are `compose/` and
the `.moon/workspace.yml` line that registers it. Nothing in this doc depends on
the currency work either way.
