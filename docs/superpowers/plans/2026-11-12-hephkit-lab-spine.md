# hephkit.lab Integrity Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the research-integrity spine of `hephkit.lab` — typed configs, provenance records, crash-safe run records, replay-and-diff, CI gates and MLflow tracking — so that a reported number cannot exist without a record that replays.

**Architecture:** A new `hephkit-lab` distribution supplies `hephkit.lab` through a PEP 420 namespace package, depends on `hephkit` for content hashing, and keeps every scientific dependency behind an extra so the spine installs with none. Behaviour is pinned by `spec/heph-spec.md` §7–§9 and `conformance/lab/*.json` before implementation, and enforced by an in-repo gate that records a fixture run, replays it with the network blocked, and diffs a perturbed variant.

**Tech Stack:** Python 3.12, pydantic 2, pytest, mypy --strict, maturin (for the existing core), moon, MLflow (behind the `track` extra), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-12-hephkit-lab-research-core-design.md`

**Scope:** Waves 0 and 1 of the design's §12 only. Waves 2–5 (`lab.data`, `lab.sources`, `lab.causal`, `lab.stats`, `lab.bench`, `lab.flows`, `lab.notebook`, `lab.train`, `lab.embed`, `lab.rl`, `lab.paper`, `lab.lit`, `lab.bio`) get their own plans, each written when that wave starts. Every wave produces working software on its own.

## Global Constraints

> **Correction (Ruling 12).** The conformance suites are named `lab.config`,
> `lab.record` and `lab.diff` — two segments, matching every existing suite
> (`money.parse`, `hashing.jcs`, `idempotency.key`). An earlier draft of this
> plan used three (`lab.config.resolve`, `lab.provenance.record`,
> `lab.provenance.diff`), which `tools/check_vectors.py` cannot accept:
> line 82 derives the expected suite as `f"{path.parent.name}.{path.stem}"`,
> and line 105 maps a missing suite back to a path with `suite.replace('.', '/')`.
> Task 1 committed the three-segment names into the schema `suite` enum before
> this was caught; **Task 7 corrects those three enum entries** as it adds the
> first suite file.


- Python `>=3.12`. `mypy --strict` passes on all source.
- Coverage gate: `--cov-fail-under=90`, same as `hephkit`.
- No new hashing. Content hashes come from `hephkit.hashing.content_hash` (RFC 8785 JCS + SHA-256, spec §4.2).
- Error codes match `^HEPH-[A-Z]{2,6}-\d{3}$` and live only in `spec/errors.yaml`.
- Every module carries `Maturity: experimental.` in its module docstring and a matching row in `spec/modules.yaml`.
- Generated files are never hand-edited: `_codes.py`, `conventions.py`, `go/internal/fragments/files/`, docs-site pages, `_snippets/site-data.json`.
- Conventional Commits. Branch `work/<topic>`. **No AI attribution** in commit messages, PR bodies or branch names.
- Local host ports come from the 54xxx block. MLflow takes **54500**.
- Vectors are never produced by running our own implementation (CLAUDE.md rule 2).
- ADRs land contiguously in the order tasks COMPLETE, not the order the design first listed them (Ruling 15): **Task 4 = 0021** (PEP 420), **Task 5 = 0022 and 0023**, **Task 6 = 0024**. `tools/check_adrs.py` fails on any gap, so writing a higher number before a lower one exists turns the branch red.

## Review Focus

Input classes the spec implies that no task's happy path exercises, most likely to bite first. Each has a test added to the task that owns the code.

1. **A config holding a NumPy scalar or array.** Overwhelmingly likely in research configs, and `json.dumps` cannot serialise `np.float32`. A raw `TypeError` from the JSON encoder is the wrong answer; the caller needs the field name. → Task 7.
2. **No git repository, no commits, or detached HEAD.** `code_sha` capture must degrade to `provenance-only` rather than raise. → Task 8.
3. **A recorded result containing NaN.** `NaN != NaN`, so a naive diff reports a difference between a run and itself. Replay must treat NaN as equal to NaN. → Task 10.
4. **A record directory that is read-only or full mid-run.** The design says an unwritable record is a failed run, not a quiet one, so the write path must raise rather than warn. → Task 9.
5. **PyTorch installed but no CUDA device.** `torch.use_deterministic_algorithms` and the CUDA seed calls behave differently; `environment.accelerator` must be `null` without crashing. → Task 8.

## File Structure

**Created**

| File | Responsibility |
| --- | --- |
| `python/hephkit-lab/pyproject.toml` | Distribution metadata, extras, mypy and coverage config |
| `python/hephkit-lab/moon.yml` | `test`, `test-fast`, `typecheck` tasks mirroring `hephkit`'s |
| `python/hephkit-lab/src/hephkit/lab/__init__.py` | Package docstring, maturity label, public re-exports |
| `.../lab/config.py` | Typed configs, layered resolution, config hash |
| `.../lab/repro.py` | Seeding, deterministic flags, provenance record capture |
| `.../lab/record.py` | Run records: incremental write, registry, read-back |
| `.../lab/replay.py` | Re-execute against frozen inputs, produce a diff report |
| `.../lab/gates.py` | Integrity checks runnable from CI |
| `.../lab/track.py` | MLflow adapter that no-ops when unconfigured |
| `conformance/lab/config.json` | `lab.config` vectors |
| `conformance/lab/record.json` | `lab.record` vectors |
| `conformance/lab/diff.json` | `lab.diff` vectors |
| `compose/mlflow.yaml` | MLflow on Postgres with SeaweedFS artifacts, port 54500 |
| `examples/lab-replay/` | The in-repo gate fixture: records, replays, diffs |
| `docs/adr/0021`–`0024` | The four wave-1 decisions |

**Modified**

| File | Change |
| --- | --- |
| `spec/heph-spec.md` | Bump to 0.5.0 in Task 6 (0.4.0 is taken by PR #22); revise §7 in Task 6; add §8 run records and §9 replay in Task 10 |
| `conformance/schema/vector-file.schema.json` | Three `lab.*` suites in the `suite` enum; `spec` const → 0.5.0 |
| every `conformance/*/*.json` | `spec` field re-stamped to 0.5.0 in Task 10 |
| `spec/errors.yaml` | Four `LAB` codes |
| `spec/modules.yaml` | Replace the `lab.repro` planned row with six shipped rows |
| `tools/check_vectors.py` | `MIN_CASES` for the three new suites |
| `tools/check_modules.py` | Scan a second python tree; resolve dotted module names |
| `python/hephkit/src/hephkit/__init__.py` | **Deleted** (PEP 420) |
| `python/hephkit/pyproject.toml` | **No version edit** (Ruling 16): `release-please-config.json` has a `linked-versions` plugin grouping `hephaestus`, `hephkit-core`, `hephkit-py`, `hephkit` and `go` at one version, so release-please owns the bump and a hand edit breaks `test_manifest_matches_the_versions_in_the_tree` |
| `python/hephkit/tests/test_conformance.py` | Exempt `lab.*` suites from the runner assertion |
| `conformance/moon.yml` | Add `lab/*.json` to inputs |
| `.moon/workspace.yml` | Add `hephkit-lab: 'python/hephkit-lab'` |
| `.github/workflows/python-ci.yml` | Run the `hephkit-lab` tasks |
| `go/internal/fragments/fragments_test.go` | `mlflow` port expectation |
| `go/internal/fragments/files/mlflow.yaml` | Synced copy (generated) |

---

## Wave 0 — shared groundwork

These three tasks touch files the Phase 2 stream is also in. Each lands as its own commit, and the stream note at `side-session-notes/.../phase-3-lab-research-core.md` is updated before each one lands.

### Task 1: Reserve the lab conformance suites

**REWRITTEN BY RULING 1.** PR #22 (Phase 2) already bumps the spec to 0.4.0 and
re-stamps every vector file, so this task no longer does either. It keeps only
the schema enum entries and the moon input glob. **Blocked until #22 merges**
(Ruling 2), because #22 rewrites all thirteen vector files.

The 0.4.0 -> 0.5.0 bump that spec §8–§10 require, with its own full re-stamp,
belongs to Task 10, which is the task that adds those sections.

**Files:**
- Modify: `conformance/schema/vector-file.schema.json` (`suite` enum only)
- Modify: `conformance/moon.yml` (inputs)

**Interfaces:**
- Produces: the suite names `lab.config`, `lab.record`, `lab.diff` accepted by the schema.

- [ ] **Step 1: Confirm PR #22 has merged and rebase onto it**

Run: `git fetch origin && git log --oneline origin/main -3 && grep -n '"const"' conformance/schema/vector-file.schema.json`
Expected: #22's merge commit is on `origin/main`, the branch is rebased onto it, and the const already reads `0.4.0`. If #22 has not merged, do not proceed — work another task.

- [ ] **Step 2: Add the three `lab.*` suites to the schema enum**

In `conformance/schema/vector-file.schema.json`, extend the `suite` enum with `lab.config`, `lab.record`, `lab.diff`. Leave the `spec` const alone.

- [ ] **Step 4: Add the moon input glob only — NOT the `MIN_CASES` entries**

In `conformance/moon.yml`, add `'lab/*.json'` to `check`'s inputs.

Do **not** add `MIN_CASES` entries here. `tools/check_vectors.py:53-56` iterates `MIN_CASES` and reports `missing suite file` for any suite it has not seen, so an entry added before its vector file exists fails `conformance:check` on every commit until that file lands. Each `MIN_CASES` entry is therefore added by the task that creates its suite: `lab.config: 10` in Task 7, `lab.record: 12` in Task 8, `lab.diff: 8` in Task 10.

- [ ] **Step 5: Verify the checker still passes**

Run: `moon run conformance:check`
Expected: PASS, with the existing suites unchanged and no `lab` suite required yet.

- [ ] **Step 6: Commit**

```bash
git add spec/heph-spec.md conformance tools/check_vectors.py
git commit -m "spec: bump to 0.4.0 and reserve the lab conformance suites"
```

### Task 2: Teach `check_modules.py` a second tree and dotted names

**Files:**
- Modify: `tools/check_modules.py:66,209`
- Test: `tools/tests/test_check_modules.py`

**Interfaces:**
- Produces: `spec/modules.yaml` rows named `lab.<name>` with `home: python` resolve to `python/hephkit-lab/src/hephkit/lab/<name>.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_dotted_python_name_resolves_in_lab_tree(tmp_repo):
    # row {name: lab.config, home: python, status: shipped, maturity: experimental}
    # with python/hephkit-lab/src/hephkit/lab/config.py carrying
    # "Maturity: experimental." must produce no error
    assert check_modules(tmp_repo) == []

def test_dotted_name_missing_maturity_label_is_an_error(tmp_repo):
    # same row, module docstring without the label
    assert any("lab.config" in e for e in check_modules(tmp_repo))

def test_module_on_disk_without_a_row_is_still_caught_in_lab_tree(tmp_repo):
    # lab/orphan.py exists, no row
    assert any("orphan" in e for e in check_modules(tmp_repo))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest tools/tests/test_check_modules.py -v`
Expected: FAIL — the lab tree is not scanned.

- [ ] **Step 3: Implement the second tree and dotted-name resolution**

In `tools/check_modules.py`, replace the single `py` root at line 66 and the single `base` at line 209 with an ordered mapping from name prefix to tree: a name containing a `.` resolves under `python/hephkit-lab/src/hephkit/` by replacing `.` with `/`; everything else keeps today's `python/hephkit/src/hephkit` behaviour. Exhaustiveness (a module on disk with no row) must scan both trees.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --with pytest --with pyyaml pytest tools/tests/test_check_modules.py -v`
Expected: PASS

- [ ] **Step 5: Verify the live registry still passes**

Run: `python tools/check_modules.py`
Expected: PASS — no `lab` rows exist yet, so behaviour is unchanged.

- [ ] **Step 6: Commit**

```bash
git add tools/check_modules.py tools/tests/test_check_modules.py
git commit -m "tools(check-modules): resolve dotted module names in a second python tree"
```

### Task 3: Exempt lab suites from `hephkit`'s conformance runner assertion

**Files:**
- Modify: `python/hephkit/tests/test_conformance.py`

**Interfaces:**
- Produces: `conformance/lab/*.json` may exist without a runner in the zero-dependency `hephkit` package; lab suites are run from `python/hephkit-lab/tests/test_conformance.py` instead.

- [ ] **Step 1: Read the existing assertion**

Run: `grep -n "glob\|suite\|runner" python/hephkit/tests/test_conformance.py`
Expected: the test that walks `conformance/` and asserts each file has a runner.

- [ ] **Step 2: Write the failing test**

```python
def test_lab_suites_are_not_required_to_have_a_hephkit_runner(tmp_path):
    # a conformance/lab/<x>.json present must not fail the exhaustiveness check
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd python/hephkit && uv run pytest tests/test_conformance.py -v -k lab`
Expected: FAIL

- [ ] **Step 4: Implement the exemption**

Exclude the `lab/` directory from the runner-exhaustiveness walk, with a comment naming `python/hephkit-lab/tests/test_conformance.py` as where those suites are run and why they cannot run here: `hephkit` must keep zero runtime dependencies.

- [ ] **Step 5: Run the suite to verify it passes**

Run: `cd python/hephkit && uv run pytest tests/test_conformance.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add python/hephkit/tests/test_conformance.py
git commit -m "test(conformance): run lab suites from hephkit-lab, not hephkit"
```

---

## Wave 1 — the integrity spine

### Task 4: Convert `hephkit` to a PEP 420 namespace package (ADR 0021)

**Files:**
- Delete: `python/hephkit/src/hephkit/__init__.py`
- Modify: `python/hephkit/pyproject.toml` (mypy config only — **no version edit**, Ruling 16)
- Create: `docs/adr/0021-hephkit-is-a-namespace-package.md`
- Test: `python/hephkit/tests/test_namespace.py`

**Interfaces:**
- Produces: `hephkit` as a namespace package, so a second distribution can install `hephkit/lab/`. `hephkit.__version__` is gone; callers use `importlib.metadata.version("hephkit")`.

- [ ] **Step 1: Write the failing tests**

```python
def test_hephkit_is_a_namespace_package():
    import hephkit
    assert not hasattr(hephkit, "__file__") or hephkit.__file__ is None

def test_version_is_available_from_metadata():
    from importlib.metadata import version
    assert version("hephkit") == <the version declared in pyproject.toml>

def test_submodules_still_import():
    from hephkit.hashing import content_hash
    from hephkit.money import Money
    assert content_hash({"a": 1}).startswith("sha256:")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit && uv run maturin develop --uv && uv run pytest tests/test_namespace.py -v`
Expected: FAIL — `hephkit.__file__` is set and the version is `0.2.0`.

- [ ] **Step 3: Delete `__init__.py`**

Remove `python/hephkit/src/hephkit/__init__.py`. **Do not touch the version.** Ruling 16: the five packages are a `linked-versions` group in `release-please-config.json`, so release-please computes and applies the bump across all of them from the conventional-commit history; the `!` in `refactor(hephkit)!:` is what tells it this is breaking. Confirm `[tool.maturin]`'s `python-source = "src"` and `module-name = "hephkit._core"` still place the compiled extension inside the namespace directory.

- [ ] **Step 4: Run the whole `hephkit` suite**

Run: `cd python/hephkit && uv run maturin develop --uv && uv run pytest -m "not slow" --cov=hephkit --cov-fail-under=90 && uv run mypy --strict src`
Expected: PASS. If coverage drops because the deleted `__init__.py` held covered lines, it is the denominator that changed, not the tests.

- [ ] **Step 5: Write ADR 0021**

Record: the three mechanisms considered, that `ecosystem.yml` states no consumer has adopted `hephkit` (so the break is nearly free now and expensive later), the loss of `hephkit.__version__` and its replacement, and that `hephkit.ai` will need the same mechanism.

- [ ] **Step 6: Verify ADR numbering**

Run: `python tools/check_adrs.py`
Expected: PASS. **If this fails on a gap at 0020, Phase 2 has not landed its ADR — stop and coordinate.** Do not renumber unilaterally.

- [ ] **Step 7: Commit**

```bash
git add -A python/hephkit docs/adr/0021-hephkit-is-a-namespace-package.md
git commit -m "refactor(hephkit)!: make hephkit a PEP 420 namespace package"
```

### Task 5: The `hephkit-lab` distribution (ADR 0022, 0023)

**Files:**
- Create: `python/hephkit-lab/pyproject.toml`, `moon.yml`, `src/hephkit/lab/__init__.py`, `tests/test_package.py`
- Create: `docs/adr/0022-research-integrity-is-the-spine.md`, `docs/adr/0023-hephkit-lab-ships-separately.md`
- Modify: `.moon/workspace.yml`, `.github/workflows/python-ci.yml`

**Interfaces:**
- Produces: `hephkit.lab` importable; extras `track`, `data`, `causal`, `stats`, `ml`, `flows`, `notebook`, `bio`, `all`; moon tasks `hephkit-lab:test-fast`, `hephkit-lab:typecheck`.

- [ ] **Step 1: Write the failing tests**

```python
def test_lab_imports_with_no_scientific_stack():
    import hephkit.lab  # must not import torch, mlflow, dowhy, dvc, prefect

def test_core_and_lab_coexist_in_one_namespace():
    from hephkit.hashing import content_hash
    from hephkit.lab import __all__ as lab_all
    assert content_hash({}) and isinstance(lab_all, list)

def test_spine_declares_no_heavy_dependencies():
    # parse pyproject: [project].dependencies ⊆ {hephkit, pydantic}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run pytest -v`
Expected: FAIL — the package does not exist.

- [ ] **Step 3: Create the distribution**

`pyproject.toml`: name `hephkit-lab`, version `0.1.0`, `requires-python = ">=3.12"`, `dependencies = ["hephkit>=0.3", "pydantic>=2.9"]`, the nine extras from the design's §7.1.2 table, `[tool.mypy] strict = true`, `[tool.coverage]` matching `hephkit`'s. Build backend: plain `hatchling` — there is no Rust in this package. `src/hephkit/lab/__init__.py` carries the module docstring with `Maturity: experimental.`; there is **no** `src/hephkit/__init__.py`.

- [ ] **Step 4: Wire moon and CI**

`python/hephkit-lab/moon.yml` mirrors `python/hephkit/moon.yml`'s `test`, `test-fast` and `typecheck` tasks, without the maturin step. Add `hephkit-lab: 'python/hephkit-lab'` to `.moon/workspace.yml`. Add a `moon run hephkit-lab:test-fast hephkit-lab:typecheck` step to `.github/workflows/python-ci.yml` after the existing `hephkit` steps.

- [ ] **Step 5: Run the tests and the typecheck**

Run: `moon run hephkit-lab:test-fast hephkit-lab:typecheck`
Expected: PASS

- [ ] **Step 6: Write ADR 0022 and ADR 0023**

0022: research integrity as the spine, superseding the parent design's lab table, with the NeoRx and SAWA evidence. 0023: separate distribution, the extras partition, Ligase as a leaf with the dependency direction reversed, and that `ligase-bio` and `causalphylo` are on PyPI.

- [ ] **Step 7: Commit**

```bash
git add python/hephkit-lab .moon/workspace.yml .github/workflows/python-ci.yml docs/adr/0022-research-integrity-is-the-spine.md docs/adr/0023-hephkit-lab-ships-separately.md
git commit -m "feat(lab): add the hephkit-lab distribution"
```

### Task 6: Provenance record in the spec (ADR 0024) and the LAB error codes

**Files:**
- Modify: `spec/heph-spec.md` (§7 revision)
- Modify: `spec/errors.yaml`
- Create: `docs/adr/0024-provenance-record-splits-hashes-from-environment.md`
- Modify: `python/hephkit/src/hephkit/errors/_codes.py` (generated)

**Interfaces:**
- Produces: spec §7 with `run_id`, `config_hash`, `data_hash`, `deps_hash`, `code_sha`, `class`, `environment`; the preconditions for `deterministic`; codes `HEPH-LAB-422`, `HEPH-LAB-409`, `HEPH-LAB-424`, `HEPH-LAB-412`.

- [ ] **Step 0: Bump the spec to 0.5.0 and re-stamp the vectors (Ruling 19)**

This task, not Task 10, owns the version bump: it is the **first** task in the wave to change `spec/heph-spec.md`, and leaving the spec modified while it still declares `0.4.0` would make that version name two different specs mid-branch. Set `- **Version:** 0.5.0` in `spec/heph-spec.md`, set `"const": "0.5.0"` in `conformance/schema/vector-file.schema.json`, and re-stamp the `"spec"` field of every file under `conformance/*/`. PR #22 took `0.4.0` for the idempotency spec change, so this wave's spec work lands in `0.5.0`.

Run afterwards: `uv run tools/check_vectors.py`
Expected: PASS with every vector file at `0.5.0`.

- [ ] **Step 1: Revise spec §7**

Remove "Status: draft". Add `deps_hash` (normative, content hash of the lockfile) and `environment` (descriptive, never compared on replay) with the field table from the design's §9.2. Add §7.3: a run is `provenance-only` unless the working tree is clean **and** a lockfile exists. Keep `provenance-only` hyphenated.

- [ ] **Step 2: Add the four LAB codes**

In `spec/errors.yaml`, append the four codes with `area: LAB`. Each needs a caller-facing `detail_hint` and a developer-facing `guidance` that differs from it — `HEPH-LAB-409` is the one a reviewer reads, so its guidance says to read the diff report rather than re-run.

- [ ] **Step 3: Regenerate and verify**

Run: `python tools/gen_errors.py && moon run hephkit:gen-errors && python tools/check_adrs.py && uv run tools/gen_error_pages.py --check`
Expected: the generated `_codes.py` and error pages are regenerated and `--check` passes. Never hand-edit either.

- [ ] **Step 4: Write ADR 0024**

Record why `deps_hash` is normative and `environment` is not: putting the GPU driver in the determinism contract means nothing reproduces across machines and the label becomes decorative. Record the hostname exclusion and the two `deterministic` preconditions as the user's decisions.

- [ ] **Step 5: Commit**

```bash
git add spec docs/adr/0024-provenance-record-splits-hashes-from-environment.md python/hephkit/src/hephkit/errors/_codes.py docs/site
git commit -m "spec(provenance): split normative hashes from descriptive environment"
```

### Task 7: `lab.config`

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/config.py`
- Create: `conformance/lab/config.json`
- Test: `python/hephkit-lab/tests/test_config.py`, `tests/test_conformance.py`

