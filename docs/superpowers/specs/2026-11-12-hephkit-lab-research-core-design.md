# hephkit.lab — the research core

**Status: draft, awaiting approval.** Supersedes the `hephkit.lab` table in
`docs/superpowers/specs/2026-11-04-hephaestus-design.md` (lines 318–335).

## 1. Intent

Hephaestus already refuses to produce a plausible wrong number on the product
side: money is integer minor units, hashes are canonical, idempotency is
relational. `hephkit.lab` is the same refusal applied to research.

The original design treated the lab tier as convenience wrappers over MLflow,
DVC and DoWhy — useful, but the kind of thing a researcher reimplements per
project and then quietly stops using. An inventory of the work this kit is
meant to serve (SAWA, NeoRx, CausalPhylo, Ligase, Adam) shows those repos have
already converged, independently, on something stronger and harder-won.

From `neorx/src/neorx/experiments/`:

- `record.py` — "no number without a record", written incrementally so that a
  crash costs the current cell rather than the run: "the failure that lost 881
  seconds of the original RL benchmark and led to its numbers being retyped by
  hand."
- `replay.py` — re-executes a recorded run against frozen inputs and diffs it.
  "A replay that differs is not a failure of the tool — it names exactly which
  values moved, which is the information a reviewer actually needs."
- `capture.py` — freezes the HTTP inputs so a run replays without the network.
- `gates.py` — the checks that came out of a manuscript audit: F1 values held
  as literals in `_gen_figures.py`, so "Figure 3 was a transcription of a table
  rather than a rendering of data"; records whose summary disagrees with their
  rows; a manuscript citing a run that does not exist or that nobody can
  reproduce.
- `registry.py` — an experiment never opens a file and never decides where
  results go, which is "what makes 'a number cannot exist without a record'
  structural rather than a habit."

From `neorx/src/neorx/snapshots/`: temporal honesty. "A dated run must evaluate
the population that date would have evaluated" — otherwise there is hindsight
in the sampling frame, which is as fatal to a result as hindsight in the
predictor. The extractor version is recorded beside the release id, and the
digest is taken over the extract actually written rather than the upstream file.

SAWA reached for the same instinct separately: the Stanford HIVdb client sits
behind a sha256 cache with algorithm-version pinning and an offline replay mode,
and `phylo/` emits a per-run `partition_report.parquet` carrying a per-subtype
decision and its reason "for reviewer-grade reproducibility".

**So the spine of `hephkit.lab` is research integrity, and tracking is a view
onto it rather than its foundation.** Four claims the kit makes structurally
true:

1. A number cannot exist without a record.
2. A record replays, and a replay that differs says which values moved.
3. Inputs are frozen, content-addressed and temporally honest.
4. CI refuses a result, a figure or a manuscript that breaks any of the above.

## 2. Goals

- One kit carries a research project from raw input to published figure without
  the researcher writing provenance plumbing per project.
- Any reported number is traceable to the config, data, code and environment
  that produced it, and the traceability is enforced rather than encouraged.
- A run that claims `deterministic` genuinely re-executes to an identical
  result, proven by a replay test in CI.
- A run that cannot reproduce says so honestly and is still fully traceable.
- Reuses the shipped Rust core for hashing. No new hashing is written.
- Adopts what already exists and works — CausalPhylo, Ligase, MLflow, DVC,
  DoWhy, Prefect — rather than rebuilding commodity capability.

## 3. Non-goals

- `lab.cogsci` (jsPsych, PyDDM, human-subjects records). Specced in the parent
  design, no harvest source yet; Adam is a cognitive architecture, not
  human-subjects work. Revisit when a cog-sci project exists.
- Domain science itself. Alignment, phylogenetics, docking, folding and
  structure prediction stay in SAWA, NeoRx and Ligase. `hephkit.lab` is the
  substrate they stand on.
- Hosted or multi-tenant infrastructure. MLflow is self-hosted via Compose; GPU
  scheduling is a work-pool concern, not this kit's.
- Replacing the Rust core's role. Nothing here does canonicalisation or hashing
  of its own.

## 4. Anti-goals

Things that would make this a failure even if every test passed:

- **A kit that gets switched off.** If tracking, recording or gating makes a run
  slower or more annoying than not using them, they will be bypassed under
  deadline. Tracking must no-op cleanly when unconfigured (SAWA's single best
  idea), and recording must never lose a run's work to a crash.
- **`deterministic` as an aspiration.** A label nothing can actually wear is
  worse than no label. If the environment is part of the determinism contract,
  no run ever reproduces across machines and the label becomes decorative.
