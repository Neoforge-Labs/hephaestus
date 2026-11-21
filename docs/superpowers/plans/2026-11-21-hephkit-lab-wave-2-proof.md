# hephkit.lab Wave 2 — Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive a causal analysis end to end through the shipped integrity spine — honest inputs, identification, estimation, refutation and multi-seed statistics — so the spine's contract is proven by a running analysis before the remaining eleven modules lean on it.

**Architecture:** Four modules are added to the existing `hephkit-lab` distribution: `lab.data` and `lab.sources` make inputs honest (content-addressed manifests with a specified digest scope, date-to-release resolution, a frozen response cache), `lab.causal` adopts CausalPhylo for identification and DoWhy for estimation and refutation, and `lab.stats` supplies effect sizes, test selection and bootstrap intervals. Each sits behind the extra named in design §7.1.2, so the spine still installs with no scientific stack. A second fixture in `examples/lab-causal/` runs a SAWA-shaped analysis (DAG → estimate → refute, synthetic data) through `lab.record` and `lab.replay`, and its gate script joins `examples/lab-replay/`'s on every pull request.

**Tech Stack:** Python 3.12, pydantic 2, pytest, mypy --strict, networkx, causalphylo, dowhy, causal-learn, scipy, polars, duckdb, dvc, moon.

**Spec:** `docs/superpowers/specs/2026-11-12-hephkit-lab-research-core-design.md` (wave 2 of §12; §8.2 and §8.3 for the modules, §9.2 for spec §10, §9.3 for which suites are vectored and which are contract-tested, §10 for ADR 0025, §11 for the gate)

**Scope:** Wave 2 of the design's §12 only — `lab.data`, `lab.sources`, `lab.causal`, `lab.stats`, spec §10, ADR 0025, and the causal fixture through the in-repo gate. Waves 3–5 (`lab.bench`, `lab.flows`, `lab.notebook`, `lab.train`, `lab.embed`, `lab.rl`, `lab.paper`, `lab.lit`, `lab.bio`) get their own plans. Done means the gate of §11 passes on a fixture causal analysis, **not** that SAWA itself has been re-run, which §11 puts out of scope.

## Global Constraints

- Python `>=3.12`. `mypy --strict` passes on all source.
- Coverage gate: `--cov-fail-under=90` on `hephkit.lab`, unchanged.
- No new hashing. Every content hash comes from `hephkit.hashing.content_hash` (RFC 8785 JCS + SHA-256, spec §4.2). Per-file byte digests are plain SHA-256 and are *inputs* to a content hash, never a second hashing scheme (Task 2 states the composition).
- Error codes match `^HEPH-[A-Z]{2,6}-\d{3}$` and live only in `spec/errors.yaml`. The four `LAB` codes already exist; add a new one only when a module needs one, never speculatively.
- Every module carries `Maturity: experimental.` in its module docstring and a matching row in `spec/modules.yaml`, **in the same commit as the module** — `tools/check_modules.py` fails on a module on disk with no row.
- Generated files are never hand-edited: `_codes.py`, `conventions.py`, `go/internal/fragments/files/`, docs-site pages, `_snippets/site-data.json`.
- Conventional Commits. Branch `work/<topic>`. **No AI attribution** in commit messages, PR bodies or branch names.
- Local host ports come from the 54xxx block. Nothing in this wave opens a port; the S3 remote at 54333 is not a dependency of any task (Task 5 says why).
- Vectors are never produced by running our own implementation (CLAUDE.md rule 2). The three vectored suites of this wave are hand-derived: `lab.manifest` from spec §10 as written in Task 1, `lab.effects` from the published formulae quoted in Task 11, `lab.selection` from the decision table written in Task 12.
- Conformance suite names are **two segments** — `<directory>.<stem>` — because `tools/check_vectors.py` derives the expected suite as `f"{path.parent.name}.{path.stem}"`. The design's `lab.stats.effects` and `lab.stats.tests` are therefore impossible; this wave uses `lab.manifest`, `lab.effects` and `lab.selection`, all under `conformance/lab/`, which is the directory `python/hephkit/tests/test_conformance.py` already exempts from needing a zero-dependency runner.
- The spine's no-dependency promise holds: `python/hephkit-lab/tests/test_package.py::test_spine_declares_no_heavy_dependencies` must keep passing, so nothing this wave adds may reach `[project.dependencies]`. `networkx`, `dowhy`, `causal-learn`, `scipy`, `polars`, `duckdb` and `dvc` live in the extras that already declare them.
- Every new module imports its heavy library **inside the function that needs it**, behind `except ImportError`, and raises `MissingExtraError` naming the extra to install. A module-scope import would break `import hephkit.lab.<module>` in a spine-only environment, which Task 15's import probe asserts.

### Precondition: CausalPhylo's licence

`causalphylo` 0.1.0 on PyPI is `LicenseRef-CausalPhylo-NonCommercial`, and `hephkit-lab` is MIT. **Decided by the user: CausalPhylo is relicensed MIT, and that is a precondition of adopting it.** So:

- Task 7 writes ADR 0025 and bumps the pin to the first MIT release of `causalphylo`.
- Task 7 also adds the enforcing test, so the precondition cannot be lost to a future resolution: the installed distribution's `License-Expression` must be `MIT`.
- Tasks 1–6 and 11–13 do not depend on `causalphylo` at all. **If the MIT release has not landed when Task 7 is reached, stop and raise it** rather than pinning the non-commercial version or vendoring the algorithm. Tasks 8–10 and 14 are blocked behind it; the rest of the wave is not.

## Review Focus

Input classes spec §10 and design §8.2–§8.3 imply that no task's happy path exercises, most likely to bite first. Each has a test added to the task that owns the code.

1. **A dataset read as of a date that precedes its own release.** The whole point of date-to-release resolution is that a dated run evaluates the population that date would have evaluated; a resolver that returns the newest release it can see puts hindsight in the sampling frame. → Task 3.
2. **A multi-file dataset whose files are reordered, renamed or re-walked in a different filesystem order.** A digest over concatenated bytes or over `Path.iterdir()` order makes the same data hash differently on another machine, and `data_hash` stops identifying the data. → Task 2.
3. **A cache hit whose upstream algorithm or release version has moved.** Keying on the request alone serves a stale body under a new upstream version, which is the exact failure SAWA's version-pinned Sierra cache exists to prevent. → Task 6.
4. **A graph where treatment or outcome is absent, or sits in a cycle.** `find_adjustment_set` answers with a reason; a wrapper that raises instead loses the distribution of failure reasons that makes a run's identification auditable. → Task 8.
5. **A degenerate sample: n = 1, zero variance, or all ties.** Cohen's *d* divides by a pooled standard deviation and a bootstrap resamples a constant; both produce `0.0`, `inf` or `nan` rather than refusing, and a zero-width 95% interval reads as certainty. → Tasks 11 and 13.