**Interfaces:**
- Consumes: `hephkit.hashing.content_hash`.
- Produces: `class ExperimentConfig(BaseModel)`; `resolve(model: type[C], *, defaults: dict, file: Path | None, env: Mapping[str, str], argv: Sequence[str]) -> C`; `config_hash(cfg: BaseModel) -> str`; `ConfigError(ValueError)` with `.code == "HEPH-LAB-422"`.

- [ ] **Step 1: Write the vectors**

`conformance/lab/config.json`, suite `lab.config`, at least 10 cases, hand-derived — never produced by running this code. Cover: each layer alone; full precedence chain defaults < file < env < CLI; a CLI override of a nested field; an unknown CLI key rejected; a type coercion that must fail; and two cases pinning `config_hash` for a config whose hash is derivable from the existing `hashing.content` vectors.

- [ ] **Step 2: Write the failing tests**

```python
def test_precedence_cli_beats_env_beats_file_beats_defaults(): ...
def test_unknown_cli_key_raises_config_error_naming_the_key(): ...
def test_config_hash_is_stable_across_key_order(): ...
def test_numpy_scalar_in_config_raises_config_error_naming_the_field():
    # Review Focus 1 — np.float32(0.1) must not surface a raw json TypeError
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run pytest tests/test_config.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement `config.py`**

Layered resolution in the order above. `config_hash` delegates to `content_hash(cfg.model_dump(mode="json"))`. For Review Focus 1: catch the serialisation failure and re-raise as `ConfigError` carrying the offending field path — `model_dump(mode="json")` is what converts known types, so the error path is for types pydantic does not know.

- [ ] **Step 4a: Add this suite's `MIN_CASES` entry**

In `tools/check_vectors.py`, add `"lab.config": 10`. It lands with the suite file, never before it (see Task 1 Step 4).

- [ ] **Step 5: Add the conformance runner**

`python/hephkit-lab/tests/test_conformance.py` loads `conformance/lab/*.json` and drives each suite, mirroring `python/hephkit/tests/test_conformance.py`'s structure.

- [ ] **Step 6: Run tests, typecheck and the vector checker**

Run: `moon run hephkit-lab:test-fast hephkit-lab:typecheck conformance:check`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add python/hephkit-lab conformance/lab/config.json tools/check_vectors.py
git commit -m "feat(lab): typed experiment configs with layered overrides"
```

### Task 8: `lab.repro`

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/repro.py`
- Create: `conformance/lab/record.json`
- Test: `python/hephkit-lab/tests/test_repro.py`

**Interfaces:**
- Consumes: `hephkit.hashing.content_hash`; `lab.config.config_hash`.
- Produces: `class ProvenanceRecord(BaseModel)` with the seven spec §7 fields; `seed_everything(seed: int) -> None`; `capture(*, run_id: str, config_hash: str, data_hash: str, repo: Path) -> ProvenanceRecord`; `ReproError(RuntimeError)` with `.code == "HEPH-LAB-424"`.

- [ ] **Step 1: Write the vectors**

`conformance/lab/record.json`, suite `lab.record`, at least 12 cases, hand-derived from spec §7 as revised. Cover: serialisation field order and types; `class` assignment for clean-tree-with-lockfile, dirty tree, missing lockfile, and both missing; `environment.frameworks` recording a `null` for an absent framework; `environment.accelerator` as `null`; and rejection of a record missing a normative field.

- [ ] **Step 2: Write the failing tests**

```python
def test_clean_tree_with_lockfile_is_deterministic(): ...
def test_dirty_tree_is_provenance_only(): ...
def test_missing_lockfile_is_provenance_only(): ...
def test_seed_everything_is_reproducible_for_stdlib_and_numpy_if_present(): ...
def test_not_a_git_repository_is_provenance_only_not_an_error():
    # Review Focus 2 — also covers no commits and detached HEAD
def test_torch_without_cuda_records_null_accelerator():
    # Review Focus 5 — skipif torch absent
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run pytest tests/test_repro.py -v`
Expected: FAIL

- [ ] **Step 4: Implement `repro.py`**

`seed_everything` seeds `random` and `PYTHONHASHSEED`, then NumPy and PyTorch **behind import guards**, setting `torch.use_deterministic_algorithms(True)` only when torch is importable. `capture` reads the git SHA and tree cleanliness by invoking `git` in `repo`; any git failure, including not-a-repository, yields `provenance-only` rather than raising. `deps_hash` is `content_hash_bytes` of the lockfile when one exists at `repo/uv.lock`, else `None` and `provenance-only`.

- [ ] **Step 4a: Add this suite's `MIN_CASES` entry**

In `tools/check_vectors.py`, add `"lab.record": 12`.

- [ ] **Step 5: Run tests, typecheck and the vector checker**

Run: `moon run hephkit-lab:test-fast hephkit-lab:typecheck conformance:check`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add python/hephkit-lab conformance/lab/record.json tools/check_vectors.py
git commit -m "feat(lab): seeding and provenance record capture"
```

### Task 9: `lab.record`

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/record.py`
- Test: `python/hephkit-lab/tests/test_record.py`

**Interfaces:**
- Consumes: `lab.repro.ProvenanceRecord`.
- Produces: `class RunRecord` with `append_row(cell: str, values: Mapping[str, float | str]) -> None`, `summary() -> dict`, `path: Path`; `open_record(dir: Path, provenance: ProvenanceRecord) -> RunRecord`; `read_record(path: Path) -> RunRecord`; `register(name: str) -> Callable` and `run(name: str, dir: Path) -> RunRecord`; `RecordError(RuntimeError)` with `.code == "HEPH-LAB-424"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_rows_are_on_disk_before_the_run_ends(): ...
def test_killing_the_process_mid_run_keeps_completed_rows():
    # subprocess that appends two rows then os._exit(1); both must be readable
def test_summary_must_agree_with_rows(): ...
def test_registered_experiment_cannot_choose_its_output_path():
    # the registered callable receives a RunRecord and has no dir argument
def test_unwritable_record_directory_raises_rather_than_warning():
    # Review Focus 4 — chmod 0o500 the dir; RecordError, not a logged warning
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run pytest tests/test_record.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `record.py`**

Rows append as JSON Lines and are flushed and `os.fsync`ed per row, so a crash costs at most the in-flight row. The provenance record is written as a header file at open time. Nothing in this module swallows an exception: every write failure raises `RecordError`.

- [ ] **Step 4: Run the tests and the typecheck**

Run: `moon run hephkit-lab:test-fast hephkit-lab:typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/hephkit-lab
git commit -m "feat(lab): crash-safe run records and the experiment registry"
```

### Task 10: `lab.replay` and spec §8–§9

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/replay.py`
- Create: `conformance/lab/diff.json`
- Modify: `spec/heph-spec.md` (add §8 run records, §9 replay and diff; bump to 0.5.0)
- Modify: `conformance/schema/vector-file.schema.json` (`spec` const -> 0.5.0)
- Modify: every `conformance/*/*.json` (`spec` field -> 0.5.0)
- Test: `python/hephkit-lab/tests/test_replay.py`

**Interfaces:**
- Consumes: `lab.record.RunRecord`, `read_record`.
- Produces: `class Difference(BaseModel)` with `cell`, `key`, `recorded`, `replayed`; `class DiffReport(BaseModel)` with `matched: bool`, `differences: list[Difference]`; `replay(record: Path, *, experiment: str) -> DiffReport`; `ReplayError(RuntimeError)` with `.code == "HEPH-LAB-409"`.

- [ ] **Step 0a: Add a reserved §10 (Ruling 21)**

§7.1 forward-references §10 for the digest scope of `data_hash`, and §10 belongs to a later wave with `lab.data` — so without this the shipped spec points at a section that does not exist. Add a short reserved §10 ("Dataset manifests"), stating that the section is not yet specified and that the digest scope of `data_hash` (§7.1) is settled there. This mirrors how §7 itself was carried as a draft before this wave, so it is consistent with repo practice rather than a new device.

- [ ] **Step 1: Write spec §8 and §9**

§8: record structure, incremental write semantics, and that an unwritable record is a failed run. §9: what a replay compares (the normative hashes of §7, never `environment`), what a difference report contains, that float comparison uses a stated tolerance, and that NaN compares equal to NaN for replay purposes.

**Ruling 19 moved the version bump to Task 6**, which is the first task in the wave to touch the spec. By the time this task runs the spec already declares `0.5.0`, and §8–§10 land inside that same unreleased version, so **do not bump again**. Re-stamp only the `lab/` suite files if Tasks 7 and 8 created them before the bump landed.

Run afterwards: `moon run conformance:check`
Expected: PASS with every vector file at 0.5.0.

- [ ] **Step 2: Write the vectors**

`conformance/lab/diff.json`, suite `lab.diff`, at least 8 cases, hand-derived: identical records match; one changed metric names exactly that cell and key; a changed `environment` does **not** produce a difference; a changed `deps_hash` does; NaN against NaN matches; NaN against a number differs; a missing cell; an extra cell.

- [ ] **Step 3: Write the failing tests**

```python
def test_identical_run_replays_and_matches(): ...
def test_perturbed_input_names_the_changed_value(): ...
def test_environment_difference_does_not_break_a_match(): ...
def test_nan_matches_nan():
    # Review Focus 3