- **A spec written around existing code.** Back-filling vectors from NeoRx's
  behaviour would pin whatever that code happens to do, including its bugs.
- **A bio-shaped general kit.** If `hephkit-lab` core imports a computational
  biology engine, every non-bio ingot pays for it and the layering is lost.
- **Silent widening of Phase 3.** This document supersedes a published design
  table; that is an ADR and a re-cut rollout, not a quiet scope creep.

## 5. Constraints

From `CLAUDE.md`, binding:

- **Rule 1, spec first.** Behaviour is defined in `spec/heph-spec.md` and pinned
  by `conformance/` vectors or contract tests before implementation. Changing
  behaviour means spec plus vectors in the same PR, plus an ADR if a decision
  moved.
- **Rule 2, vectors from independent sources.** Never generated by running our
  own implementation. For this kit that is the sharpest constraint: see §9.
- **Rule 3, one home per capability.** No hand-porting between languages.
- **Rule 4,** the Rust core does no I/O and never panics on input.
- **Rule 7, maturity.** Everything here starts `experimental`, with a row in
  `spec/modules.yaml` equal to its in-source `Maturity:` label.
- **Rule 8, adopt before building.** Checked per module in §7.
- **Rule 9, IP boundary.** Harvest only from NeoForge and cod3smith. SAWA
  (`Neoforge-Labs/SAWA`, on disk at `~/Mirror/Bio-CPS/hiv-dr-watch`), NeoRx,
  CausalPhylo, Ligase and Nocturna all qualify. DataQRL and Backbone do not.

Operational:

- Error codes live only in `spec/errors.yaml`, matching `^HEPH-[A-Z]{2,6}-\d{3}$`.
- Local host ports come from the 54xxx block.
- ADR numbering is contiguous from 0001. This stream owns **0021 and up**;
  Phase 2 holds 0020, so 0021 waits for 0020 to land.
- A second stream is working Phase 2 concurrently. `spec/errors.yaml`,
  `spec/modules.yaml`, `conventions/attributes.yaml` and everything generated
  from them are the collision surface: touch in as few commits as possible,
  always regenerate, never hand-edit.

## 6. Approaches

Three ways to build seventeen modules were considered.

**A. Spine first, with one real analysis proving it.** Build `lab.config`,
`lab.repro`, `lab.record`, `lab.replay` and `lab.gates` to completion — spec
sections, vectors, a replay-and-diff test in CI — then prove the contract
against one real SAWA causal analysis before the remaining twelve modules lean
on it, then work outward. Trades early breadth for a contract that is enforced
before anything depends on it.

**B. Vertical slice.** Drive one analysis end to end through every layer with
each module as thin as possible. Reaches a genuine phase gate soonest and makes
the whole chain tangible early. Rejected: seventeen modules would all take
their shape from one HIV drug-resistance analysis, and the NeoRx
knowledge-graph case then forces churn through every one of them. The
integrity contract is the part most expensive to get wrong and most expensive
to change later.

**C. Adopt and wrap.** Lift NeoRx's `experiments/` and `snapshots/` across close
to intact, adopt CausalPhylo, and write the spec to describe what already works.
Fastest to comprehensive, and the code is battle-tested by a real manuscript
audit. Rejected: it inverts rule 1 — the spec and vectors are meant to pin
behaviour before an implementation exists, and a spec written around working
code pins that code's accidents too. It also imports NeoRx-shaped assumptions
(seven named HTTP sources, a disease corpus, a date-to-release table verified
against one archive on one day).

**Chosen: A.** NeoRx and SAWA become harvest *sources* in the rule-9 sense —
read for their lessons, rewritten against a spec written first. This was my
call, not the user's; it and the packaging call in §7.1 are the two decisions
to check while reading.

## 7. Architecture

### 7.1. Packaging — my call

`hephkit-lab` ships as its own distribution depending on `hephkit`, rather than
as extras on `hephkit`.

Reason: `hephkit` today has **zero** runtime dependencies, and that is a large
part of what it is for. The lab surface needs torch, dowhy, mlflow, dvc,
prefect, polars, duckdb and marimo. Putting those behind extras on `hephkit`
means the correctness kit's dependency tree is mostly machine learning, and a
product service installing `hephkit[settings]` resolves against a package whose
metadata is dominated by research tooling. A separate distribution keeps both
honest and lets the lab stack version independently.

Layout:

```
python/hephkit-lab/              own pyproject, depends on hephkit
  src/hephkit/lab/               namespace package under hephkit
    config.py  repro.py  record.py  replay.py  gates.py
    data/  sources/  causal/  stats.py  bench.py
    track.py  flows/  notebook.py  paper/  lit.py
    train.py  embed.py  rl.py
    bio.py                       requires the `bio` extra
```

#### 7.1.1. How the shared namespace actually works — my call

Two distributions cannot both own a regular package directory. Today
`python/hephkit/src/hephkit/__init__.py` exists and sets
`__version__ = "0.2.0"`, so `hephkit` is a regular package and three mechanisms
were possible:

- Co-install both distributions into one `site-packages/hephkit/`. Imports
  work, but two dists writing one directory breaks uninstall, `py.typed`
  resolution under `mypy --strict`, and above all the
  `uv run maturin develop --uv` loop CLAUDE.md mandates, because an editable
  install pins `hephkit.__path__` to a single source tree.
- Convert `hephkit` to a PEP 420 native namespace package. Breaking for a
  published 0.2.0 wheel and `hephkit.__version__` goes away.
- Ship the import path as `hephkit_lab` and abandon the dotted name.

**Chosen: PEP 420.** The decisive fact is that nothing has adopted `hephkit`
yet — `.github/workflows/ecosystem.yml` says so in its own header, with every
consumer row disabled because "none has". A breaking packaging change costs
approximately nothing today and is expensive at any later point, and the same
mechanism is what `hephkit.ai` will need. `hephkit/__init__.py` is removed, its
docstring moves to the docs page, and `hephkit.__version__` is replaced by
`importlib.metadata.version("hephkit")`, which is documented as a migration
note and bumps `hephkit` to 0.3.0.

This is recorded as ADR 0021, and it means **wave 1 edits
`python/hephkit/`** — a tree the Phase 2 stream also touches. §13 covers the
coordination.

#### 7.1.2. `hephkit-lab`'s own extras — my call

The §4 anti-goal about non-bio ingots paying for a bio engine applies with
equal force to non-ML projects paying for an ML stack, so the heavy
dependencies are partitioned rather than required:

| Install | Pulls |
| --- | --- |
| `hephkit-lab` | `hephkit`, pydantic — the whole integrity spine |
| `[track]` | mlflow |
| `[data]` | dvc, polars, duckdb |
| `[causal]` | dowhy, causal-learn, causalphylo |
| `[stats]` | scipy |
| `[ml]` | torch, accelerate, safetensors, transformers |
| `[flows]` | prefect |
| `[notebook]` | marimo |
| `[bio]` | ligase-bio |
| `[all]` | everything above |

The spine — config, repro, record, replay, gates — therefore installs with no
scientific stack at all, which is what lets wave 1's CI stay fast and what lets
a project adopt the integrity guarantees without adopting our tool choices.

Consequence for behaviour, not just packaging: `lab.repro` seeds NumPy and
PyTorch **conditionally**, and the provenance record states which frameworks
were present rather than assuming any. That is specified in §9.2, not left to
the builder.

#### 7.1.3. Typing markers across portions — established by experiment

`mypy` resolves a PEP 561 `py.typed` marker **per `sys.path` entry, not per
logical namespace**. Verified in both install shapes during wave 1: with a second
portion on its own `.pth` — exactly what `uv run maturin develop --uv` produces,
since it writes a `.pth` holding the source-tree path — `hephkit/py.typed` does
**not** make that tree's `hephkit.lab` typed. It reports `import-untyped` and
silently degrades to `Any`, while `hephkit.money` resolves correctly from the
same import. External consumers of a real wheel are unaffected and stay fully
typed; the failure is specific to a second portion on its own path entry, which
is the development loop CLAUDE.md mandates.

So:

- `hephkit` keeps `hephkit/py.typed`. Its modules sit directly in the namespace
  directory, there is no deeper placement available, and it owns that path alone.
- **Every later portion ships its marker inside the subpackage it alone owns** —
  `hephkit/lab/py.typed`, and `hephkit/ai/py.typed` when that arrives.
- `hephkit-lab` must **not** ship `hephkit/py.typed`. It would type-check, but in
  a merged `pip install` layout two distributions would own one file, which is the
  exact collision §7.1.1 exists to prevent.

Deleting `hephkit/__init__.py` also breaks `mypy --strict src` outright with
"Source file found twice under different module names", so `[tool.mypy]` carries
`mypy_path = "src"` and `explicit_package_bases = true` — mypy's documented
namespace-package fix, taken in preference to weakening `--strict`.