## File Structure

**Created**

| File | Responsibility |
| --- | --- |
| `python/hephkit-lab/src/hephkit/lab/data/__init__.py` | Public surface of `lab.data`: manifests, releases, loaders, snapshots |
| `.../lab/data/manifest.py` | `Manifest`, `FileDigest`, digest scope and `manifest_hash` (spec §10) |
| `.../lab/data/releases.py` | `Release` and date-to-release resolution |
| `.../lab/data/frames.py` | Polars and DuckDB loaders behind the `data` extra |
| `.../lab/data/snapshots.py` | DVC push/pull against a configured remote |
| `.../lab/sources.py` | Content-addressed response cache, upstream-version keying, offline replay |
| `.../lab/causal/__init__.py` | Public surface of `lab.causal` |
| `.../lab/causal/identify.py` | CausalPhylo adapter: graph → `Verdict` |
| `.../lab/causal/estimate.py` | DoWhy estimation: `Estimate` |
| `.../lab/causal/refute.py` | The refutation suite, on by default |
| `.../lab/causal/discover.py` | causal-learn discovery adapters |
| `.../lab/stats.py` | Effect sizes, test selection, bootstrap intervals, seed aggregation |
| `.../lab/extras.py` | `MissingExtraError` and the one import guard every module uses |
| `conformance/lab/manifest.json` | `lab.manifest` vectors, hand-derived from spec §10 |
| `conformance/lab/effects.json` | `lab.effects` vectors, hand-derived from published formulae |
| `conformance/lab/selection.json` | `lab.selection` vectors, hand-derived from the decision table |
| `python/hephkit-lab/tests/test_data_manifest.py` … `test_stats.py` | One test module per source module |
| `python/hephkit-lab/tests/test_extras.py` | The licence gate and the extras guard |
| `examples/lab-causal/{experiment.py,gate_test.sh,pyproject.toml,moon.yml}` | The fixture causal analysis and its gate |
| `docs/adr/0025-adopt-causalphylo-for-identification.md` | ADR 0025 |
| `docs/site/content/modules/{lab.data,lab.sources,lab.causal,lab.stats}.mdx` | One docs page per module, each with a runnable example |

**Modified**

| File | Change |
| --- | --- |
| `spec/heph-spec.md` | §10 written; version `0.5.0` → `0.6.0` |
| `conformance/schema/vector-file.schema.json` | `spec` const re-stamped; three suites added to the `suite` enum |
| `conformance/**/*.json` (15 files) | `spec` field re-stamped to `0.6.0` |
| `tools/gen_idempotency_vectors.py`, `tools/gen_signature_vectors.py` | `SPEC_VERSION` / `SPEC` constant re-stamped |
| `tools/check_vectors.py` | `MIN_CASES` entries for the three new suites |
| `spec/modules.yaml` | Four `shipped` rows, one per module task |
| `python/hephkit-lab/pyproject.toml` | `networkx` into `[causal]`, `causalphylo` pin bumped, mypy overrides per library |
| `python/hephkit-lab/moon.yml` | `test`/`test-fast` run with the wave's extras; new `test-spine` task |
| `python/hephkit-lab/tests/test_conformance.py` | Runners for the three new suites |
| `.github/workflows/ci.yml` | `lab-causal` gate job beside `lab-replay` |
| `docs/site/content/modules/_meta.ts`, `_snippets/site-data.json` | Four pages registered; site data regenerated |

---

### Task 1: Spec §10 and the 0.6.0 bump

The shared-surface commit. It lands first and alone, because it re-stamps every vector file in the repository.

**Files:**
- Modify: `spec/heph-spec.md:3` (version), `spec/heph-spec.md:393-399` (§10)
- Modify: `conformance/schema/vector-file.schema.json` (`spec` const, `suite` enum)
- Modify: every `conformance/*/*.json` (`spec` field)
- Modify: `tools/gen_idempotency_vectors.py:45`, `tools/gen_signature_vectors.py:58`
- Modify: `tools/check_vectors.py:28-56` (`MIN_CASES`)

**Interfaces:**
- Produces: spec §10's normative text, which Tasks 2 and 3 implement and `conformance/lab/manifest.json` pins. §10.1 the manifest's members; §10.2 the digest scope; §10.3 date-to-release resolution; §10.4 the refusals.

- [ ] **Step 1: Write spec §10**

Replace the reserved stub. §10 states, in the voice of §7–§9 (RFC 2119 keywords, numbered subsections, a table per structure):

- §10.1 A manifest MUST carry `dataset`, `source`, `release`, `extractor_version`, `captured_at` (RFC 3339 date), and `files`, a non-empty array of `{path, sha256, bytes}`. It MUST NOT carry a top-level member §10 does not define.
- §10.2 **The digest scope.** `data_hash` (§7.1) is the content hash (§4.2) of the canonical JSON (§4.1) of the array of `{path, sha256, bytes}` objects sorted by `path` under byte-wise comparison, where each `sha256` is the lowercase hex SHA-256 of that file's bytes **as written by the extractor**, not of the upstream source. Concatenating file bytes is forbidden; so is hashing a directory walk's order. A single-file dataset is an array of one.
- §10.3 **Date-to-release resolution.** Given releases each carrying a `published` date, resolving as of date *d* MUST yield the latest release whose `published` is less than or equal to *d*, and MUST refuse when no release satisfies it. A release published after *d* MUST NOT be reachable from *d*.
- §10.4 Refusals: a manifest with an empty `files`, a duplicate `path`, a `sha256` that is not 64 lowercase hex characters, or a `bytes` that disagrees with the file it names is invalid and MUST be refused rather than repaired.

- [ ] **Step 2: Bump the version and re-stamp**

`spec/heph-spec.md:3` to `0.6.0`; add §10's decision to the "Decisions this version settles" list; the schema's `"spec": {"const": "0.6.0"}`; both generator constants; and every vector file's `spec` field.

```bash
python3 - <<'PY'
import json, pathlib
for p in sorted(pathlib.Path("conformance").glob("*/*.json")):
    d = json.loads(p.read_text())
    d["spec"] = "0.6.0"
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
PY
git diff --stat conformance/
```

