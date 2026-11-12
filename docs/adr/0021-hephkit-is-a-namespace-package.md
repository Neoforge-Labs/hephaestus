# 0021. hephkit is a namespace package

## Status

Accepted. Date: 2026-11-12. Design: `docs/superpowers/specs/2026-11-12-hephkit-lab-research-core-design.md`.

## Context

A second distribution, `hephkit-lab`, is about to supply `hephkit.lab`. Two distributions cannot both own a regular package directory. `python/hephkit/src/hephkit/__init__.py` made `hephkit` a regular package, so installing both into one environment would have put two distributions' files in one directory that each one's `RECORD` claims in full. The consequences are not theoretical: uninstalling either removes the other's `__init__.py`, typing resolution depends on which wheel was written last, and — decisively — `uv run maturin develop --uv`, the dev loop CLAUDE.md mandates, breaks. That loop installs by writing a `.pth` file pointing at one source tree, and a regular package's `__path__` is the first `hephkit/` directory found on `sys.path`, so whichever tree wins makes the other's modules unimportable.

Three mechanisms can put two distributions under one import name.

1. **A PEP 420 implicit namespace package.** Neither distribution ships `hephkit/__init__.py`; the import system builds `hephkit.__path__` from every `hephkit/` directory on `sys.path`. (The pre-PEP-420 `pkgutil`- and `pkg_resources`-style declarations do the same job through a shim `__init__.py`; they are superseded, require every portion to carry the identical shim, and are not considered further.)
2. **One distribution with extras.** Keep `hephkit` a regular package, ship `hephkit/lab/` inside it, and gate the research dependencies behind a `hephkit[lab]` extra.
3. **A separate top-level name.** Ship the lab code as its own import root, `heph_lab`, sharing no namespace with `hephkit`.

Mechanism 2 was rejected on maturity and cadence. It would put research and ML code in the same distribution as the money path, where CLAUDE.md rule 7 forbids anything below `stable`; an extra gates the *dependencies*, not the *files*, so the wheel would ship `hephkit/lab/` to every consumer whether or not they can import it. It also welds the two release cadences together: a lab change would force a `hephkit` release, and a `hephkit` release could not reach `stable` while carrying `experimental` lab code.

Mechanism 3 was rejected on naming. It is the cheapest option and it works, but `from heph_lab import ...` gives up the single-kit reading that `hephkit.lab` has, and it forecloses nothing less than the same question again when `hephkit.ai` arrives.

The break is cheap now and expensive later. `.github/workflows/ecosystem.yml` says in its own header that no product has adopted `hephkit` and that every consumer row is `enabled: false`; two of us independently grepped this repository and found nothing reading `hephkit.__version__`. That is a claim about *this repository*, not about PyPI, and the two are not the same claim.

## Decision

`hephkit` is a PEP 420 implicit namespace package. `python/hephkit/src/hephkit/__init__.py` is deleted.

The version is deliberately not set by hand here. `release-please-config.json` carries a `linked-versions` plugin whose `hephaestus` group binds `hephaestus`, `hephkit-core`, `hephkit-py`, `hephkit` and `go` to one shared version, and release-please computes the bump for all five from the conventional-commit history. The `!` in this change's `refactor(hephkit)!:` subject is what marks the breaking change, so the number it derives is the right one; editing one member's version by hand would break the invariant `tools/tests/test_release_config.py` exists to protect.

`hephkit/errors/` and `hephkit/idempotency/` stay regular subpackages with their `__init__.py` files. Only the top-level `hephkit/` becomes a namespace portion; nothing below it does.

**`hephkit.__version__` is removed from a published package.** `hephkit` is on PyPI at `0.2.0` and `__version__` was listed in `__all__`, so an external adopter reading `hephkit.__version__` was doing something conventional and supported, and this release breaks them. We are doing it anyway, and the reason is maturity rather than consumer count: every module is `experimental` under [ADR 0015](0015-maturity-levels.md), which says in as many words that the API may change and that the package is not for production. This is the kind of change `experimental` exists to permit, and the moment to take it is before any consumer exists rather than after. A namespace package can hold no code, so there is no shim and no deprecation period — the attribute is gone in the next release, not warned about.

