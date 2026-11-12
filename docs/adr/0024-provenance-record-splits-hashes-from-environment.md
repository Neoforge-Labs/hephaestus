# 0024. The provenance record splits normative hashes from a descriptive environment

## Status

Accepted. Date: 2026-11-12. Design: `docs/superpowers/specs/2026-11-12-hephkit-lab-research-core-design.md` §9.1, §9.2.1.

## Context

`spec/heph-spec.md` §7 has carried a provenance record since `0.1.0`, marked **draft**, with five fields — `run_id`, `config_hash`, `data_hash`, `code_sha` and `class` — and a note that the fields may change before promotion. [ADR 0022](0022-research-integrity-is-the-spine.md) made that record the spine of `hephkit.lab` rather than a convenience, so the draft has to become something an implementation can be held to before `lab.repro` is written against it.

Two facts the record does not yet hold have to go in. The parent design, `docs/superpowers/specs/2026-11-04-hephaestus-design.md`, asks `lab.repro` to capture the dependency lockfile hash and the GPU driver. Adding both as plain fields is the naive fix and it breaks the thing being built. The record's five existing fields are all *normative*: they are what a replay compares, so a difference in any of them means the replay is not the same run. Put the GPU driver in that set and the same configuration, data and code re-executed on a second machine stops matching. `deterministic` would then be a label nothing could ever wear, because no two machines agree on their driver version, and a class that is unreachable in practice is decoration.

The lockfile hash does not have that problem. Two different dependency sets genuinely give different answers, so a replay against a different lockfile *is* a different run and should be reported as one.

So the two additions are not the same kind of thing, and the record needs a distinction it does not currently have.

A second question sits underneath. If `deterministic` is reachable, what makes a run eligible for it? The draft said nothing, which left an implementation free to stamp `deterministic` on a run from a dirty working tree with no lockfile — a record that claims re-execution while naming neither the code nor the dependencies that produced the result.

## Decision

**Fields split by whether they decide reproducibility or merely describe it.** Spec §7.1 names a **determinism contract**: `config_hash`, `data_hash`, `deps_hash` and `code_sha`. `run_id` identifies the run and `class` classifies it, so neither is in the contract. `environment` is descriptive, and §7.2 says normatively that a replay MUST NOT compare it and that two records differing only in `environment` are not a divergence. That sentence, not a column in a table, is what keeps the label wearable: the distinction has to be a rule an implementer in another language can satisfy, not an inference a reader draws from a layout.

**`deps_hash` is normative and is a hash of the lockfile.** It is a content hash (spec §4.2) over the lockfile's bytes as committed, not over a parsed form, because a lockfile is not required to be JSON and §4.1's canonicalisation therefore does not apply to it. It is `null` exactly when the run had no lockfile.

**`environment` carries `platform`, `python`, `frameworks` and `accelerator`, and never an identifier of a person or a machine. My call, taken by the user.** Hostname, username and filesystem paths are excluded under any member name. [ADR 0022](0022-research-integrity-is-the-spine.md) makes `lab.gates` require records to be committed and citable, which means they are published alongside a paper; spec §6.2 already requires `pii: true` attributes to be redacted from log output, and a researcher's machine name or home directory in a permanent public artefact is the same class of thing as one in a log line, only harder to withdraw. A project that wants them carries them in its own configuration, outside the record. An absent framework is recorded as `null` rather than omitted, so the record distinguishes "looked for and not there" from "never asked".

**A run is `provenance-only` unless the working tree is clean and a lockfile exists. Both are the user's decisions, not derivations.** A dirty tree means `code_sha` no longer identifies the code that ran, which is the one job `code_sha` has in the record. No lockfile means no `deps_hash` and so an unpinned dependency set. Failing either condition costs the label and nothing else: the run is still recorded in full, with `config_hash`, `data_hash`, `code_sha` and `environment`, so a marimo session or a conda environment gets an honest `provenance-only` and loses no traceability.

"Clean" is resolved into a condition an implementation can check: nothing tracked differs from the commit named by `code_sha`, and no untracked file is present other than those the repository's ignore rules exclude — a tree for which `git status --porcelain` prints nothing. The stricter reading is deliberate. An untracked script that the run imported is code that ran and is not in `code_sha`, which is the exact failure the precondition exists to prevent, so untracked files dirty the tree too.

**Hashing the resolved installed distribution set instead of the lockfile was considered and rejected.** It varies by platform and by CUDA build at the same version string, which smuggles the environment back into the contract this ADR exists to keep it out of.

**`provenance-only` is hyphenated, and the hyphen is normative.** Nocturna, one of the harvest sources, spells it `provenance_only`; that is a divergence, recorded here so nobody adopts it by copying.

**The spec moves to `0.5.0`.** §7 loses its draft status and gains MUST sentences where it previously had none, so by [ADR 0019](0019-the-public-domain-is-hephkit-dev.md)'s reasoning — a minor bump because a MUST changed — that is a minor bump. `0.4.0` is taken by the idempotency change in §2, so this is `0.5.0`, and the `spec` field of every conformance vector and the `const` in `conformance/schema/vector-file.schema.json` move with it. The rest of this wave's spec work lands in the same `0.5.0`.

**Four codes enter `spec/errors.yaml` under area `LAB`:** `HEPH-LAB-422` (experiment config failed validation), `HEPH-LAB-409` (replay diverged from its record), `HEPH-LAB-424` (a required record, manifest or frozen input is missing) and `HEPH-LAB-412` (an integrity gate failed). They are the set the design's §9.4 settles; no code is added speculatively ahead of the module that raises it.

## Consequences

`deterministic` is now strict rather than unwearable, and it is earnable exactly where the discipline already exists. This repository, SAWA and NeoRx all run under git with a `uv.lock`, so runs there can claim it; everything else gets `provenance-only`, which is an honest answer and not a degraded one. The failure mode this protects against is the opposite of the obvious one: the risk was never that too few runs would qualify, it was that a label attached to every run would stop meaning anything.

The split has a cost in what the record can tell you. A replay that matches on all four contract members but produced a different number has to be explained by something outside the contract, and `environment` is where the reader looks — descriptively, by hand. `lab.replay` cannot do that reasoning, by construction, because the moment it compares `environment` the contract has grown the field this ADR removed from it. `HEPH-LAB-409`'s developer guidance therefore sends the reader to the difference report rather than to a re-run.

`environment` is an open object whose named members are individually optional but whose names and types are reserved, so a project may add members and an implementation on another runtime may omit `python`, while nobody may record a platform under a second name. That is deliberate — implementations differ in what they can see — and it is also the place this decision can rot: the exclusion of hostname, username and paths is a prose MUST in §7.5 with no check behind it, and nothing in `tools/` can see a hostname smuggled in under another member name. The guard is review of the module that builds the record, and a vector for `lab.provenance.record` once the design's §9.3 suite exists.

Two things are deliberately left open. §7 does not say what a run outside a version-controlled tree records for `code_sha`, because the record requires the field and this ADR will not invent a null form for it; spec §8, which owns run records, settles it. And §7.2 constrains only that a replay never compares `environment` — what a replay does compare, and what "identical result" means for floating point, belong to spec §9 and are not decided here.

The `0.5.0` bump re-stamps thirteen vector files and the schema `const` in the same commit as the §7 revision, which is the whole point of doing it here: leaving the spec revised while it still declared `0.4.0` would make one version number name two different specifications mid-branch. `tools/gen_idempotency_vectors.py` and `tools/gen_signature_vectors.py` each hold the version as a constant and were moved with it, or the next run of either would quietly revert the stamp.