Expected: 15 vector files changed, one line each. If any file's diff is larger, the re-stamp reformatted it — revert and re-stamp that file by hand.

- [ ] **Step 3: Add the three suites to the schema enum and `MIN_CASES`**

Enum gains `"lab.manifest"`, `"lab.effects"`, `"lab.selection"`. `MIN_CASES` gains `"lab.manifest": 10`, `"lab.effects": 8`, `"lab.selection": 10`, each with the one-line comment the existing entries carry, naming what the minimum covers.

- [ ] **Step 4: Run the checkers to verify the repository is still coherent**

```bash
python tools/check_vectors.py; python tools/check_adrs.py; python tools/check_modules.py
uv run tools/gen_site_pages.py --check || uv run tools/gen_site_pages.py
```

Expected: `check_vectors` reports the three new suites as missing files and nothing else. That failure is correct here and clears in Tasks 2, 11 and 12; every other check passes.

- [ ] **Step 5: Commit**

```bash
git add spec/heph-spec.md conformance tools docs/site/content/_snippets/site-data.json
git commit -m "spec: section 10 pins the dataset manifest and the digest scope"
```

---

### Task 2: `lab.data` manifests and the digest scope

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/data/__init__.py`, `.../data/manifest.py`, `.../lab/extras.py`
- Create: `conformance/lab/manifest.json`
- Create: `python/hephkit-lab/tests/test_data_manifest.py`
- Modify: `python/hephkit-lab/tests/test_conformance.py` (a `lab.manifest` runner)
- Modify: `spec/modules.yaml` — `{name: lab.data, home: python, status: shipped, maturity: experimental, spec_section: "10"}`

**Interfaces:**
- Consumes: `hephkit.hashing.content_hash`; `hephkit.lab.repro.ContentHash` as the annotated hash type the provenance record already validates.
- Produces:
  - `class FileDigest(BaseModel)` — frozen, `extra="forbid"`, `strict=True`; `path: str`, `sha256: str`, `bytes: int`.
  - `class Manifest(BaseModel)` — frozen, `extra="forbid"`; `dataset: str`, `source: str`, `release: str`, `extractor_version: str`, `captured_at: date`, `files: tuple[FileDigest, ...]`; `.as_document() -> dict[str, Any]` in §10.1's member order.
  - `def digest_file(path: Path, *, relative_to: Path) -> FileDigest`
  - `def manifest_for(root: Path, *, dataset: str, source: str, release: str, extractor_version: str, captured_at: date) -> Manifest`
  - `def data_hash(manifest: Manifest) -> str` — §10.2's composition.
  - `def write_manifest(manifest: Manifest, path: Path) -> Path`, `def read_manifest(path: Path) -> Manifest`
  - `class ManifestError(ValueError)` carrying `HEPH-LAB-422`; `class MissingExtraError(ImportError)` in `extras.py` with `def require(module: str, *, extra: str) -> ModuleType`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_data_hash_is_order_independent_over_paths(tmp_path): ...
    # two roots with the same files written in opposite order hash equal
def test_the_data_hash_changes_when_a_file_is_renamed(tmp_path): ...
def test_the_data_hash_is_the_content_hash_of_the_sorted_digest_array(tmp_path): ...
    # assert data_hash(m) == content_hash([d.model_dump() for d in sorted_files])
def test_a_manifest_with_no_files_is_refused(): ...
def test_a_duplicate_path_is_refused(): ...
def test_a_sha256_that_is_not_64_hex_characters_is_refused(): ...
def test_bytes_disagreeing_with_the_file_is_refused(tmp_path): ...
def test_a_manifest_round_trips_through_disk(tmp_path): ...
def test_as_document_writes_section_10_1s_members_in_order(): ...
```

Review Focus 2 is `test_the_data_hash_is_order_independent_over_paths` plus a third case that walks one root twice with `iterdir` monkeypatched to reverse, asserting both walks hash equal.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run pytest tests/test_data_manifest.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hephkit.lab.data'`

- [ ] **Step 3: Implement `manifest.py` and `extras.py`**

The digest array is sorted by `path.encode()` before hashing, which is §10.2's byte-wise comparison and not Python's default string ordering for non-ASCII paths. `data_hash` passes the sorted array through `content_hash` and returns its result unchanged.

- [ ] **Step 4: Write the `lab.manifest` vectors**

`conformance/lab/manifest.json`, `"suite": "lab.manifest"`, `"spec": "0.6.0"`, `"source"` naming spec §10 and this plan. At least ten cases, each hand-derived: the single-file hash, two-file order independence, the rename, and one case per §10.4 refusal as `{"error": "HEPH-LAB-422"}`. A `sha256` in an input is a literal the case states; it is never read back from our own implementation.

- [ ] **Step 5: Add the runner and run the suite**

A `run_manifest(case)` in `tests/test_conformance.py`, registered in `RUNNERS` under `"lab.manifest"`.

Run: `cd python/hephkit-lab && uv run pytest tests/test_conformance.py -v && cd ../.. && python tools/check_vectors.py`
Expected: PASS; `check_vectors` no longer reports `lab/manifest.json` missing.

- [ ] **Step 6: Commit**

```bash
git add python/hephkit-lab/src/hephkit/lab/data python/hephkit-lab/src/hephkit/lab/extras.py \
        python/hephkit-lab/tests conformance/lab/manifest.json spec/modules.yaml
git commit -m "feat(lab): dataset manifests and the digest scope of spec section 10"
```

---

### Task 3: Date-to-release resolution

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/data/releases.py`
- Create: `python/hephkit-lab/tests/test_data_releases.py`
- Modify: `.../data/__init__.py` (re-export)

**Interfaces:**
- Produces:
  - `class Release(BaseModel)` — frozen, `extra="forbid"`; `release: str`, `published: date`.
  - `def release_as_of(releases: Sequence[Release], when: date) -> Release`
  - `class TemporalError(LookupError)` carrying `HEPH-LAB-424`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_date_resolves_to_the_latest_release_published_on_or_before_it(): ...
def test_a_release_published_after_the_date_is_unreachable(): ...
    # three releases; as_of(the day before the newest) never returns the newest
def test_a_date_equal_to_a_publication_date_resolves_to_that_release(): ...
def test_a_date_before_every_release_is_refused(): ...
    # TemporalError, not the earliest release
def test_an_empty_release_table_is_refused(): ...
def test_releases_out_of_chronological_order_resolve_the_same(): ...
```

