# hephkit.dev and the mark — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the kit's public address to `hephkit.dev`, record why, and give it a mark — so the site and the repo stop looking anonymous before `hephkit` 0.1 ships.

**Architecture:** Two independent halves that share a PR. The domain half is a normative change: the spec's §1.4 MUST, the constant that implements it, and an ADR, guarded afterwards by a repo-wide test that fails if the old host ever reappears. The brand half is four hand-written SVGs plus a `--check`able raster generator in the shape of the repo's existing generators. Neither half depends on the other, so they can be committed and reviewed separately.

**Tech Stack:** Python 3.12 via `uv` with PEP 723 inline deps (matching `tools/gen_errors.py`); pytest for every task's tests; plain hand-written SVG; `cairosvg` for raster generation only.

**Specs:**
- `docs/superpowers/specs/2026-11-10-hephkit-dev-domain-design.md` (Tasks 1–2)
- `docs/superpowers/specs/2026-11-10-hephkit-logo-design.md` (Tasks 3–4)

**Branch:** a fresh `work/<topic>` branch, per `CLAUDE.md`. This work must land before the docs-site plan's Task 1, which publishes the wheel that bakes the URL in.

## Global Constraints

- Conventional Commits. Branches `work/<topic>`. **No AI attribution** in commit messages, PR bodies or branch names.
- Error codes match `^HEPH-[A-Z]{2,6}-\d{3}$` and live only in `spec/errors.yaml`. No task adds or edits a code.
- Generated files are never hand-edited: `_codes.py`, `conventions.py`, and — new in this plan — every PNG under `docs/site/public/brand/`.
- The repo name and the Go module path `github.com/Neoforge-Labs/hephaestus/go` do not change. Nothing in this plan touches `go/`.
- No deploy token, Vercel token or registrar credential enters this repo.
- Palette is exactly four values: `ink #0C0A09`, `bronze #C2884A`, `bronze-deep #8A5A24`, `paper #F5F0E8`. **`#C2884A` reaches only 3.0:1 on white and must never be the colour on a light background.**
- Green is excluded from this palette: `#4ade80` belongs to Domus, `#0E6944` to NeoHealth.
- `TYPE_BASE_URL` keeps its trailing slash; callers concatenate `TYPE_BASE_URL + code`.

## Review Focus

Five failure modes the specs imply that no obvious task would otherwise test. Each line's test is added to the task that owns the code.

1. **Two marks inlined on one HTML page collide on `mask` id** and one renders as a solid block — the hero and the navbar will both be inline SVG. (Task 3)
2. **`TYPE_BASE_URL` loses its trailing slash** and every problem body emits `.../errorsHEPH-VAL-422`. (Task 1)
3. **The favicon ships as a scaled copy** of the primary mark, so the knocked-out strike closes up at 16px. (Task 3)
4. **An issue form with a wrong top-level key** is silently ignored by GitHub, so the templates never appear and nobody notices. (Task 2)
5. **`#C2884A` used on `paper` or white**, failing contrast at 3.0:1. (Task 3)

---

## File Structure

| File | Responsibility |
| --- | --- |
| `spec/heph-spec.md` | §1.4's normative URL, the example body, the version header |
| `python/hephkit/src/hephkit/errors/__init__.py` | `TYPE_BASE_URL`, the one source of the URL in code |
| `conformance/schema/vector-file.schema.json` | the schema's `$id` |
| `docs/adr/0019-the-public-domain-is-hephkit-dev.md` | why the host changed and why adopters are now courted |
| `tools/tests/test_no_stale_domain.py` | the guard: the old host appears in no tracked file |
| `tools/tests/test_github_meta.py` | `SECURITY.md` and the issue/PR templates are well-formed |
| `tools/tests/test_brand_assets.py` | the SVGs' geometry, distinct mask ids, and the palette's measured contrast |
| `tools/gen_brand_raster.py` | SVG → PNG for the touch icon and social card, with `--check` |
| `docs/site/public/brand/*.svg` | primary mark, favicon cut, avatar, lockup |
| `SECURITY.md`, `.github/ISSUE_TEMPLATE/*`, `.github/PULL_REQUEST_TEMPLATE.md` | the front door for strangers |

---

### Task 1: The domain, and the ADR that explains it