### 7.2. Dependency layering

```
hephkit-core (Rust)
      │
   hephkit            ← zero runtime deps: hashing, money, errors, settings
      │
 hephkit-lab          ← domain-agnostic research integrity
   │        │
   │   hephkit-lab[bio] → ligase-bio
   │
 SAWA, NeoRx, Adam, any ingot
```

Rules that fall out, and must hold:

- `hephkit-lab` core never imports a domain library. `lab.bio` is the only
  module permitted to import `ligase-bio`, and it lives behind the `bio` extra.
- **Ligase stays a leaf.** It must not take a dependency on `hephkit-lab`, or
  the two cycle. This reverses the parent design's "Ligase depends on
  `hephkit-core` and `hephkit.lab`, never the reverse" — see ADR 0023 (§10).
  Ligase may depend on `hephkit` (the zero-dependency core) without a cycle.
- Research repos depend on `hephkit-lab`, never the reverse.

### 7.3. Why Ligase belongs here at all

A `data_hash` over a file does not capture the file's *dimensions*. Ligase's
case is that the worst bugs in computational biology do not crash: align to
hg19, call variants against hg38, and you get a well-formed VCF full of
positions quietly shifted. Two runs can therefore replay to an identical
`data_hash` while comparing incompatible reference builds, and `lab.replay`
would report a match.

So `lab.bio` wires Ligase's dimension reading into two places: `lab.data`
manifests record the dimensions Ligase reads (organism, reference build,
coordinate system, identifier namespace, sample order), and `lab.gates` can run
Ligase's type-check as a gate. Bio projects get provenance that knows what the
data is about; non-bio projects never load it.

## 8. The seventeen modules

All `experimental`, all home `python`, each needing a `spec/modules.yaml` row
whose maturity equals its in-source `Maturity: experimental.` label, a docs page
with a runnable example, and vectors or contract tests per §9.

### 8.1. Integrity spine

| Module | What it does | Harvest from |
| --- | --- | --- |
| `lab.config` | Typed pydantic experiment configs with CLI overrides. The resolved config is content-hashed via `hephkit.hashing.content_hash` and stored with the run. Layering: defaults, file, environment, CLI, in that order | SAWA, NeoRx |
| `lab.repro` | Seeds Python and, when present, NumPy and PyTorch; sets deterministic flags; captures git SHA, lockfile hash, platform and accelerator; emits the provenance record of spec §7 and labels it `deterministic` or `provenance-only`. Framework seeding is import-guarded and the record states which frameworks were present | Nocturna (tiering), SAWA |
| `lab.record` | The run record. Written incrementally so a crash costs the current cell, not the run. A record that cannot be written is a failed run, not a quiet one. Registry of experiments where the experiment function never opens a file and never chooses where results go | NeoRx `experiments/record.py`, `registry.py` |
| `lab.replay` | Re-executes a record against its frozen inputs and diffs the result, naming which values moved rather than reporting pass/fail | NeoRx `experiments/replay.py` |
| `lab.gates` | CI-enforceable integrity checks: no hardcoded metrics in figure code, record summaries agree with their rows, every cited run exists and is replayable, committed records are citable | NeoRx `experiments/gates.py` |

### 8.2. Honest inputs

| Module | What it does | Harvest from |
| --- | --- | --- |
| `lab.data` | Content-addressed dataset snapshots on object storage via DVC; Polars and DuckDB loaders; data cards; manifests carrying source, release, extractor version and a digest over the extract actually written; date-to-release resolution so a dated run evaluates the population that date would have evaluated | NeoRx `snapshots/`, SAWA |
| `lab.sources` | External inputs frozen and pinned: content-addressed response cache keyed by request plus upstream algorithm or release version, and an offline replay mode so a run reproduces without the network | NeoRx `experiments/capture.py`, `core/cache.py`; SAWA Sierra client |

### 8.3. Analysis

| Module | What it does | Harvest from |
| --- | --- | --- |
| `lab.causal` | Two halves. Identification over graphs — which edges have earned an arrow before do-calculus runs — **adopted from CausalPhylo**, not rebuilt. Estimation, refutation and reporting through DoWhy, with the refutation suite on by default and causal-learn discovery adapters | CausalPhylo (adopt), SAWA `causal/`, NeoRx |
| `lab.stats` | Multi-seed aggregation, bootstrap confidence intervals, effect sizes, and test selection that refuses an inappropriate test | Written fresh |
| `lab.bench` | Benchmark harness across methods, datasets and seeds, emitting a record per cell so a reported table is a rendering of data | NeoRx `benchmark.py`, SAWA `benchmarks/` |
| `lab.train` | PyTorch helpers on accelerate: mixed precision, checkpointing to object storage as safetensors, early stopping | SAWA `foundation_models/`, NeoRx |
| `lab.embed` | Generic Hugging Face loading and cached embedding extraction keyed by content hash. ESM-specific wrappers stay in Ligase | SAWA, NeoRx |
| `lab.rl` | Gymnasium environment scaffolding, Stable-Baselines3 baselines, evaluation across seeds and episodes | NeoRx `causalbiorl/` |