def test_replay_with_network_blocked_still_matches(): ...
```

- [ ] **Step 4: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run pytest tests/test_replay.py -v`
Expected: FAIL

- [ ] **Step 5: Implement `replay.py`**

Re-run the named registered experiment against the record's frozen inputs and compare row by row. A difference is reported, not raised; `ReplayError` is for a record that cannot be read or an experiment name that is not registered. NaN-equals-NaN is explicit, since `==` gives the wrong answer.

- [ ] **Step 5a: Add this suite's `MIN_CASES` entry**

In `tools/check_vectors.py`, add `"lab.diff": 8`.

- [ ] **Step 6: Run tests, typecheck and the vector checker**

Run: `moon run hephkit-lab:test-fast hephkit-lab:typecheck conformance:check`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add python/hephkit-lab conformance/lab/diff.json spec/heph-spec.md tools/check_vectors.py
git commit -m "feat(lab): replay a record and diff the result"
```

### Task 11: `lab.gates`

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/gates.py`
- Test: `python/hephkit-lab/tests/test_gates.py`, `tests/fixtures/violations/`

**Interfaces:**
- Consumes: `lab.record.read_record`, `lab.replay.replay`.
- Produces: `find_hardcoded_metrics(paths: Iterable[Path]) -> list[Violation]`; `check_records_wellformed(dir: Path) -> list[Violation]`; `check_cited_runs(manuscript: Path, records: Path) -> list[Violation]`; `check_all(...) -> list[Violation]`; `GateError(RuntimeError)` with `.code == "HEPH-LAB-412"`.