The replacement is `importlib.metadata.version("hephkit")`, which is stdlib, needs no import of `hephkit` itself, and reads the one authoritative copy of the version in `python/hephkit/pyproject.toml` rather than a second copy in source.

**The PEP 561 typing marker stays at `hephkit/py.typed`, and every later portion carries its own marker inside the subpackage it alone owns.** `hephkit`'s modules (`money.py`, `hashing.py`, `signatures.py`, …) sit directly in the namespace directory, so there is no deeper directory to mark; `hephkit/py.typed` is the only possible placement for them, and the `hephkit` distribution owns that path alone. `hephkit-lab` must therefore put its marker at `hephkit/lab/py.typed`, not at `hephkit/py.typed`: the second would be a file owned by two distributions, which is the collision this ADR exists to avoid.

That rule is not a formality. mypy resolves `py.typed` per `sys.path` entry, not per logical namespace, so in the editable layout the dev loop produces — one `.pth` per source tree — `hephkit`'s marker does **not** make a `hephkit.lab` from another tree typed. Verified against mypy 1.x: with `hephkit/py.typed` present and no marker under `lab/`, `hephkit.lab` is reported `import-untyped` and its types degrade to `Any`, while `hephkit.money` resolves exactly. Adding `hephkit/lab/py.typed` fixes it, in both the editable layout and the merged single-directory layout a plain `pip install` produces.

`hephkit.ai`, when it exists, is a third portion under the same rules: no `__init__.py` at `hephkit/`, its own `hephkit/ai/py.typed`, its own version in its own `pyproject.toml`.

## Consequences

`import hephkit` now yields a module with `__file__` of `None` and a `_NamespacePath` for `__path__`. Nothing can be imported from `hephkit` itself — no re-exports, no `__all__`, no package-level constants — so every public name must be reached through a submodule, as `hephkit.money` and `hephkit.errors` already were. `python/hephkit/tests/test_namespace.py` pins all three properties: the absent `__file__`, the metadata version, and that the submodules still import.

Deleting a file changes the coverage denominator, and the gate is `--cov-fail-under=90` and is not touched. Measured: the deleted file contributed exactly two statements coverage.py counted, the `__all__` and the `__version__` assignment, and both ran on import. The denominator goes 1008 to 1006 with misses at zero either side, so coverage stays at 100.00% and does not move.

`uv run mypy --strict src` needed configuration to keep working. Checking a *path* rather than a module makes mypy infer each file's module name from the directory tree, and with no `__init__.py` at `src/hephkit/` it treats that directory as a package base too, reaching `src/hephkit/errors/_codes.py` as both `errors._codes` and `hephkit.errors._codes` and refusing to go further. `[tool.mypy]` now sets `mypy_path = "$MYPY_CONFIG_FILE_DIR/src"` and `explicit_package_bases = true`, which names one base and resolves every file to `hephkit.*`. This is configuration, not a weakening: `--strict` is untouched and the command CLAUDE.md mandates is unchanged.

The deleted docstring's content is not lost. It described what the Python package contains and where to look, which belongs on the docs site rather than in a file no longer able to exist; it now lives in `docs/site/content/docs/index.mdx`.

Nothing in the build changes. `[tool.maturin]`'s `python-source = "src"` and `module-name = "hephkit._core"` still place the compiled extension inside the namespace directory, and maturin does not synthesise an `__init__.py`: the wheel ships `hephkit/_core.abi3.so`, `hephkit/py.typed`, `hephkit/idempotency/schema.sql` and no `hephkit/__init__.py`.

The cost is a sharper edge for contributors. An `__init__.py` accidentally added back to `python/hephkit/src/hephkit/` would silently convert `hephkit` to a regular package again and shadow every other portion, and nothing but `test_namespace.py` would say so. The failure is loud in tests and silent at runtime in a consumer's environment, which is the wrong way round; the test is the only guard, and it is why it asserts the absence of `__file__` rather than merely that imports work.