### 8.4. Orchestration and output

| Module | What it does | Harvest from |
| --- | --- | --- |
| `lab.flows` | Prefect flow templates that run locally or on GPU workers, plus Nextflow for paper-scale analyses | SAWA `pipeline/`, `workflows/` |
| `lab.track` | MLflow wrapper: config, metrics, artifacts and dataset hashes per run, linked to its trace. **No-ops when `MLFLOW_TRACKING_URI` is unset** so tests, CI and offline runs need no server | SAWA `tracking.py` |
| `lab.notebook` | marimo notebooks as reactive, diffable Python, executed end to end in CI | SAWA `notebooks/` |
| `lab.paper` | Figure styling; a methods-and-provenance paragraph generated from `lab.repro` records; `CITATION.cff`; Zenodo DOI on release | SAWA `paper1_tools/`, `_gen_figures.py` |
| `lab.lit` | Validating a claim against the literature it cites | NeoRx `core/literature_validator.py` |

### 8.5. Bio layer

| Module | What it does | Harvest from |
| --- | --- | --- |
| `lab.bio` | Behind the `bio` extra. Reads biological dimensions through `ligase-bio` into `lab.data` manifests, and exposes Ligase's dimension type-check as a `lab.gates` gate | Ligase (adopt) |

## 9. Spec and vectors

### 9.1. Provenance record — revising spec §7

Spec §7 is a draft with five fields and nowhere to record the lockfile hash and
GPU driver the parent design asks `lab.repro` to capture. The naive fix — add
both as fields — breaks the thing being built: if the GPU driver is part of the
record that defines re-execution, the same run on another machine stops
matching and `deterministic` becomes a label nothing can wear.

So fields split by whether they *decide* reproducibility or merely *describe* it:

| Field | Type | In the determinism contract? |
| --- | --- | --- |
| `run_id` | string | identifier |
| `config_hash` | string, content hash per §4.2 | yes |
| `data_hash` | string, content hash per §4.2 | yes |
| `deps_hash` | string, content hash of the lockfile | **yes — new** |
| `code_sha` | string, git commit SHA | yes |
| `class` | string, `deterministic` or `provenance-only` | — |
| `environment` | object | **no — new, descriptive only** |

`deps_hash` is normative because different dependency versions genuinely give
different answers. `environment` is recorded for the reader and never
participates in a replay comparison. Its fields:

| `environment` field | Example |
| --- | --- |
| `platform` | `macOS-15.6-arm64` |
| `python` | `3.12.7` |
| `frameworks` | `{"numpy": "2.1.3", "torch": null}` — absence is recorded, not assumed |
| `accelerator` | `{"model": "NVIDIA RTX 4090", "driver": "550.54.14"}` or `null` |

**Hostname, username and filesystem paths are deliberately excluded — my
call.** `lab.gates` requires records to be committed and citable, which means
they are published alongside a paper. Spec §6.2 already redacts `pii: true`
attributes from logs, and a researcher's machine name or home directory in a
public artefact is the same class of thing. A project that wants them can carry
them in its own config.

#### 9.2.1. Preconditions for the `deterministic` class

Both decided by the user. A run is `provenance-only`, never `deterministic`,
unless **both** hold:

- **The working tree is clean.** A run with uncommitted changes cannot claim the
  label, because `code_sha` would otherwise stop identifying the code that
  produced the result. Exploratory work commits first or accepts
  `provenance-only`.
- **A lockfile exists.** No lockfile means no `deps_hash`, and without it the
  dependency set is unpinned. Hashing the resolved installed distribution set
  instead was rejected: it varies by platform and by CUDA build at the same
  version string, which smuggles the environment back into a contract §9.2
  exists to keep it out of.

This makes the label strict rather than unwearable. This repository, SAWA and
NeoRx all run under git with a `uv.lock`, so the label is earnable exactly where
the discipline already exists, while a marimo session or a conda environment
gets an honest `provenance-only` and loses no traceability — it still carries
`config_hash`, `data_hash`, `code_sha` and `environment`.