- [ ] **Step 1: Write the failing tests, each with a violating fixture**

```python
def test_figure_script_with_a_literal_metric_is_caught():
    # fixtures/violations/figure_with_literals.py holds f1 = 0.474
def test_record_whose_summary_disagrees_with_its_rows_is_caught(): ...
def test_manuscript_citing_a_missing_run_is_caught(): ...
def test_manuscript_citing_an_unreplayable_run_is_caught(): ...
def test_clean_inputs_produce_no_violations(): ...
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run pytest tests/test_gates.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `gates.py`**

`find_hardcoded_metrics` parses with `ast` and flags a float literal assigned to a name matching a metric vocabulary — a regex over source would flag version strings and axis limits. Each check returns violations; `check_all` is what CI calls and raises `GateError` when any is non-empty.

- [ ] **Step 4: Run the tests and the typecheck**

Run: `moon run hephkit-lab:test-fast hephkit-lab:typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/hephkit-lab
git commit -m "feat(lab): integrity gates for figures, records and citations"
```

### Task 12: The `mlflow` Compose fragment

**Files:**
- Create: `compose/mlflow.yaml`
- Modify: `go/internal/fragments/fragments_test.go`
- Generate: `go/internal/fragments/files/mlflow.yaml`
- Modify: `compose/test/boot_test.sh` if it enumerates fragments

**Interfaces:**
- Produces: an `mlflow` fragment on host port **54500**, backend store Postgres, artifact store the SeaweedFS S3 endpoint from the `objects` fragment.

- [ ] **Step 1: Write the failing port test**

In `go/internal/fragments/fragments_test.go`, add `"mlflow": {54500}` to the expected port map in `TestResolveFrom`'s table and include `"mlflow"` in the resolved set.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd go && go test ./internal/fragments/ -run TestResolveFrom -v`
Expected: FAIL — no such fragment.