The second is Review Focus 1 and is the test this task exists for.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run pytest tests/test_data_releases.py -v`
Expected: FAIL with an import error for `releases`.

- [ ] **Step 3: Implement `release_as_of`**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python/hephkit-lab && uv run pytest tests/test_data_releases.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(lab): a dated run resolves the release that date would have seen"
```

---

### Task 4: Polars and DuckDB loaders behind the `data` extra

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/data/frames.py`
- Create: `python/hephkit-lab/tests/test_data_frames.py`, `python/hephkit-lab/tests/test_extras.py`
- Modify: `python/hephkit-lab/moon.yml`, `python/hephkit-lab/pyproject.toml` (mypy overrides for `polars`, `duckdb`)
- Modify: `.github/workflows/python-ci.yml` (the lab job's extras)

**Interfaces:**
- Consumes: `Manifest`, `data_hash`, `require` from Task 2.
- Produces:
  - `def read_frame(manifest: Manifest, *, root: Path, file: str | None = None) -> pl.DataFrame` — verifies the file's digest before reading and refuses a mismatch with `ManifestError`.
  - `def query(manifest: Manifest, *, root: Path, sql: str) -> pl.DataFrame` — DuckDB over the manifest's files registered by `path`.

- [ ] **Step 1: Write the failing tests**

```python
def test_read_frame_reads_the_file_the_manifest_names(tmp_path): ...
def test_read_frame_refuses_a_file_whose_digest_moved(tmp_path): ...
    # rewrite one byte after the manifest is written -> ManifestError
def test_query_sees_every_file_in_the_manifest(tmp_path): ...
def test_a_file_absent_from_the_manifest_is_not_readable(tmp_path): ...
# tests/test_extras.py
def test_a_missing_extra_names_the_extra_to_install(monkeypatch): ...
    # require("polars", extra="data") with the import blocked raises
    # MissingExtraError whose message contains "hephkit-lab[data]"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run --extra data pytest tests/test_data_frames.py tests/test_extras.py -v`
Expected: FAIL with an import error for `frames`.

- [ ] **Step 3: Implement `frames.py`**

Both functions call `require("polars", extra="data")` / `require("duckdb", extra="data")` inside the function body. Digest verification reuses `digest_file` rather than re-deriving SHA-256.

- [ ] **Step 4: Teach moon and CI the extras**

`test` and `test-fast` gain `--extra data --extra causal --extra stats`, and the coverage gate stays `--cov-fail-under=90` — the extras must be installed in the measuring task, or the four new modules report zero coverage and the gate fails for the wrong reason. A new `test-spine` task runs `uv run pytest -m "not extras"` with no extras at all, so the spine's independence is proven rather than assumed. Add the `extras` marker to `[tool.pytest.ini_options]` and mark every test that needs one.

- [ ] **Step 5: Run the tests and the typecheck**

```bash
cd python/hephkit-lab && uv run --extra data pytest tests/test_data_frames.py tests/test_extras.py -v && uv run mypy --strict src
```
Expected: PASS, and mypy clean with the two new overrides.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(lab): polars and duckdb loaders that verify the digest they read"
```

---

### Task 5: DVC snapshots and the data card

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/data/snapshots.py`, `.../data/cards.py`
- Create: `python/hephkit-lab/tests/test_data_snapshots.py`, `python/hephkit-lab/tests/test_data_cards.py`

**Interfaces:**
- Consumes: `Manifest`, `require`.
- Produces:
  - `def push(manifest: Manifest, *, root: Path, remote: str) -> None`
  - `def pull(manifest: Manifest, *, into: Path, remote: str) -> None` — refuses with `ManifestError` if what arrives does not match the manifest's digests.
  - `def data_card(manifest: Manifest, *, notes: str | None = None) -> str` — design §8.2's data card: the Markdown a reader gets, carrying every manifest member, the `data_hash`, the file table and the caller's own notes. Rendered from the manifest and never typed by hand, so a card cannot describe a dataset that is not the one on disk.

A **local directory remote** is what the tests use. DVC supports one, it needs no daemon, no credentials and no S3, and the thing under test is that a snapshot round-trips and that a corrupted arrival is refused — none of which an object-store protocol changes. The Compose S3 at 54333 is therefore not a test dependency, and this gate keeps running on every pull request.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.extras
def test_a_pushed_snapshot_pulls_back_byte_identical(tmp_path): ...
@pytest.mark.extras
def test_a_pull_whose_arrival_disagrees_with_the_manifest_is_refused(tmp_path): ...
@pytest.mark.extras
def test_pull_leaves_nothing_behind_when_it_refuses(tmp_path): ...
# tests/test_data_cards.py -- no extra: a card is Markdown over a manifest
def test_the_card_states_the_data_hash_the_manifest_composes(tmp_path): ...
def test_the_card_lists_every_file_with_its_digest_and_size(tmp_path): ...
def test_the_card_carries_the_release_and_the_extractor_version(tmp_path): ...
def test_notes_reach_the_card_without_displacing_a_manifest_member(tmp_path): ...
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run --extra data pytest tests/test_data_snapshots.py -v`
Expected: FAIL with an import error for `snapshots`.

- [ ] **Step 3: Implement `snapshots.py` and `cards.py`**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python/hephkit-lab && uv run --extra data pytest tests/test_data_snapshots.py tests/test_data_cards.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(lab): dataset snapshots and the card that describes them"
```

---

### Task 6: `lab.sources` — frozen inputs and offline replay

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/sources.py`
- Create: `python/hephkit-lab/tests/test_sources.py`
- Modify: `spec/modules.yaml` (the `lab.sources` row)

**Interfaces:**
- Consumes: `hephkit.hashing.content_hash`.
- Produces:
  - `class Request(BaseModel)` — frozen; `method: str`, `url: str`, `body: bytes | None`.
  - `def cache_key(request: Request, *, upstream_version: str) -> str` — the content hash of `{"method", "url", "body" (base64 or null), "upstream_version"}`.
  - `class SourceCache` — `__init__(directory: Path, *, upstream_version: str, offline: bool = False)`; `.fetch(request: Request, fetcher: Callable[[Request], bytes]) -> bytes`; `.frozen() -> tuple[str, ...]`.
  - `class SourceError(LookupError)` carrying `HEPH-LAB-424`.

**Freezing mechanism — my call, which design §14 leaves to the builder.** A content-addressed cache at the `fetch` boundary, not vcrpy. Our sources do not share NeoRx's per-call `Session` construction, vcrpy patches `httplib` process-wide (which collides with the in-process network block the gate already proves), and the lesson actually worth keeping from SAWA is the *version-pinned key*, not the transport interception. A project needing transport-level capture can still wrap its own client in `fetcher`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_fetch_is_frozen_and_the_second_call_does_not_reach_the_fetcher(tmp_path): ...
    # fetcher counts calls; second fetch leaves the count at 1
def test_a_changed_upstream_version_misses_the_cache(tmp_path): ...
    # Review Focus 3: same Request, new upstream_version -> fetcher called again
def test_offline_mode_serves_a_hit(tmp_path): ...
def test_offline_mode_refuses_a_miss_rather_than_fetching(tmp_path): ...
    # SourceError, and the fetcher is never called
def test_a_body_distinguishes_two_posts_to_one_url(tmp_path): ...
def test_the_key_is_stable_across_processes(tmp_path): ...
    # literal expected key for a literal request, so a keying change is caught
def test_a_corrupted_frozen_body_is_refused_rather_than_served(tmp_path): ...
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run pytest tests/test_sources.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hephkit.lab.sources'`

