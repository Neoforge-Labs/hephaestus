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

Maturity: experimental.
"""

from __future__ import annotations

__all__: list[str] = []