- [ ] **Step 3: Write the fragment**

`compose/mlflow.yaml`, following `postgres.yaml`'s shape: first-line `#` header ending `maturity: experimental`, a comment naming the 54500 port and that it is dev-only, `depends_on` postgres and the objects service with `condition: service_healthy`, and a healthcheck on MLflow's `/health`.

- [ ] **Step 4: Sync the embedded copy and verify**

Run: `moon run heph-cli:sync-fragments && cd go && go test ./... && go vet ./... && staticcheck ./...`
Expected: PASS. Never hand-edit `go/internal/fragments/files/mlflow.yaml`.

- [ ] **Step 5: Boot it**

Run: `bash compose/test/boot_test.sh`
Expected: PASS with MLflow healthy.

- [ ] **Step 6: Commit**

```bash
git add compose/mlflow.yaml go/internal/fragments
git commit -m "feat(compose): self-hosted mlflow fragment on postgres and seaweedfs"
```

### Task 13: `lab.track`

**Files:**
- Create: `python/hephkit-lab/src/hephkit/lab/track.py`
- Test: `python/hephkit-lab/tests/test_track.py`

**Interfaces:**
- Consumes: `lab.record.RunRecord`, `lab.repro.ProvenanceRecord`.
- Produces: `is_enabled() -> bool`; `tracked_run(name: str, *, provenance: ProvenanceRecord, tags: Mapping[str, str] | None = None) -> ContextManager[TrackedRun]`; `TrackedRun` with `log_params`, `log_metrics`, `log_artifact`, `log_dict`, `set_tags`.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_call_is_a_noop_when_tracking_uri_is_unset(): ...
def test_context_manager_enters_even_when_mlflow_is_unreachable(): ...
def test_provenance_class_is_logged_as_a_tag(): ...
def test_import_does_not_require_mlflow(): ...
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd python/hephkit-lab && uv run pytest tests/test_track.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `track.py`**

