"""The Hephaestus research core: integrity first, tracking as a view onto it.

`hephkit.lab` applies the kit's refusal to produce a plausible wrong number to
research work. Its spine makes four claims structurally true: a number cannot
exist without a record, a record replays and a replay that differs says which
values moved, inputs are frozen and content-addressed and temporally honest,
and CI refuses a result that breaks any of the above (ADR 0022).

The spine installs with no scientific stack. Tracking, dataframes, causal
identification, statistics, training, flows, notebooks and bio dimensions are
extras, so a project adopts the integrity guarantees without adopting our tool
choices (ADR 0023).

This is a portion of the PEP 420 `hephkit` namespace supplied by the separate
`hephkit-lab` distribution (ADR 0021). Nothing is re-exported here: every
public name is reached through a submodule.

How every module in this package raises
---------------------------------------

One shape, so a reader who has met one module's errors has met them all. A
module that refuses anything declares:

* **One base class**, named for the module (`ConfigError`, `GateError`,
  `ManifestError`, `TemporalError`, `SourceError`, `StatsError`), carrying the
  registry code for that module's ordinary refusal -- "this input exists and
  says the wrong thing" -- as a class attribute `code`. It subclasses a builtin
  (`ValueError`, `RuntimeError`, `LookupError`) chosen for what the module does,
  and *every* error the module raises subclasses it. Never two unrelated classes
  in one module: `except <ModuleBase>` must be the one way to catch "this input
  is unusable", and two different builtin bases make `except ValueError` or
  `except LookupError` miss half of them.
* **A subclass per specific refusal**, named for what was refused
  (`AmbiguousReleaseError`, `CorruptSourceError`), each carrying its own `code`.
  The base may be raised bare for the module's general case.
* **The absence case as a `Missing*` subclass carrying `HEPH-LAB-424`**
  (`MissingConfigError`, `MissingSubjectError`, `MissingManifestError`,
  `MissingSourceError`; `NoEligibleReleaseError` where "missing" would not read
  as English). A required input that is not there at all is never the same error
  as one that is there and wrong, and the base must not be the class that
  carries 424 while a subclass carries some other code: `.code` is what tells
  the two apart, and inverting them makes the general `except` the narrow one.

Codes are never spelled as literals; they are imported from `hephkit.errors`,
which `tools/gen_errors.py` generates from `spec/errors.yaml`, and
`tests/test_error_codes.py` fails any module that writes one by hand.

Maturity: experimental.
"""

from __future__ import annotations

__all__: list[str] = []