- [ ] **Step 3: Implement `sources.py`**

The frozen body is stored under its key with a sidecar holding the request and the upstream version, so `frozen()` can list what a run depends on and a reviewer can read it. The spine installs it: no extra, no new dependency.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python/hephkit-lab && uv run pytest tests/test_sources.py -v && uv run mypy --strict src`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/hephkit-lab spec/modules.yaml
git commit -m "feat(lab): frozen external inputs keyed by request and upstream version"
```

---

### Task 7: ADR 0025 and the CausalPhylo licence gate

**Blocked on the MIT release of `causalphylo`.** See the precondition above; if it has not landed, stop here and raise it.

**Files:**
- Create: `docs/adr/0025-adopt-causalphylo-for-identification.md`
- Modify: `python/hephkit-lab/pyproject.toml` (`causal` extra: pin bump, `networkx`)
- Modify: `python/hephkit-lab/tests/test_extras.py`

- [ ] **Step 1: Write ADR 0025**

Following the format of `docs/adr/0021`–`0024`. It records: rule 8 — the capability exists as a documented single-dependency package extracted from NeoRx for exactly this purpose, so it is adopted and pinned, not vendored and not rebuilt; that identification runs on the causal-admissible subgraph, which is the decision the dependency actually buys; **and that adoption was conditional on CausalPhylo being relicensed MIT**, because `hephkit-lab` is MIT and `LicenseRef-CausalPhylo-NonCommercial` would have put non-commercial terms inside an MIT kit's extra. It names the MIT version as the floor and the test below as the enforcement.

- [ ] **Step 2: Write the failing licence test**

```python
@pytest.mark.extras
def test_causalphylo_is_not_licensed_non_commercially():
    metadata = importlib.metadata.metadata("causalphylo")
    expression = metadata.get("License-Expression") or metadata.get("License") or ""
    assert "NonCommercial" not in expression
    assert expression.strip() == "MIT"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd python/hephkit-lab && uv run --extra causal pytest tests/test_extras.py -v`
Expected: FAIL while the old pin resolves, naming `LicenseRef-CausalPhylo-NonCommercial`. This failure *is* the precondition check.

- [ ] **Step 4: Bump the pin and add `networkx`**

`causal = ["dowhy>=0.13", "causal-learn>=0.1.4", "causalphylo>=<first MIT release>", "networkx>=3.3", "hephkit-lab[data]"]`, with a comment naming ADR 0025 and the licence floor. `networkx` is explicit because `lab.causal`'s own signatures take a `nx.DiGraph`, so it is a direct dependency of ours and not only CausalPhylo's. `hephkit-lab[data]` is there because Tasks 9 and 10 take a `pl.DataFrame`: `[causal]` alone would import a name it cannot resolve. The `all` extra already composes extras this way, so the pattern is the file's own.

- [ ] **Step 5: Verify the test passes and ADR numbering is contiguous**

```bash
cd python/hephkit-lab && uv run --extra causal pytest tests/test_extras.py -v
cd ../.. && python tools/check_adrs.py
```
Expected: PASS, and `check_adrs` reports no gap at 0025.

- [ ] **Step 6: Commit**

```bash
git add docs/adr/0025-adopt-causalphylo-for-identification.md python/hephkit-lab
git commit -m "docs(adr): adopt causalphylo for identification under an MIT licence"
```

---

### Task 8: `lab.causal` identification

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/causal/__init__.py`, `.../causal/identify.py`
- Create: `python/hephkit-lab/tests/test_causal_identify.py`
- Modify: `spec/modules.yaml` (the `lab.causal` row), `pyproject.toml` (mypy overrides for `causalphylo`, `networkx`, `dowhy`, `causallearn`)

**Interfaces:**
- Consumes: `causalphylo.find_adjustment_set(graph, treatment, outcome)`, whose verdict carries `.identifiable`, `.adjustment_set`, `.reason.value` and `.n_near_miss_confounders`; `require` from Task 2.
- Produces:
  - `class Verdict(BaseModel)` — frozen, `extra="forbid"`; `identifiable: bool`, `adjustment_set: tuple[str, ...]`, `reason: str`, `near_miss_confounders: int`; `.as_document() -> dict[str, Any]` so a record row can carry it.
  - `def identify(graph: nx.DiGraph, *, treatment: str, outcome: str) -> Verdict`

`identify` is a translation boundary, not a reimplementation: it passes the **full** graph through (CausalPhylo restricts to the admissible subgraph internally, and a caller must not be able to forget that), and converts the verdict into our frozen model so a run record and a replay diff see a stable shape even if the upstream dataclass changes.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.extras
def test_the_textbook_confounder_is_identifiable_by_adjustment(): ...
    # U->X, U->D, X->D with the evidence classes CausalPhylo admits;
    # identifiable is True, adjustment_set == ("U",),
    # reason == "identifiable_by_adjustment"
@pytest.mark.extras
def test_an_absent_treatment_returns_a_reason_rather_than_raising(): ...
    # Review Focus 4: reason == "treatment_absent", identifiable is False
@pytest.mark.extras
def test_a_cycle_through_the_treatment_returns_cyclic_component(): ...
@pytest.mark.extras
def test_a_trivial_verdict_carries_its_near_miss_count(): ...
    # a trivial verdict is not a clean bill of health
@pytest.mark.extras
def test_an_associational_edge_does_not_earn_an_arrow(): ...
    # a co-mention-only path is not a causal path
@pytest.mark.extras
def test_the_verdict_is_frozen_and_closed_to_extras(): ...
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run --extra causal pytest tests/test_causal_identify.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hephkit.lab.causal'`

