"""A figure script that renders data rather than transcribing it.

Everything here is what a regex over the source would flag and what the gate
must not: version strings, axis limits, hyperparameters, tuning knobs named
after the metric they tune, integer counts, and the metric names themselves
bound to values read out of a record rather than typed in.

Like its violating sibling this file is read and parsed, never imported, and it
holds no marker comments at all -- `test_gates.py` asserts that too, so "the
clean fixture produces no violations" cannot be true because the fixture went
missing.
"""

from __future__ import annotations

from typing import Any

# A version string, which a regex for `\\d+\\.\\d+` cannot tell from an F1.
__version__ = "1.2.0"
SCHEMA_VERSION = 3

# Axis limits and figure geometry: numbers the author chose, not numbers a run
# produced.
ylim = (0.0, 1.0)
xlim = (0.0, 100.0)
figure_width = 6.4
figure_height = 4.8

# The same geometry, qualified by the metric the panel renders, which is the
# ordinary idiom in figure code and the only idiom this gate is ever pointed at.
# Every one of these is a float literal under a name carrying a metric word, so
# each needs the presentation veto rather than the structure of the scan.
f1_ylim = (0.0, 1.0)
loss_ymax = 2.5
f1_vmin = 0.4
loss_alpha = 0.35
f1_bar_width = 0.8
loss_linewidth = 1.25
f1_dpi = 220.0
recall_tick_step = 0.05
score_pad = 0.02
f1_xpos = 1.5

# Hyperparameters, which are inputs to a run.
learning_rate = 0.001
lr = 3e-4
warmup_fraction = 0.06
dropout = 0.1

# Knobs named after the metric they tune. Each carries a tuning word, which is
# the whole reason the vocabulary has a veto list: these are inputs.
loss_weight = 0.25
loss_scale = 128.0
accuracy_threshold = 0.9
f1_cutoff = 0.5
relative_tolerance = 1e-9
target_f1 = 0.6

# Integer counts, epochs and seeds. An integer is a count rather than a
# transcribed metric, and a transcribed metric has decimals.
epochs = 90
seed = 1234
n_correct = 847

# A metric name bound to something other than a float literal: this is what a
# figure script that renders data looks like.
RESULTS: dict[str, Any] = {}
f1 = RESULTS["f1"]
accuracy = float(RESULTS["accuracy"])
auroc_label = "AUROC"


def plot(records: list[dict[str, float]]) -> list[float]:
    """f1 = 0.474 in a docstring is documentation, not a second home for a number."""
    # And recall = 0.655 in a comment is the same.
    return [record["f1"] for record in records]
