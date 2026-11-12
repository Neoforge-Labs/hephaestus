# 0023. hephkit-lab ships separately and Ligase stays a leaf

## Status

Accepted. Date: 2026-11-12. Design: `docs/superpowers/specs/2026-11-12-hephkit-lab-research-core-design.md`.

## Context

[ADR 0021](0021-hephkit-is-a-namespace-package.md) made `hephkit` a PEP 420 namespace package so that a second distribution can supply `hephkit.lab`. It settled the *mechanism*. It did not settle whether a second distribution is the right thing to build, or what the lab tier may depend on.

`hephkit` today has **zero** runtime dependencies, and that is a large part of what it is for: a product service installing `hephkit[settings]` gets pydantic-settings and nothing else. The lab surface, taken whole, needs torch, dowhy, mlflow, dvc, prefect, polars, duckdb, scipy, transformers and marimo. Shipping those as extras on `hephkit` would make the correctness kit's dependency metadata mostly machine learning, and would weld two release cadences together: a lab change would force a `hephkit` release, and a `hephkit` release could not reach `stable` while carrying `experimental` lab code. [ADR 0021](0021-hephkit-is-a-namespace-package.md) rejected that option on those grounds for the packaging question; the same reasoning decides this one.

There is a second, sharper question underneath. The parent design, `docs/superpowers/specs/2026-11-04-hephaestus-design.md`, says at line 336: "Ligase depends on `hephkit-core` and `hephkit.lab`, never the reverse." But the new design's §7.3 makes the case that the lab tier *needs* what Ligase knows. A `data_hash` over a file does not capture the file's dimensions: align to hg19, call variants against hg38, and you get a well-formed VCF full of quietly shifted positions. Two runs can therefore replay to an identical `data_hash` while comparing incompatible reference builds, and `lab.replay` would report a match — a false negative in exactly the check [ADR 0022](0022-research-integrity-is-the-spine.md) makes the package's reason to exist. Wiring Ligase's dimension reading into `lab.data` manifests and `lab.gates` fixes it, and points the dependency the other way round from the parent design.

## Decision

**`hephkit-lab` is its own distribution**, at `python/hephkit-lab`, supplying the `hephkit.lab` portion of the namespace. It is built with plain `hatchling` — there is no Rust in it — and its wheel ships `hephkit/lab/` and nothing else. Its required dependencies are `hephkit` and pydantic, and nothing more. Its PEP 561 marker is `hephkit/lab/py.typed`, inside the subpackage it alone owns; it must never ship `hephkit/py.typed`, which in a merged `pip install` layout would be one file owned by two distributions.

**Everything heavy is an extra.** The §4 anti-goal about non-bio ingots paying for a bio engine applies with equal force to non-ML projects paying for an ML stack, so the partition is:

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

The spine — config, repro, record, replay, gates — therefore installs with no scientific stack at all. That is what lets CI stay fast and what lets a project adopt the integrity guarantees of [ADR 0022](0022-research-integrity-is-the-spine.md) without adopting our tool choices. `python/hephkit-lab/tests/test_package.py` asserts it against the manifest, so an added runtime dependency fails the build rather than being noticed later.

**`hephkit-lab` core never imports a domain library.** `lab.bio` is the only module permitted to import `ligase-bio`, and it lives behind the `bio` extra. Bio capability is reached by installing `hephkit-lab[bio]`, not by the lab tier depending on a genomics engine.

**Ligase stays a leaf. This reverses the parent design's line 336.** Ligase must not take a dependency on `hephkit-lab`, or the two cycle: `lab.bio` imports `ligase-bio`, so a `ligase-bio` that imports `hephkit-lab` closes the loop. Ligase may depend on `hephkit`, the zero-dependency core, without a cycle, and that is the dependency the parent design's Week 13 step ("point Ligase at `hephkit-core` hashing") actually needs. The provenance capability the parent design wanted Ligase to take from `lab.repro` now flows the other way: `lab.bio` reads Ligase's dimensions, and research repos depend on `hephkit-lab`, never the reverse.

**`causalphylo` and `ligase-bio` are adopted as pinned dependencies, not vendored.** Both are published on PyPI. Under rule 8 and [ADR 0014](0014-adopt-or-build.md) that makes each a version-bounded dependency in the extra that needs it, with no code copied into this repository. `causalphylo` was extracted from NeoRx as a clean, documented, single-dependency package for exactly this purpose; its own ADR travels with the wave that adopts it.

## Consequences

Two distributions to version, release and audit instead of one, and a reader must know which one a module came from. `hephkit-lab` starts at `0.1.0` and versions independently of `hephkit`, which is the point: the lab stack can move fast and stay `experimental` while the money path walks towards `stable`, and rule 7 is not strained by shipping research code in the distribution a production money path installs.

Independent versioning is not free, and the first cost is already visible. `hephkit` is one of five packages `release-please-config.json` binds with a `linked-versions` plugin, so the version in which it first ships as a namespace package is release-please's to assign and does not exist yet; the published `0.2.0` is the regular-package build and cannot host `hephkit.lab` at all. `hephkit-lab`'s `hephkit>=0.2` floor is therefore a local-development floor only, kept loose so `[tool.uv.sources]` resolves the portion in this repository, and raising it to the first released namespace-capable version is a hard precondition on publishing `hephkit-lab`. `hephkit-lab` is deliberately absent from `release-please-config.json`: `tools/tests/test_release_config.py` asserts that the five lockstep packages share one version, which `hephkit-lab` does not and must not.

The development loop is two editable installs in one environment, which is the layout §7.1.3's typing finding was established against and the reason the marker sits where it does. `python/hephkit-lab/tests/test_package.py::test_core_and_lab_coexist_in_one_namespace` is the first test in this repository where two portions of `hephkit` exist at once, so it is the first place [ADR 0021](0021-hephkit-is-a-namespace-package.md)'s actual property can be checked; it asserts that `hephkit.__path__` holds both trees, because an import test passes even when one portion shadows the other.

Coverage, mypy and pytest run per distribution. `hephkit-lab` measures `--cov=hephkit.lab` rather than `--cov=hephkit`: the sibling portion is installed editable into the same environment, and measuring it here would report another distribution's coverage against this one's gate. Both gates are `--cov-fail-under=90`.

An extras partition is a promise that can rot quietly. A module that imports scipy at top level while sitting outside the `stats` extra breaks a spine-only install, and nothing but a test that imports the spine in a clean interpreter will say so. `test_lab_imports_with_no_scientific_stack` does exactly that, in a subprocess, and must grow as the extras do.

The `[all]` extra is a convenience with a cost: it resolves torch, transformers, mlflow, dvc, prefect and marimo together, so a conflict between any two of them surfaces as a failure to lock. The committed lockfile covers every extra for this reason — the conflict is found here rather than in a consumer's environment.

Finally, the reversal has to be respected in a repository we do not control. Nothing in this repository can stop someone adding `hephkit-lab` to Ligase's dependencies; the cycle would appear as a resolution failure or, worse, as an import-time cycle in `lab.bio`. The guard is this ADR and ecosystem CI once Ligase is an enabled consumer row, not a check in `tools/`.