- [ ] **Step 3: Implement `identify.py`**

- [ ] **Step 4: Run the tests and the typecheck**

Run: `cd python/hephkit-lab && uv run --extra causal pytest tests/test_causal_identify.py -v && uv run mypy --strict src`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/hephkit-lab spec/modules.yaml
git commit -m "feat(lab): identification over graphs where not every edge is an arrow"
```

---

### Task 9: `lab.causal` estimation and the refutation suite

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/causal/estimate.py`, `.../causal/refute.py`
- Create: `python/hephkit-lab/tests/test_causal_estimate.py`

**Interfaces:**
- Consumes: `Verdict` from Task 8; `dowhy`; `require`.
- Produces:
  - `class Estimate(BaseModel)` — frozen; `value: float`, `estimator: str`, `adjustment_set: tuple[str, ...]`, `n: int`.
  - `def estimate(frame: pl.DataFrame, *, treatment: str, outcome: str, verdict: Verdict, estimator: str = "backdoor.linear_regression", seed: int) -> Estimate` — refuses a `Verdict` whose `identifiable` is false with `CausalError` (`HEPH-LAB-412`), because estimating an unidentified effect is the error the module exists to prevent.
  - `class Refutation(BaseModel)` — frozen; `name: str`, `effect: float`, `passed: bool`.
  - `def refute(frame, *, treatment, outcome, verdict, estimate: Estimate, seed: int, refuters: Sequence[str] = DEFAULT_REFUTERS) -> tuple[Refutation, ...]` — `DEFAULT_REFUTERS` is placebo treatment, random common cause and data subset, **on by default**, which is design §8.3's requirement.
  - `class CausalError(RuntimeError)` carrying `HEPH-LAB-412`.

Determinism: every refuter that resamples takes `seed`, and `estimate`'s default estimator is a closed-form regression rather than a sampling method, so the fixture of Task 14 can replay bit-identically. A refuter that cannot be seeded does not belong in `DEFAULT_REFUTERS`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.extras
def test_the_estimate_recovers_a_known_synthetic_effect(): ...
    # y = 2*x + 3*u + noise, generated under a seed; estimate within tolerance of 2
@pytest.mark.extras
def test_an_unidentified_verdict_is_refused_before_any_estimation(): ...
@pytest.mark.extras
def test_the_placebo_refuter_finds_no_effect_on_a_scrambled_treatment(): ...
@pytest.mark.extras
def test_the_random_common_cause_refuter_leaves_the_estimate_alone(): ...
@pytest.mark.extras
def test_every_default_refuter_runs_and_is_reported(): ...
    # names == DEFAULT_REFUTERS, so a silently skipped refuter fails the test
@pytest.mark.extras
def test_two_runs_at_one_seed_produce_an_identical_estimate_and_refutations(): ...
@pytest.mark.extras
def test_an_omitted_confounder_biases_the_estimate_away_from_the_truth(): ...
    # the control for the first test: adjusting for nothing must NOT recover 2
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run --extra causal pytest tests/test_causal_estimate.py -v`
Expected: FAIL with an import error for `estimate`.

- [ ] **Step 3: Implement `estimate.py` and `refute.py`**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python/hephkit-lab && uv run --extra causal pytest tests/test_causal_estimate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(lab): estimation through dowhy with the refutation suite on by default"
```

---

### Task 10: `lab.causal` discovery adapters

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/causal/discover.py`
- Create: `python/hephkit-lab/tests/test_causal_discover.py`

**Interfaces:**
- Consumes: `causallearn`; `require`.
- Produces:
  - `def discover(frame: pl.DataFrame, *, algorithm: str = "pc", alpha: float = 0.05, seed: int) -> nx.DiGraph` — returns a graph whose edges carry the `edge_type` and `evidence_class` attributes `identify` reads, with every discovered edge marked as the evidence class a discovery algorithm can actually warrant.
  - `class DiscoveryError(RuntimeError)` carrying `HEPH-LAB-412`.

The evidence class matters more than the algorithm here: a discovered edge is not a curated mechanism, and marking it as one would let `identify` admit an arrow nothing earned. `discover` therefore labels its output as discovered, and a project that wants it treated as regulatory has to say so explicitly in its own graph assembly.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.extras
def test_discovery_recovers_a_chain_from_synthetic_data(): ...
@pytest.mark.extras
def test_every_discovered_edge_is_labelled_as_discovered_evidence(): ...
@pytest.mark.extras
def test_an_unknown_algorithm_is_refused(): ...
@pytest.mark.extras
def test_discovery_at_one_seed_is_reproducible(): ...
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run --extra causal pytest tests/test_causal_discover.py -v`
Expected: FAIL with an import error for `discover`.

- [ ] **Step 3: Implement `discover.py`**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python/hephkit-lab && uv run --extra causal pytest tests/test_causal_discover.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(lab): causal-learn discovery that does not launder discovered edges"
```

---

### Task 11: `lab.stats` effect sizes and the `lab.effects` vectors

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/stats.py`
- Create: `conformance/lab/effects.json`
- Create: `python/hephkit-lab/tests/test_stats.py`
- Modify: `python/hephkit-lab/tests/test_conformance.py`, `spec/modules.yaml` (the `lab.stats` row)

**Interfaces:**
- Produces:
  - `def cohens_d(a: Sequence[float], b: Sequence[float]) -> float`
  - `def hedges_g(a: Sequence[float], b: Sequence[float]) -> float`
  - `def cliffs_delta(a: Sequence[float], b: Sequence[float]) -> float`
  - `class StatsError(ValueError)` carrying `HEPH-LAB-422`.

Effect sizes are pure arithmetic over sequences and need no extra; `scipy` enters only in Task 13.

- [ ] **Step 1: Write the `lab.effects` vectors**

Hand-derived from the published definitions, which the file's `source` names and which the plan writes out so the derivation is checkable rather than remembered:

- Cohen's *d* = (mean(a) − mean(b)) / s_pooled, where s_pooled = sqrt(((n_a−1)·var_a + (n_b−1)·var_b) / (n_a + n_b − 2)), variances sample (n−1).
- Hedges' *g* = *d* · (1 − 3 / (4·(n_a + n_b) − 9)).
- Cliff's δ = (#(x > y) − #(x < y)) / (n_a · n_b) over all pairs.