Spelling: spec §7's hyphenated `provenance-only` is normative. Nocturna's
`provenance_only` is a divergence to note, not to adopt.

### 9.2. New spec sections

- **§8 Run records.** Record structure, incremental write semantics, and the
  rule that an unwritable record is a failed run.
- **§9 Replay and diff.** What a replay compares, what a difference report
  contains, and what "identical result" means for floating point.
- **§10 Dataset manifests.** Source, release, extractor version, digest scope,
  and date-to-release resolution.

### 9.3. Vectors versus contract tests — the rule-2 problem

Rule 2 forbids generating a vector by running our own implementation. Much of
this kit is I/O-shaped, so a JSON vector file is the wrong instrument for most
of it. The split:

**JSON vectors in `conformance/`,** because the input and output are both pure
data and can be hand-derived or taken from an independent source:

- `lab.provenance.record` — record serialisation and class assignment, derived
  by hand from spec §7 as revised.
- `lab.provenance.diff` — given two records and two result sets, the exact
  difference report. Hand-derived.
- `lab.config.resolve` — config layering and override precedence, hand-derived.
- `lab.stats.effects` and `lab.stats.tests` — effect sizes and test selection,
  with expected values taken from published worked examples, never from ours.

Bootstrap confidence intervals are deliberately **not** vectored — my call. A
bootstrap CI has no value independent of a resampling scheme and an RNG stream,
so taking expected numbers from a seeded `scipy.stats.bootstrap` run would make
scipy's resampling order and bit-level RNG the normative definition and freeze
our public API to it. That is precisely the accidental pinning rule 2 exists to
prevent. They are contract-tested on coverage properties instead.

**Contract tests,** because the behaviour is about effects on the world and no
vector can express it:

- `lab.record` crash-safety: kill a run mid-cell, assert the completed cells
  survive on disk.
- `lab.replay` round trip: a recorded run replays with the network blocked and
  matches; a deliberately perturbed input produces a diff naming that value.
- `lab.gates`: each gate is given a fixture that violates it and must fail —
  the hardcoded-metric fixture is a figure script with a literal in it.
- `lab.track` no-op: with `MLFLOW_TRACKING_URI` unset, every call succeeds and
  nothing is written.
- `lab.data` temporal honesty: a run dated before a release must not see it.
- `lab.stats` bootstrap: nominal 95% intervals cover a known parameter at
  roughly 95% over many synthetic draws, and a degenerate sample is refused
  rather than given a zero-width interval.

### 9.5. Shared conformance plumbing this forces

`conformance/` is a closed system, and three pieces of it must change before a
single `lab` vector can exist:

- `conformance/schema/vector-file.schema.json` holds a **hard-coded `suite`
  enum** and pins `"spec": {"const": "0.3.0"}`. Every new `lab.*` suite is an
  edit to that enum.
- Adding spec §8–§10 bumps `spec/heph-spec.md` to **0.4.0**, which re-stamps
  that `const` and the `spec` field of every existing vector file — files the
  Phase 2 stream is editing. This happens in **one commit, early in wave 1**,
  and is announced to the other stream before it lands.
- `python/hephkit/tests/test_conformance.py` asserts every vector file has a
  runner inside the zero-dependency `hephkit` package. Lab suites must be
  exempted there and run from `python/hephkit-lab/tests` instead, or the spine's
  no-dependency promise dies.
- `tools/check_modules.py` scans only `python/hephkit/src/hephkit` (lines 66 and
  209) and resolves a python label as `<name>.py`. It must learn the second
  tree and dotted names like `lab.config`.
- `tools/check_vectors.py` gets a `MIN_CASES` entry per new suite.

### 9.4. Error codes

New codes in `spec/errors.yaml`, area `LAB`:

| Code | Status | Meaning |
| --- | --- | --- |
| `HEPH-LAB-422` | 422 | Experiment config failed validation |
| `HEPH-LAB-409` | 409 | Replay diverged from its record |
| `HEPH-LAB-424` | 424 | A required record, manifest or frozen input is missing |
| `HEPH-LAB-412` | 412 | An integrity gate failed |

Exact set and wording are settled when each module's spec section is written;
codes are added only as a module needs them, never speculatively.

## 10. Decisions needing an ADR

Numbered from 0021, which waits on Phase 2's 0020 landing.