`MLFLOW_TRACKING_URI` is the only knob and there is no default, so tests are hermetic. mlflow is imported lazily inside the context manager, behind the `track` extra. Every logging call swallows its exception and warns: a missing tracking server must never break a run. The provenance `class` and `run_id` go on as tags, which is how a reviewer finds a run's class in the UI.

- [ ] **Step 4: Run the tests and the typecheck**

Run: `moon run hephkit-lab:test-fast hephkit-lab:typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/hephkit-lab
git commit -m "feat(lab): mlflow tracking that no-ops when unconfigured"
```

### Task 14: The in-repo gate, module rows and docs

**Files:**
- Create: `examples/lab-replay/` (`experiment.py`, `moon.yml`, `pyproject.toml`, `gate_test.sh`)
- Modify: `spec/modules.yaml` (six shipped rows)
- Modify: `.github/workflows/ci.yml` (call the gate)
- Create: docs pages for the six modules
- Modify: `.moon/workspace.yml`

**Interfaces:**
- Produces: the gate the design's §11 makes this wave's definition of done.

- [ ] **Step 1: Write the gate script**

`examples/lab-replay/gate_test.sh`: run the fixture experiment, replay it with the network blocked, assert `matched`; run a perturbed variant and assert the diff names the changed value; run `check_all` against the violating fixtures and assert it fails. Frozen inputs are synthetic and generated by the fixture, so nothing third-party is redistributed.