**Files:**
- Create: `tools/tests/test_no_stale_domain.py`, `docs/adr/0019-the-public-domain-is-hephkit-dev.md`
- Modify: `spec/heph-spec.md` (§1.4, the example body, the version header), `python/hephkit/src/hephkit/errors/__init__.py:17`, `python/hephkit/tests/test_errors.py:23`, `conformance/schema/vector-file.schema.json:3`, `docs/superpowers/specs/2026-11-04-hephaestus-design.md` (lines 140, 146 and the "courting external adopters" non-goal), `docs/superpowers/plans/2026-11-04-phase-1-core-and-local-stack.md` (lines 20, 191), `docs/superpowers/specs/2026-11-05-docs-site-and-landing-page-design.md`, `docs/superpowers/plans/2026-11-05-docs-site-and-landing-page.md`, `README.md`

**Interfaces:**
- Produces: `hephkit.errors.TYPE_BASE_URL == "https://hephkit.dev/errors/"`. Every later task and the docs-site plan read the host from here, never from a literal.

- [ ] **Step 1: Write the failing test** — `tools/tests/test_no_stale_domain.py`:

```python
def test_old_host_appears_in_no_tracked_file():
    # git ls-files, read each as utf-8 (skip undecodable), assert the pre-move host string is absent.
    # Allowed exception: docs/adr/0019-*.md, which must name the old host to explain the change.

def test_type_base_url_is_hephkit_dev_and_keeps_its_trailing_slash():
    assert TYPE_BASE_URL == "https://hephkit.dev/errors/"
    assert TYPE_BASE_URL.endswith("/")

def test_composed_type_matches_the_spec_example():
    assert TYPE_BASE_URL + "HEPH-VAL-422" == "https://hephkit.dev/errors/HEPH-VAL-422"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/theforge/Mirror/hephaestus && uv run pytest tools/tests/test_no_stale_domain.py -v`
Expected: all three FAIL — the old host is still in six files.

- [ ] **Step 3: Swap the host in the four normative places**

- `spec/heph-spec.md` §1.4 becomes: ``1.4. `type` MUST be `https://hephkit.dev/errors/<code>`, for example `https://hephkit.dev/errors/HEPH-VAL-422`.``
- the example body's `"type"` becomes `"https://hephkit.dev/errors/HEPH-IDEMP-409"`.
- `errors/__init__.py:17` becomes `TYPE_BASE_URL = "https://hephkit.dev/errors/"`.
- the schema `$id` becomes `"https://hephkit.dev/conformance/vector-file.schema.json"`.
- `test_errors.py:23`'s `TYPE_BASE` becomes the same value.

Bump the spec header to **`0.3.0`** (a MUST changed, so a minor, not a patch) and add one line under "Decisions this version settles": the problem `type` host is `hephkit.dev`.

- [ ] **Step 4: Swap the host in the five documents, and drop the non-goal**

Update lines 140 and 146 of the parent design, lines 20 and 191 of the Phase 1 plan, and both `2026-11-05-*` docs-site files including the `vercel.json` CNAME note — **which becomes an apex A/ALIAS record, not a CNAME**, since the site now sits at the apex. Delete "Courting external adopters" from the parent design's non-goals; add `| Site | hephkit.dev |` to the README's Where/Name table and a `Site: hephkit.dev` line to "Where to look".

- [ ] **Step 5: Write ADR 0019**

`docs/adr/0019-the-public-domain-is-hephkit-dev.md`, with the four headings `tools/check_adrs.py` requires: `## Status`, `## Context`, `## Decision`, `## Consequences`. Context carries the two reasons (a front door, and a portfolio link), the crowded-name evidence, and that the spec was still `0.2.0` Draft with no vector encoding the host. Decision records the host, the apex, the repo name staying for the Go module path, and the reversal of the adopters non-goal. Consequences records that the old host is deleted rather than redirected, and that this had to precede the 0.1 release.

- [ ] **Step 6: Run to verify passage**

Run: `uv run pytest tools/tests/test_no_stale_domain.py -v && cd python/hephkit && uv run pytest tests/test_errors.py -v`
Expected: PASS. Then `uv run python tools/check_adrs.py && uv run python tools/check_vectors.py && uv run python tools/gen_errors.py --check` → all exit 0.

- [ ] **Step 7: Commit**

```bash
git add spec/ python/hephkit/ conformance/ docs/ tools/tests/test_no_stale_domain.py README.md
git commit -m "feat!: move the public host to hephkit.dev"
```

---

### Task 2: A front door for strangers

**Files:**
- Create: `SECURITY.md`, `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/config.yml`, `.github/PULL_REQUEST_TEMPLATE.md`, `tools/tests/test_github_meta.py`
- Modify: none

**Interfaces:**
- Consumes: nothing. Independent of Task 1 and committable before or after it.

- [ ] **Step 1: Write the failing test** — `tools/tests/test_github_meta.py`:

```python
def test_security_md_names_a_reporting_channel_and_a_response_window():
    # SECURITY.md exists; mentions GitHub private vulnerability reporting; states a window in days.

def test_every_issue_form_parses_and_has_githubs_required_top_level_keys():
    # each .github/ISSUE_TEMPLATE/*.yml except config.yml: yaml.safe_load succeeds and
    # has "name", "description" and a non-empty list "body" — a wrong top-level key is
    # accepted silently by GitHub and the form never appears.

def test_pull_request_template_asks_for_the_repos_own_gates():
    # mentions the spec-first rule and that vectors come from independent sources.
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pyyaml pytest tools/tests/test_github_meta.py -v`
Expected: FAIL — none of the files exist.

- [ ] **Step 3: Write the four files**

`SECURITY.md` points at GitHub private vulnerability reporting (no email address, so nothing to rot), states the supported versions as "`0.x`, latest only" and a response window, and says plainly that every module is `experimental` and nothing is yet fit for a production money path. `bug_report.yml` is a GitHub issue *form* with `name`, `description`, `body`; its fields ask for the module, the language binding, the version, and whether the reporter can share a failing vector. `config.yml` sets `blank_issues_enabled: false`. The PR template asks the three questions a check cannot: does the spec change in this PR, where did any new vector come from, and does the maturity label still hold.

- [ ] **Step 4: Run to verify passage**

Run: `uv run --with pyyaml pytest tools/tests/test_github_meta.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add SECURITY.md .github/ tools/tests/test_github_meta.py
git commit -m "docs: add a security policy and issue templates"
```

---

### Task 3: The mark

**Files:**
- Create: `docs/site/public/brand/mark.svg`, `docs/site/public/brand/favicon.svg`, `docs/site/public/brand/avatar.svg`, `docs/site/public/brand/lockup.svg`, `docs/site/public/brand/palette.json`, `tools/tests/test_brand_assets.py`
- Modify: `docs/superpowers/plans/2026-11-05-docs-site-and-landing-page.md` (its Task 4 scaffolds `docs/site/`, which now already exists)

**Interfaces:**
- Produces: the four SVGs and `palette.json` (`{"ink","bronze","bronze-deep","paper"}`), which the docs-site plan's hero and `vercel.json` consume.

- [ ] **Step 1: Write the failing test** — `tools/tests/test_brand_assets.py`:

```python
def test_every_mark_parses_as_xml_and_declares_the_96_viewbox():
    # mark, favicon, avatar: ElementTree.parse succeeds; viewBox == "0 0 96 96".

def test_mask_ids_are_unique_across_every_svg():
    # Collect every id= in all four files. Two marks inlined on one page must not
    # collide, so no id may appear in more than one file, and none may be "a"/"b"/"m".

def test_favicon_is_its_own_drawing_not_a_scaled_mark():
    # favicon.svg's strike path differs from mark.svg's — the cut is fatter by hand.

def test_light_background_assets_never_use_the_light_bronze():
    # "#C2884A" absent from any asset whose background is paper or white.

def test_palette_contrast_meets_the_measured_floors():
    # WCAG relative luminance, computed in the test:
    #   bronze-deep on paper  >= 4.5
    #   bronze on ink         >= 3.0
    #   bronze on white        < 4.5   <- pins WHY bronze-deep exists
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tools/tests/test_brand_assets.py -v`
Expected: FAIL — `docs/site/public/brand/` does not exist.

- [ ] **Step 3: Draw the four assets**

Geometry from the logo design's "Decided", `viewBox="0 0 96 96"`:
plate `<rect x="10" y="10" width="76" height="76" rx="18">`, strike masked out with
`M48 18 L55 41 L78 48 L55 55 L48 78 L41 55 L18 48 L41 41 Z`.

- `mark.svg` — plate in `#C2884A`, for dark backgrounds. Mask id `heph-mark`.
- `favicon.svg` — same composition, **strike redrawn with a visibly fatter cut** so the hole survives 16px. Judge it by looking at it at 16px, not by scaling a number. Mask id `heph-favicon`.
- `avatar.svg` — inverted: solid `#C2884A` plate, strike drawn in `#0C0A09` as a filled path with no mask at all.
- `lockup.svg` — `mark.svg` plus `hephkit` in a generic sans at weight 700, tracking `-0.03em`, as `<text>` with a system stack so no font is embedded or downloaded. Mask id `heph-lockup`.

A light-background variant is not a fifth file: `mark.svg` and `lockup.svg` take `#8A5A24` via a documented one-line fill swap, recorded in `palette.json`.