At least eight cases, each with inputs chosen so the expected value is exact by hand: `a=[1,2,3]`/`b=[1,2,3]` → *d* = 0; `a=[2,4]`/`b=[0,2]` → *d* = 2/sqrt(2); δ = 1 for fully separated samples, −1 reversed, 0 for identical; plus one Hedges' *g* case where the correction factor is a clean fraction. Every refusal case expects `{"error": "HEPH-LAB-422"}`.

- [ ] **Step 2: Write the failing tests**

```python
def test_a_zero_variance_pair_is_refused_rather_than_divided_by_zero(): ...
    # Review Focus 5: a=[2,2,2], b=[2,2,2] -> StatsError, not 0.0 or nan
def test_a_single_observation_sample_is_refused(): ...
def test_cliffs_delta_handles_all_ties(): ...
def test_an_empty_sample_is_refused(): ...
def test_a_nan_in_a_sample_is_refused(): ...
```

- [ ] **Step 3: Run them and the suite to verify both fail**

Run: `cd python/hephkit-lab && uv run pytest tests/test_stats.py tests/test_conformance.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hephkit.lab.stats'`

- [ ] **Step 4: Implement the three effect sizes and the `lab.effects` runner**

- [ ] **Step 5: Run the tests, the suite and the checker**

```bash
cd python/hephkit-lab && uv run pytest tests/test_stats.py tests/test_conformance.py -v
cd ../.. && python tools/check_vectors.py
```
Expected: PASS; `check_vectors` no longer reports `lab/effects.json` missing.

- [ ] **Step 6: Commit**

```bash
git add python/hephkit-lab conformance/lab/effects.json spec/modules.yaml
git commit -m "feat(lab): effect sizes that refuse a sample they cannot describe"
```

---

### Task 12: `lab.stats` test selection and the `lab.selection` vectors

**Files:**
- Modify: `python/hephkit-lab/src/hephkit/lab/stats.py`
- Create: `conformance/lab/selection.json`
- Modify: `python/hephkit-lab/tests/test_stats.py`, `tests/test_conformance.py`

**Interfaces:**
- Produces:
  - `class Scale(StrEnum)` — `interval`, `ordinal`, `nominal`.
  - `class TestRequest(BaseModel)` — frozen, `extra="forbid"`, `strict=True`; `scale: Scale`, `groups: int`, `paired: bool`, `normal: bool`, `equal_variance: bool`, `n_min: int`.
  - `class TestChoice(BaseModel)` — frozen; `test: str`, `reason: str`.
  - `def choose_test(request: TestRequest) -> TestChoice` — raises `StatsError` when no test in the table is appropriate, rather than falling back to one.

The decision table is written in this task and is what the vectors pin: two interval groups, normal, equal variance, unpaired → `independent_t`; unequal variance → `welch_t`; paired → `paired_t`; non-normal or ordinal → `mann_whitney_u` unpaired, `wilcoxon_signed_rank` paired; three or more interval groups → `one_way_anova`, non-normal → `kruskal_wallis`; nominal → `chi_square`, and `fisher_exact` when `n_min` is below 5; a refusal for one group, for zero groups, and for a paired nominal design the table does not cover.

- [ ] **Step 1: Write the `lab.selection` vectors**

At least ten cases, one per row of the table above plus each refusal, `{"error": "HEPH-LAB-422"}` for the refusals. Pure data in, pure data out: this is why it is vectored rather than contract-tested.

- [ ] **Step 2: Write the failing tests**

```python
def test_an_inappropriate_test_is_refused_rather_than_approximated(): ...
def test_a_small_nominal_cell_count_chooses_fisher_over_chi_square(): ...
def test_the_reason_names_the_rule_that_decided(): ...
def test_a_request_with_an_unknown_member_is_refused(): ...
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run pytest tests/test_stats.py -k selection -v`
Expected: FAIL with an attribute error for `choose_test`

- [ ] **Step 4: Implement `choose_test` and the `lab.selection` runner**

- [ ] **Step 5: Run the tests, the suite and the checker**

```bash
cd python/hephkit-lab && uv run pytest tests/test_stats.py tests/test_conformance.py -v
cd ../.. && python tools/check_vectors.py
```
Expected: PASS, and `check_vectors` reports no missing suite at all.

- [ ] **Step 6: Commit**

```bash
git add python/hephkit-lab conformance/lab/selection.json
git commit -m "feat(lab): test selection that refuses an inappropriate test"
```

---

### Task 13: `lab.stats` bootstrap intervals and seed aggregation

Contract-tested, never vectored: design §9.3 settles that taking expected numbers from a seeded `scipy.stats.bootstrap` run would make scipy's resampling order and RNG stream the normative definition.

**Files:**
- Modify: `python/hephkit-lab/src/hephkit/lab/stats.py`
- Modify: `python/hephkit-lab/tests/test_stats.py`

**Interfaces:**
- Consumes: `scipy` via `require("scipy", extra="stats")`.
- Produces:
  - `class Interval(BaseModel)` — frozen; `low: float`, `high: float`, `confidence: float`.
  - `def bootstrap_ci(sample: Sequence[float], statistic: Callable[[Sequence[float]], float] = mean, *, confidence: float = 0.95, resamples: int = 10_000, seed: int) -> Interval` — refuses a degenerate sample with `StatsError`.
  - `class SeedSummary(BaseModel)` — frozen; `n: int`, `mean: float`, `sd: float`, `interval: Interval`.
  - `def aggregate_seeds(values: Mapping[int, float], *, confidence: float = 0.95, seed: int) -> SeedSummary`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.extras
def test_a_nominal_95_interval_covers_a_known_parameter_about_95_percent_of_the_time(): ...
    # many synthetic draws from a known mean; coverage within a stated band.
    # Mark it `slow` as well as `extras` so test-fast deselects it.
@pytest.mark.extras
def test_a_zero_variance_sample_is_refused_rather_than_given_a_zero_width_interval(): ...
    # Review Focus 5
@pytest.mark.extras
def test_a_single_observation_sample_is_refused(): ...
@pytest.mark.extras
def test_two_runs_at_one_seed_give_the_same_interval(): ...
@pytest.mark.extras
def test_aggregate_seeds_reports_the_seed_count_it_was_given(): ...
@pytest.mark.extras
def test_aggregate_seeds_refuses_a_single_seed(): ...
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run --extra stats pytest tests/test_stats.py -k bootstrap -v`
Expected: FAIL with an attribute error for `bootstrap_ci`

- [ ] **Step 3: Implement `bootstrap_ci` and `aggregate_seeds`**

`seed` is threaded into scipy's generator explicitly; nothing reads global RNG state, which is what lets a recorded run replay.

- [ ] **Step 4: Run the tests, including the slow coverage property**

```bash
cd python/hephkit-lab && uv run --extra stats pytest tests/test_stats.py -v
```
Expected: PASS, the coverage test included.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(lab): bootstrap intervals contract-tested on their coverage"
```

