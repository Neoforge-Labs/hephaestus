# 0022. Research integrity is the spine of hephkit.lab

## Status

Accepted. Date: 2026-11-12. Design: `docs/superpowers/specs/2026-11-12-hephkit-lab-research-core-design.md`.

## Context

The parent design, `docs/superpowers/specs/2026-11-04-hephaestus-design.md`, specified `hephkit.lab` as a table of convenience wrappers (lines 318–335): `lab.track` over MLflow, `lab.data` over DVC, `lab.causal` over DoWhy, and so on. Each row is useful and each row is the kind of thing a researcher reimplements per project and then quietly stops using, because a wrapper over a tracking server is only as load-bearing as the researcher's discipline in calling it.

An inventory of the work this kit exists to serve says the harder-won thing has already been built twice, independently. The evidence is set out in §1 of the design document and is not restated here; in summary:

* NeoRx has an `experiments/` subsystem — `record.py`, `replay.py`, `capture.py`, `gates.py`, `registry.py` — whose design notes name the incidents that produced it: a crash that lost 881 seconds of an RL benchmark and led to its numbers being retyped by hand, and a manuscript audit that found F1 values held as literals in a figure script, so "Figure 3 was a transcription of a table rather than a rendering of data". Its `registry.py` is what makes "a number cannot exist without a record" structural rather than a habit: an experiment never opens a file and never decides where results go. Its `snapshots/` subsystem adds temporal honesty — a dated run must evaluate the population that date would have evaluated, or there is hindsight in the sampling frame.
* SAWA reached for the same instinct separately, with no shared code: a Stanford HIVdb client behind a sha256 cache with algorithm-version pinning and an offline replay mode, and a per-run `partition_report.parquet` carrying a per-subtype decision and its reason, for reviewer-grade reproducibility.

Two projects converging on records, replay, frozen inputs and gates — while neither bothered to keep using a tracking wrapper — is the signal. Tracking is where a result is *looked at*. It is not where the result is *made true*.

## Decision

**The spine of `hephkit.lab` is research integrity, and tracking is a view onto it rather than its foundation.** The kit makes four claims structurally true:

1. A number cannot exist without a record.
2. A record replays, and a replay that differs says which values moved.
3. Inputs are frozen, content-addressed and temporally honest.
4. CI refuses a result, a figure or a manuscript that breaks any of the above.

Concretely, `lab.config`, `lab.repro`, `lab.record`, `lab.replay` and `lab.gates` are the foundation of the package, they carry no scientific dependency, and every other module is defined in terms of them. `lab.track` writes an existing record to MLflow; it is not the system of record, and a run whose tracking server is unreachable still produces a complete, replayable record on disk. `lab.data` freezes an input and records its digest; the digest is taken over the extract actually written, not over an upstream file whose contents are asserted. `lab.paper` generates its methods and provenance text from records rather than from prose.

**This supersedes the `hephkit.lab` table in the parent design** (lines 318–335) and re-cuts its rollout. The table's tier 1 led with `lab.track` and `lab.data` as foundations and had no `record`, `replay` or `gates` row at all; the new cut puts those three first and brings tracking in behind them. The replacement scope is the seventeen modules of the new design's §8, and the rollout is its §12.

[ADR 0007](0007-mlflow-experiment-tracking.md) is not reversed. MLflow remains the tracking backend we adopt rather than build, under rule 8 and [ADR 0014](0014-adopt-or-build.md). What changes is its position: it is a sink for records, reachable through an extra, and nothing in the integrity spine depends on it.

## Consequences

The package has a hard inner boundary. Five modules may be imported by everything and may import nothing heavy, which is what makes [ADR 0023](0023-hephkit-lab-ships-separately.md)'s claim — that the spine installs with no scientific stack — enforceable rather than aspirational. A change that gives `lab.record` a dependency on `lab.track` inverts this ADR and must be rejected as such.

The gate moves from "results appear in MLflow" to "a recorded run replays with the network blocked, and a perturbed variant is refused". That gate runs in this repository, on a fixture experiment in `examples/`, every pull request. The parent design's Phase 3 gate asked for a SAWA causal analysis and a NeoRx RL run to re-execute from their records, which needs repositories outside this one and so could never have run in this repo's CI; the in-repo gate replaces it here and the cross-repo check lives in ecosystem CI once a consumer adopts the kit.

Three modules the parent table does not contain — `record`, `replay`, `gates` — are now the modules the package is judged on, and each needs its `spec/modules.yaml` row, its spec section, its vectors or contract tests and its docs page like any other.

Replay has a cost this ADR accepts: a record is only as replayable as its inputs are frozen, so `lab.data` and the capture layer are on the critical path of the whole value proposition, not optional conveniences bolted on later. A project that declines to freeze its inputs gets provenance-only artifacts and is told so by label, rather than getting a `deterministic` label it has not earned.

Finally, the four claims are claims about *our* code, not about a researcher's. The kit can refuse to let a number exist without a record inside its own API; it cannot stop someone computing a number in a notebook and typing it into a manuscript. `lab.gates` closing that gap — a manuscript citing a run that does not exist, or one nobody can reproduce — is the only part of the spine that reaches outside the library, and it is the part most likely to need project-specific extension.