- [ ] **Step 4: Note the directory in the docs-site plan**

Add one line to that plan's Task 4: `docs/site/public/brand/` already exists, so the Nextra scaffold must merge into the directory rather than refuse or clobber it.

- [ ] **Step 5: Run to verify passage**

Run: `uv run pytest tools/tests/test_brand_assets.py -v`
Expected: PASS, including the three Review Focus tests (unique ids, favicon is its own cut, bronze never on light).

- [ ] **Step 6: Commit**

```bash
git add docs/site/public/brand/ tools/tests/test_brand_assets.py docs/superpowers/plans/2026-11-05-docs-site-and-landing-page.md
git commit -m "feat(brand): add the hephkit mark, favicon, avatar and lockup"
```

---

### Task 4: The raster assets nobody can hand-edit

**Files:**
- Create: `tools/gen_brand_raster.py`, `docs/site/public/brand/apple-touch-icon.png`, `docs/site/public/brand/og-card.png`
- Modify: `CLAUDE.md` (the generator list and the "Verify before you claim" list), `tools/tests/test_brand_assets.py`

**Interfaces:**
- Consumes: Task 3's `avatar.svg` and `lockup.svg`.
- Produces: `python tools/gen_brand_raster.py --check` exiting non-zero when a PNG is stale — the same contract as `gen_errors.py` and `gen_conventions.py`.

- [ ] **Step 1: Write the failing test** — append to `tools/tests/test_brand_assets.py`:

```python
def test_generator_is_deterministic_and_check_detects_staleness():
    # Run the generator twice -> byte-identical PNGs; corrupt one byte -> --check exits 1.

def test_raster_sizes_are_exactly_what_the_platforms_require():
    # apple-touch-icon.png == 180x180; og-card.png == 1200x630 (a wrong ratio is
    # cropped by every social preview, silently).
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tools/tests/test_brand_assets.py -k raster -v`
Expected: FAIL — no generator, no PNGs.

- [ ] **Step 3: Write `tools/gen_brand_raster.py`**

A PEP 723 script with `cairosvg` and `pillow` as inline deps, matching `tools/gen_errors.py`'s shape: a `main()` returning an exit code, and a `--check` flag that regenerates into a temp dir and compares bytes rather than writing. `apple-touch-icon.png` renders `avatar.svg` at 180×180. `og-card.png` composes `lockup.svg` on `#0C0A09` at 1200×630 — lockup only, no command line, since the hero's copy is the docs-site plan's to settle and would go stale here.

- [ ] **Step 4: Run to verify passage**

Run: `uv run pytest tools/tests/test_brand_assets.py -v && uv run tools/gen_brand_raster.py --check`
Expected: PASS, and `--check` exits 0.

- [ ] **Step 5: Record it where the repo's rules live**

Add the generator to `CLAUDE.md`'s generator line and its `--check` to "Verify before you claim"; add the PNGs to the never-hand-edited list.

- [ ] **Step 6: Commit**

```bash
git add tools/gen_brand_raster.py docs/site/public/brand/ tools/tests/test_brand_assets.py CLAUDE.md
git commit -m "feat(brand): generate the touch icon and social card from the SVGs"
```

---

## Self-review

**Spec coverage.** Domain design: goals 1–2 are Task 1 (swap plus the guard test), goal 3 is Task 2, goal 4 is Task 1's ADR. Its "light hygiene only" decision is Task 2, and its `CODE_OF_CONDUCT`/`CITATION.cff` non-goals are honoured by their absence. Logo design: goals 1–2 are Tasks 3–4, goal 3 is Task 3's palette and contrast tests, goal 4 is hand-written SVG throughout. Its "three drawings, not one scaled drawing" is Task 3 Step 3 and pinned by a test.

**Left-to-the-builder items the plan decided**, because the implementer cannot: the spec bumps to `0.3.0`; the social card carries the lockup only; `SECURITY.md` uses GitHub private reporting rather than an address; light backgrounds get a documented fill swap rather than a fifth file. Still genuinely open and correctly left alone: the favicon's exact fatter cut, and `rx="18"` once seen outside a mockup.

**Two things this plan found that the designs did not know.** `docs/site/` does not exist yet, so Task 3 creates it and Task 3 Step 4 warns the docs-site plan's scaffold. And the site now sits at the apex, so that plan's "CNAME" note is wrong — Task 1 Step 4 corrects it to an apex A/ALIAS record.

**Not covered, deliberately.** Registering `hephkit.dev` and creating the Vercel project are Kelyn's, outside the repo. Nothing here verifies the live site; the docs-site plan's Task 10 owns that.