- [ ] **Step 2: Run it to verify it fails**

Run: `bash examples/lab-replay/gate_test.sh`
Expected: FAIL — the experiment does not exist yet.

- [ ] **Step 3: Write the fixture experiment**

A registered experiment with two cells over synthetic data, deterministic under a fixed seed, with one input the perturbed variant changes.

- [ ] **Step 4: Add the module rows and regenerate `reference/modules.mdx`**

Six rows in `spec/modules.yaml`: `lab.config`, `lab.repro`, `lab.record`, `lab.replay`, `lab.gates`, `lab.track` — all `home: python`, `status: shipped`, `maturity: experimental`, with `spec_section` `null` except `lab.repro` (`"7"`), `lab.record` (`"8"`) and `lab.replay` (`"9"`). Replace the existing `{name: lab.repro, status: planned, phase: 3}` row.

Run: `uv run tools/gen_site_pages.py && uv run tools/gen_site_pages.py --check`
Expected: `reference/modules.mdx` regenerated, then `--check` PASS. Never hand-edit it.

- [ ] **Step 4a: Write the six docs pages with runnable examples**

CLAUDE.md requires every new module to ship "a docs page with a runnable example", and no per-module pages exist yet — the site is almost entirely generated, so these are new **hand-written** content, which `gen_site_pages.py --check` does not manage and must not claim.

