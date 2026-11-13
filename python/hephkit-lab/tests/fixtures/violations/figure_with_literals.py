"""A figure script of the kind the manuscript audit `lab.gates` was harvested from found.

Every number here was transcribed from a results table rather than read from a
run record, which is the defect the figures gate exists to catch: "Figure 3 was
a transcription of a table rather than a rendering of data".

This file is read as text and parsed; it is never imported, and nothing in it
runs. Each line the gate must flag carries a trailing marker comment, and
`test_gates.py` reads those markers rather than hard-coding line numbers, so the
fixture states its own expectations and editing it cannot quietly weaken the
test.

This docstring says `f1 = 0.474` in prose on purpose: a docstring is
documentation rather than an executable literal, and the scan must not flag it.
A comment below says the same thing for the same reason.
"""

from __future__ import annotations

from typing import Any

# A transcribed metric, which is where the audit started. Written here as
# f1 = 0.474 in a comment, which the AST never sees and the gate must not flag.
f1 = 0.474  # VIOLATION

# An annotated assignment, which is a different AST node than a bare one.
final_accuracy: float = 0.912  # VIOLATION


class Panel:
    """Somewhere to hang an attribute assignment."""

    auroc: float


panel = Panel()
panel.auroc = 0.8831  # VIOLATION

# A series, transcribed row by row out of a results table.
f1_scores = [
    0.474,  # VIOLATION
    0.521,  # VIOLATION
    0.498,  # VIOLATION
]

# Two at once, which only a tuple target reaches.
macro_f1, macro_recall = 0.474, 0.655  # VIOLATION

# Through a subscript, the shape a results dict gets filled in.
table: dict[str, Any] = {}
table["rmse"] = 1.2048  # VIOLATION

# As a dict key, the shape a figure script hands straight to a plotting call.
bars = {
    "precision": 0.71,  # VIOLATION
    "model": "resnet-50",
    "epochs": 90,
}

# A negative one, which is a unary operation rather than a constant.
delta_r2 = -0.0312  # VIOLATION

# Two literals nested under a name that is itself a metric.
dice = {"liver": 0.9412, "kidney": 0.8893}  # VIOLATION

# A p-value, whose name matches only once the separators are dropped.
p_value = 0.031  # VIOLATION

# One literal under two names: reported once, because the finding is the literal.
best_f1 = best_f1_macro = 0.5210  # VIOLATION

# Positive-class F1 and the loss at a training step. These are here because a
# bare `pos` and a bare `step` in the presentation veto silently excused all
# three, and a word that blocks a metric spelling is how a transcribed table
# ships. `xpos`, `ypos` and `tick` are what veto the figure idioms.
f1_pos = 0.4812  # VIOLATION
pos_f1 = 0.4812  # VIOLATION
step_loss = 0.0317  # VIOLATION