> **Renumbered (Ruling 15).** ADR numbers follow the order the decisions LAND,
> not the order this section first listed them, because `tools/check_adrs.py`
> enforces contiguity from 0001 and a decision's ADR ships in the same PR as the
> decision. The PEP 420 conversion landed first (wave 1, Task 4), so it takes
> **0021**; the numbers below are the corrected assignment.

- **0021 — `hephkit` becomes a PEP 420 namespace package.** So that a second
  distribution can supply `hephkit.lab`. Breaking for `hephkit.__version__`;
  cheap now because no consumer *in this repository* reads it, and expensive
  later. The ADR states plainly that an `__all__`-exported attribute is being
  removed from a package published on PyPI at 0.2.0, which breaks a conventional
  external adopter, and that this is acceptable only because every module is
  `experimental` under ADR 0015.
- **0022 — Research integrity is the spine of `hephkit.lab`.** Records, replay,
  frozen inputs and gates are the foundation; tracking is a view onto them.
  Supersedes the lab table in the parent design and re-cuts the rollout.
- **0024 — The provenance record splits normative hashes from descriptive
  environment.** Adds `deps_hash`, adds `environment`, and states why the
  environment stays outside the determinism contract.
- **0023 — `hephkit-lab` ships separately and Ligase stays a leaf.** Reverses
  the parent design's dependency direction between Ligase and the lab tier, and
  records why bio capability is an extra.
- **0025 — Adopt CausalPhylo for identification.** Rule 8: the capability exists
  as a clean, documented, single-dependency package extracted from NeoRx for
  exactly this purpose. Both it and `ligase-bio` are published on PyPI, so this
  is a pinned dependency and not vendoring. **Wave 2, not wave 1.**

Numbering note: `tools/check_adrs.py` enforces contiguity from 0001, so wave 1
must land 0021–0024 with no gap. CausalPhylo's ADR therefore takes 0025 and
travels with wave 2; an earlier draft of this document had it at 0024, which
would have left a hole when wave 1 landed 0025 without it.

## 11. The phase gate

The parent design's Phase 3 gate asks that a SAWA causal analysis and a NeoRx RL
run each re-execute from their recorded config and data hash, match, and appear
in MLflow with their provenance class. Two problems: it needs repositories
outside this one, so it cannot run in this repo's CI; and it is now achievable
in full only once `lab.rl` lands, which this document brings into scope but late
in the sequence.

**Decided by the user: the in-repo gate is the whole gate for this stream.**

- **In-repo, enforced every PR.** A fixture experiment in `examples/` records a
  run, replays it with the network blocked, matches, and a perturbed variant
  produces a diff naming the changed value. Every `lab.gates` check runs against
  a violating fixture. The fixture's frozen inputs are synthetic and generated
  by the fixture itself, so nothing third-party is redistributed.
- **Ecosystem gate: explicitly out of scope here.** Making it run is blocked on
  a problem this stream is not solving. `.github/workflows/ecosystem.yml` is
  `workflow_call` only with no caller and every row disabled, and its header
  forbids re-adding `schedule` or `workflow_dispatch` because CodeQL flagged the
  combination of untrusted execution and a privileged context as cache
  poisoning; it states that a timed consumer run "needs them executed somewhere
  other than this repository's default-branch context — that is a design change,
  not a trigger." Enabling SAWA's row would additionally need an adoption PR in
  SAWA's own repository.

So the SAWA and NeoRx halves of the parent design's Phase 3 gate remain a
declaration of intent, unchanged by this stream, and this document does not
claim them. A gate that only passes with another repository checked out is not a
gate; it is an integration test, and it is honest to say it is not running.

## 12. Sequencing

Seventeen modules, each owing a spec section, vectors or contract tests, a docs
page with a runnable example and green CI, is not one session's work. Waves,
each landing green and each a coherent PR series:

0. **Shared-file groundwork,** one commit each and announced to the other
   stream first: the spec bump to 0.4.0 with the vector re-stamp, the schema
   `suite` enum, and the `check_modules.py` / `test_conformance.py` changes of
   §9.5. These are the collisions, so they land before any module code.
1. **Spine.** `lab.config`, `lab.repro`, `lab.record`, `lab.replay`,
   `lab.gates`; spec §7 revision plus §8 and §9; ADRs 0021–0024, which includes the
   PEP 420 conversion; the in-repo gate; the `mlflow` Compose fragment and
   `lab.track`, because a record nobody can see is hard to trust.