**Ruling 3:** these go under `docs/site/content/modules/`, the convention PR #22
establishes with `docs/site/content/modules/idempotency.mdx` — not the
`docs/site/content/docs/lab/` path an earlier draft of this plan guessed. Match
whatever `_meta.ts` structure #22 leaves behind.

Create one `.mdx` page per module under `docs/site/content/modules/`, named for the module. Each page: what the module is for in two or three sentences, the maturity label, and one example a reader can paste and run. The `lab.repro` and `lab.replay` pages link to their spec sections (§7, §9); the `lab.replay` page's example is the perturbed-input diff, because the diff report is the thing a reviewer actually reads.

- [ ] **Step 4b: Build the site and check its links**

Run: `bun install --frozen-lockfile && bun run --cwd docs/site build && bun test --cwd docs/site && uv run tools/check_site_links.py`
Expected: PASS. A broken link to a spec section is the likely failure here.

- [ ] **Step 5: Wire the gate into CI**

Add `examples-lab-replay: 'examples/lab-replay'` to `.moon/workspace.yml` and a step in `.github/workflows/ci.yml` that runs the gate, beside the existing five-minute path.

- [ ] **Step 6: Run the full repo verification**

Run each and read the output:

```bash
moon run hephkit-lab:test-fast hephkit-lab:typecheck
cd python/hephkit && uv run maturin develop --uv && uv run pytest -m "not slow" --cov=hephkit --cov-fail-under=90 && uv run mypy --strict src
cd ../.. && python tools/check_adrs.py && python tools/check_registry.py && python tools/check_vectors.py && python tools/check_modules.py
uv run tools/gen_error_pages.py --check && uv run tools/gen_site_pages.py --check && uv run tools/gen_quickstart.py --check
bash examples/lab-replay/gate_test.sh
```

Expected: all PASS. Paste any failure rather than summarising it.

- [ ] **Step 7: Commit and open the PR**

```bash
git add -A
git commit -m "feat(lab): in-repo replay gate, module rows and docs pages"
```

PR body names every shared file touched: `spec/heph-spec.md`, `spec/errors.yaml`, `spec/modules.yaml`, `conformance/schema/vector-file.schema.json`, every re-stamped vector file, `python/hephkit/`, `tools/check_modules.py`, `tools/check_vectors.py`, `.moon/workspace.yml`, `.github/workflows/`, `go/internal/fragments/`.

---

## Waves 2–5

Not planned here. Each gets its own plan at `docs/superpowers/plans/YYYY-MM-DD-hephkit-lab-<wave>.md`, written when the wave starts, because each depends on interfaces this wave produces and planning them now would guess at those interfaces:

- **Wave 2, proof:** `lab.data`, `lab.sources`, `lab.causal` (ADR 0025, CausalPhylo), `lab.stats`; spec §10.
- **Wave 3, scale:** `lab.bench`, `lab.flows`, `lab.notebook`.
- **Wave 4, models:** `lab.train`, `lab.embed`, `lab.rl` — CPU-only CI, so thin adapters.
- **Wave 5, output:** `lab.paper`, `lab.lit`, `lab.bio`.