---

### Task 14: The fixture causal analysis through the gate

The wave's definition of done, and design §11's gate for this wave.

**Files:**
- Create: `examples/lab-causal/experiment.py`, `examples/lab-causal/gate_test.sh`, `examples/lab-causal/pyproject.toml`, `examples/lab-causal/moon.yml`
- Modify: `.github/workflows/ci.yml` (a `lab-causal` job beside `lab-replay`)

**Interfaces:**
- Consumes: everything this wave built, plus `hephkit.lab.record.register`/`run`/`open_record`, `hephkit.lab.repro.capture`, `hephkit.lab.replay.replay`, `hephkit.lab.gates.check_all`.
- Produces: no importable API. `experiment.py` is a script with the same subcommand shape as `examples/lab-replay/experiment.py` (`freeze`, `record`, `replay`, `perturb`, `gates`), printing one `KEY field=value` line per claim so the gate script asserts on output rather than on exit codes alone.

The analysis is SAWA-shaped and synthetic: a confounded DAG (`U → X`, `U → D`, `X → D`) whose data the fixture generates under a seed, with a known true effect. Cells: `identify`, `estimate`, `refute`, `aggregate` — `estimate` runs under several seeds so `aggregate` has a distribution to summarise rather than one number to restate. The perturbation moves one held-out observation, so the diff must name the estimate and leave `identify` alone.

- [ ] **Step 1: Write `experiment.py`**

`freeze` writes the synthetic dataset and its `lab.data` manifest and prints `FROZEN … data_hash=…`. `record` captures provenance, runs the registered experiment and prints `RECORD run_id=… class=… complete=yes rows=4 cells=identify,estimate,refute,aggregate` plus a `VALUE` line per metric. `replay` re-executes with the network blocked — reusing `lab-replay/experiment.py`'s `block_network` and printing the same self-proving `BLOCK proved=… count=4` line — and prints `REPLAY … matched=yes differences=0`. `perturb` replays against the perturbed manifest and prints a `DIFF` line per moved value. `gates` points `check_all` at a figure script holding a transcribed estimate and at a clean one.

- [ ] **Step 2: Write `gate_test.sh`**

Modelled on `examples/lab-replay/gate_test.sh`, keeping its `check`/`step`/`says`/`silent` helpers verbatim — including the load-bearing `-s` in `silent`, for the reason its comment gives. The claims:

- the fixture freezes its own synthetic data and the manifest hashes it
- the identification verdict is `identifiable_by_adjustment` with the adjustment set `U`
- the estimate recovers the known effect within the fixture's stated tolerance
- every default refuter ran and is recorded
- a clean checkout earns `class=deterministic` (the same `earned_class` logic, for the same reason)
- the replay matched with the network blocked, and named no position
- the perturbed replay diverged, and the diff names `data_hash` and the estimate
- the diff leaves the `identify` cell alone
- `check_all` refuses the transcribed estimate with `HEPH-LAB-412` and passes the clean figure

- [ ] **Step 3: Run the gate to verify it fails for the right reason**

Run: `bash examples/lab-causal/gate_test.sh`
Expected: FAIL, naming the claims not yet met — never a pass, and never a failure in `uv` resolution.

- [ ] **Step 4: Wire moon and CI**

`examples/lab-causal/moon.yml` mirrors `examples-lab-replay:gate`'s inputs, adding the four new source directories. The CI job is inline beside `lab-replay`, `fetch-depth: 0` for the same reason, running `moon run examples-lab-causal:gate`. It installs the `causal`, `data` and `stats` extras, so give it a timeout above `lab-replay`'s 20 minutes and state in a comment that this gate is the one that pays for the scientific stack.

- [ ] **Step 5: Run the gate to verify it passes**

Run: `bash examples/lab-causal/gate_test.sh`
Expected: `lab-causal gate: PASS`, with every claim listed as `PASS`.

- [ ] **Step 6: Commit**

```bash
git add examples/lab-causal .github/workflows/ci.yml
git commit -m "test(lab): a causal analysis records, replays and diffs through the spine"
```

---

### Task 15: Docs pages and whole-wave verification

**Files:**
- Create: `docs/site/content/modules/lab.data.mdx`, `lab.sources.mdx`, `lab.causal.mdx`, `lab.stats.mdx`
- Modify: `docs/site/content/modules/_meta.ts`
- Modify: `python/hephkit-lab/tests/test_package.py`

- [ ] **Step 1: Write the four docs pages**

Following `docs/site/content/modules/lab.config.mdx`'s shape: frontmatter `title`, an opening paragraph saying what the module refuses to let you get wrong, a runnable example, the extra it needs and what installing it costs. `lab.causal`'s page states ADR 0025 and that identification runs on the admissible subgraph. `lab.data`'s page states spec §10's digest scope.

- [ ] **Step 2: Extend the spine's import probe**

`test_package.py` gains the four new modules to its spine-only import probe: importing `hephkit.lab.data`, `hephkit.lab.sources`, `hephkit.lab.causal` and `hephkit.lab.stats` with no extras installed must succeed, and touching a function that needs one must raise `MissingExtraError` naming the extra. This is what makes the import-guard constraint enforced rather than stated.

- [ ] **Step 3: Run the whole repository's checks**

```bash
cd python/hephkit-lab && uv run --extra data --extra causal --extra stats pytest --cov=hephkit.lab --cov-fail-under=90 && uv run mypy --strict src
cd ../.. && uv run pytest -m "not extras" --rootdir python/hephkit-lab python/hephkit-lab/tests
python tools/check_adrs.py && python tools/check_registry.py && python tools/check_vectors.py && python tools/check_modules.py
uv run tools/gen_error_pages.py --check && uv run tools/gen_site_pages.py --check && uv run tools/gen_quickstart.py --check
bun install --frozen-lockfile && bun run --cwd docs/site build && bun test --cwd docs/site && uv run tools/check_site_links.py
bash examples/lab-replay/gate_test.sh && bash examples/lab-causal/gate_test.sh
```

Expected: every command green, coverage at or above 90%. Paste any failure rather than summarising it.

- [ ] **Step 4: Commit**

```bash
git add docs/site python/hephkit-lab/tests/test_package.py
git commit -m "docs(lab): pages for data, sources, causal and stats with runnable examples"
```