2. **Proof.** A causal analysis through the spine end to end, which is what
   validates the contract before twelve modules depend on it. Needs `lab.data`,
   `lab.sources`, `lab.causal` (CausalPhylo adopted, ADR 0025) and `lab.stats`;
   spec §10. Done means the in-repo gate of §11 passes on a fixture analysis
   shaped like SAWA's — same DAG-to-estimate-to-refute path, synthetic data —
   **not** that SAWA itself has been re-run, which §11 puts out of scope.
3. **Scale.** `lab.bench`, `lab.flows`, `lab.notebook`.
4. **Models.** `lab.train`, `lab.embed`, `lab.rl`; the `heph-ml` image.
5. **Output.** `lab.paper`, `lab.lit`, `lab.bio`.

**Wave 1 is gated on ADR 0020 landing.** `tools/check_adrs.py` enforces
contiguity from 0001, `docs/adr/` ends at 0019, and 0020 belongs to Phase 2. A
decision's ADR belongs in the same PR as the decision (rule 1), so wave 1
cannot land its code and backfill its ADRs later. If 0020 has not landed when
wave 1 is otherwise ready, the choice is to wait or — only if Phase 2 has
dropped it — renumber down from 0020. That is a coordination call, not a
technical one.

This session: this document, the implementation plan covering all seventeen, and
wave 1 built against it as far as the ADR gate allows. Later waves follow the
plan.

## 13. Coordination with the parallel stream

Phase 2 (idempotency store) runs concurrently and shares the registry files that
have already turned `main` red twice. Therefore:

- ADR numbers 0021 and up are this stream's; 0021 waits for 0020 to land.
- `spec/errors.yaml`, `spec/modules.yaml`, `conventions/attributes.yaml` and
  everything generated from them change in as few commits as possible, always
  by regeneration, and every PR body names which of them it touched.
- Every new module lands with its `spec/modules.yaml` row and its in-source
  `Maturity: experimental.` label in the same commit, since
  `tools/check_modules.py` holds the two equal.
- Nothing in this stream touches Phase 2's idempotency *behaviour*. But three
  shared surfaces are unavoidable and were missed in the first draft of this
  document: the spec version bump re-stamps every vector file; the vector-file
  schema's `suite` enum must grow; and `python/hephkit/` itself is edited by the
  PEP 420 conversion and by `test_conformance.py`'s lab exemption. Each lands as
  its own commit in wave 0, announced before it lands.

## 14. Left to the builder

- Internal module structure beyond the file layout in §7.1.
- The record's on-disk format (JSON lines versus Parquet), given that §8.1
  requires incremental writes and §9.3 requires crash-safety.
- Float comparison tolerance in `lab.replay`, which spec §9 must state but
  whose value is an implementation judgement informed by the fixture.
- Which Prefect and Nextflow templates ship in wave 3.
- Whether `lab.sources` freezes via vcrpy as NeoRx does, or a narrower
  transport-level mechanism; NeoRx chose vcrpy because its sources construct a
  Session per call, which may not be true of ours.
- Docs page structure, following the existing generated-page conventions.
- How thin each wave 3–4 module has to be. **CI is CPU-only; the user ruled out
  a GPU runner.** So `lab.train`, `lab.rl` and `lab.embed` hold the repo's 90%
  line-coverage gate on CPU with small fixtures, and the principle to apply is:
  these are adapters over adopted libraries (rule 8), so if one cannot reach 90%
  without an accelerator, that is evidence it contains logic which belongs in
  the adopted library rather than a reason to lower the gate. No `ml-ci`
  workflow and no self-hosted runner are in scope.

## 15. Decisions taken after the builder check

A design review raised nine questions; five were settled in this document as my
calls (§7.1.1 PEP 420, §7.1.2 extras, §9.2 hostname exclusion, §9.3 bootstrap
contract tests, §9.5 shared plumbing). Four needed the user and were answered:

| Question | Answer | Where it landed |
| --- | --- | --- |
| May a dirty working tree claim `deterministic`? | No — commit first | §9.2.1 |
| Is making the ecosystem gate runnable in scope? | No — in-repo gate only | §11 |
| What does `deps_hash` hash with no lockfile? | Nothing — `provenance-only` | §9.2.1 |
| Is a GPU runner available to CI? | No — CPU-only | §14 |

The through-line is that a label is worth having only if it is hard to earn, and
that this stream does not claim a gate it cannot run.

Three calls are mine and remain open to rejection while reading: spine-first
sequencing (§6), `hephkit-lab` as a separate distribution with the PEP 420
conversion of `hephkit` (§7.1), and bootstrap CIs contract-tested rather than
vectored (§9.3).
