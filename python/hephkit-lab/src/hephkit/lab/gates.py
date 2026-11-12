"""The integrity gates CI runs, which make sections 8 and 9 enforceable.

:func:`find_hardcoded_metrics` reads figure code, :func:`check_records_wellformed`
reads run records, :func:`check_cited_runs` reads a manuscript's citations, and
:func:`check_all` is the one call CI makes: it runs each gate it was given and
refuses with :class:`GateError` on what they found -- unless a gate finds a
subject missing rather than wrong, which is a refusal to check and stops there
(see the 412/424 split below).

This module was harvested from the ``experiments/gates.py`` of a project whose
manuscript audit found four things, and those four findings are the whole
specification of this file:

* F1 values held as literals in a figure script, so that "Figure 3 was a
  transcription of a table rather than a rendering of data";
* a record whose summary disagrees with its rows, which "is not evidence";
* a manuscript citing a run that does not exist, or one nobody can reproduce;
* a run record that is not citable.

**There is no spec section, and no conformance suite.** Sections 8 and 9 already
define what a record is and what a replay compares; a gate is a *policy* over
those definitions rather than a new wire contract, so there is nothing here for
another language to conform to. What design 9.3 assigns instead is contract
tests with violating fixtures, because a gate that has never been shown to fire
is indistinguishable from a passing codebase. ``tests/test_gates.py`` and
``tests/fixtures/violations/`` are that, and every gate below has both a fixture
it must flag and one it must pass.

**Nothing here reimplements a check that already exists.**
:func:`~hephkit.lab.record.read_record` *is* the well-formed check -- it refuses
a record whose stored summary disagrees with its rows, a line that is not a row
document and a repeated cell -- and :attr:`~hephkit.lab.record.RunRecord.complete`
is what says whether a record holds a summary. The records gate is therefore a
loop over ``read_record``, and the citations gate stands on ``complete``.

**``HEPH-LAB-412`` has exactly one raise site: :func:`raise_if_violated`.** Its
registry entry is "Integrity gate failed", its detail hint is that "the response
names the gate and what it found", and its guidance's three examples --
committing a run record, "removing the hardcoded metric from the figure script",
giving a dataset the manifest dimensions it lacks -- are this module's findings.
So every finding is a :class:`Violation` and the refusal that carries them is
one error, raised in one place.

That entry also says "A gate cannot pass on an artefact that does not exist at
all, which is HEPH-LAB-424", and this module takes it literally, which draws a
line worth stating because the two sides look alike:

* **The subject the gate was pointed at is not there** -- a figure path, a
  records root, a manuscript. The gate would otherwise pass by checking
  nothing, which is the one way a gate fails silently, so it raises
  :class:`MissingSubjectError`, a :class:`GateError` subclass carrying
  ``HEPH-LAB-424``. (``lab.config`` already pairs one code with another this
  way: ``MissingConfigError`` subclasses ``ConfigError`` and carries 424 while
  the base carries 422, so one ``except`` still catches every refusal and
  ``.code`` is what tells them apart.)
* **A record is missing one of its three documents.** ``read_record`` raises
  :class:`~hephkit.lab.record.RecordError` (424) and the records gate does
  **not** re-label it as a 412 finding: 424's own guidance names a record that
  is not there as its example, and "the artefact exists but says the wrong
  thing" is what it routes here.
* **A citation that resolves to nothing is still a finding**, not a missing
  subject. The subject of the citations gate is the manuscript, and the
  manuscript is there; "this citation names a run with no record" is exactly
  what that gate exists to find.

**What the citations gate can honestly check: replayability, not reproduction.**
:func:`~hephkit.lab.replay.replay` takes ``provenance`` as a required keyword
precisely so the baseline cannot be derived from the record being compared --
``config_hash``, ``data_hash``, ``deps_hash`` and ``code_sha`` would otherwise
be equal by construction and four of the five comparisons could never fail. A
gate has nowhere honest to get that provenance: capturing it needs the
configuration and the data this replay is pointed at, which is the project's
knowledge and not the gate's, and feeding the record's own provenance back in
is the degenerate comparison that keyword exists to prevent. A record does not
name the experiment that produced it either (7.1's members are the determinism
contract and nothing else), so this module could not call ``replay`` even if it
had the provenance.

So :func:`check_cited_runs` checks that each cited run **could** be replayed --
its record exists, is well-formed, is finished and is filed under the run it
records -- and takes the reproduction itself as a ``replay_check`` parameter the
project supplies, because the project is what knows the experiment name and can
capture a comparable provenance. When one is given, a report that did not match
becomes a violation, by way of
:meth:`~hephkit.lab.replay.DiffReport.raise_if_diverged`, whose docstring was
written for exactly this caller: "a gate asking whether a cited run still
reproduces".

**The metric scan parses; it does not match text.** A regex over source would
flag a version string, an axis limit, a hyperparameter and anything in a
comment, and a gate with false positives is a gate somebody switches off.
``tests/test_error_codes.py`` already establishes the pattern in this
repository, and it also shows the subtler half: the AST is what makes
docstring-awareness structural rather than a list of exclusions. A docstring is
a string constant in an expression statement, never an assignment target and
never a dict key, so the two shapes this scan looks at cannot reach one.

Conventions this module fixes, because no spec section does:

* **A metric is a name, a float literal and no veto word.**
  :data:`METRIC_WORDS` holds the words that name a number a run *produced*.
  :data:`VETO_WORDS` is what overrides them, in two groups justified
  differently: :data:`TUNING_WORDS` for how a run was configured
  (``loss_weight``, ``accuracy_threshold``, ``f1_cutoff``, ``target_f1``) and
  :data:`PRESENTATION_WORDS` for how a figure was drawn (``f1_ylim``,
  ``loss_alpha``, ``f1_bar_width``, ``f1_dpi``, ``recall_tick_step``). The
  second group is not optional decoration: qualifying a drawing parameter with
  the metric it renders is the ordinary idiom in the only code this gate reads,
  so without it the gate fires on correct figure code -- and a false positive
  there is how a gate gets switched off, exactly as a false negative is how a
  transcribed table ships. Every list is deliberately small, and every word is
  in one because an idiom puts it there.
* **An integer literal is not a metric.** In research code an integer is a
  count, an epoch or a seed, and a transcribed metric has decimals.
* **The gate is a floor rather than a proof**, and two shapes are outside it on
  purpose. A value computed at run time -- ``f1 = float("0.474")`` -- is not a
  literal, and nothing short of running the figure script would catch it. And a
  literal **bound to no name at all** is not reached: ``ax.bar(["f1", "acc"],
  [0.474, 0.812])`` and ``return [0.474, 0.812]`` both scan clean, which is the
  audit's own defect in its most literal form. That is a deliberate floor
  rather than an oversight: flagging float literals in call arguments would fire
  on every axis limit, colour, coordinate and figure size in the file, and a
  gate that noisy is a gate switched off. What catches those is the records gate
  and the citations gate -- a figure built from numbers nobody can cite has no
  record behind it.
* **A record directory is named by the run it records.** That is how a citation
  resolves: ``records / run_id``. The gate also compares the directory name
  against the record's own ``run_id``, so a mis-filed record is a finding
  rather than an invisible redirection.
* **A manuscript cites a run as ``run:<run_id>``** (:data:`CITATION`). It is a
  marker a manuscript can carry in prose, in a figure caption or in a comment,
  and it is anchored on a word boundary so ``rerun:`` and ``overrun:`` are not
  citations.

Maturity: experimental.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Final

from hephkit.errors import LAB_412, LAB_424
from hephkit.lab.record import PROVENANCE_NAME, RecordError, read_record
from hephkit.lab.replay import DiffReport, ReplayError
from pydantic import BaseModel, ConfigDict

__all__ = [
    "CITATION",
    "CITATIONS",
    "FIGURES",
    "METRIC_WORDS",
    "PRESENTATION_WORDS",
    "RECORDS",
    "TUNING_WORDS",
    "VETO_WORDS",
    "GateError",
    "MissingSubjectError",
    "ReplayCheck",
    "Violation",
    "check_all",
    "check_cited_runs",
    "check_records_wellformed",
    "cited_runs",
    "find_hardcoded_metrics",
    "names_a_metric",
    "raise_if_violated",
    "record_directories",
]

# Error codes live only in `spec/errors.yaml` (CLAUDE.md). `LAB_412` and
# `LAB_424` are generated from it and imported rather than re-spelled; the
# module docstring above argues which situation each one covers.

#: The code a gate refusal carries: "Integrity gate failed".
CODE = LAB_412

#: The code a gate carries when the subject it was pointed at is not there.
MISSING_CODE = LAB_424

#: The three gates, as they name themselves in a :class:`Violation`.
FIGURES: Final = "figures"
RECORDS: Final = "records"
CITATIONS: Final = "citations"

#: How a manuscript cites a run. A run id may carry dots, dashes and
#: underscores inside it and must begin and end alphanumeric, so a citation at
#: the end of a sentence does not swallow the full stop.
CITATION: Final = re.compile(r"\brun:(?P<run_id>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")

#: Words that name a number a run **produced**. A float literal bound to a name
#: carrying one of these was transcribed rather than read from a record, which
#: is the audit's first finding. Grouped by where each comes from.
METRIC_WORDS: Final[frozenset[str]] = frozenset(
    {
        # Classification, which is where the audit's own `f1 = 0.474` sat.
        #
        # `acc` and `precision` are the two most ambiguous entries in this set,
        # and both are kept deliberately. `acc` is also an accumulator
        # (`acc = 0.0`, then `acc += x`), and `precision` is also a numerical
        # tolerance (`precision = 1e-6`) and a number of decimal places. What
        # settles it is that this gate reads figure and table code, where an
        # accumulator is rare and a transcribed `acc = 0.812` is the defect;
        # where the tolerance idiom is spelled `tol`, `atol`, `rtol` or `eps`,
        # all of which the veto catches; and where decimal places are an
        # integer, which is not a float literal. Dropping either word is a
        # one-line change that leaves `accuracy`/`accuracies` standing.
        "accuracy",
        "accuracies",
        "acc",
        "precision",
        "recall",
        "sensitivity",
        "specificity",
        "f1",
        "f2",
        "fbeta",
        "mcc",
        "kappa",
        "auc",
        "auroc",
        "auprc",
        "roc",
        # Regression, and error as a reported quantity rather than an exception.
        "rmse",
        "mse",
        "mae",
        "mape",
        "r2",
        "rsquared",
        "error",
        "err",
        # Ranking, retrieval and language generation.
        "ndcg",
        "mrr",
        "bleu",
        "rouge",
        "meteor",
        "perplexity",
        "ppl",
        # Overlap, for segmentation work.
        "dice",
        "iou",
        "jaccard",
        # What an optimisation reports. `losses` is listed because the plural
        # rule below cannot reach it.
        "loss",
        "losses",
        "logloss",
        "nll",
        # The statistics a manuscript quotes in prose.
        "pvalue",
        "pval",
        # The generic word for a reported number.
        "score",
    }
)

#: Words that make a name an **input** rather than a result, whatever else it
#: carries. Each is here because a real idiom pairs it with a metric word, and
#: flagging that idiom is how a gate earns a pull request that switches it off:
#: `loss_weight`, `loss_scale`, `accuracy_threshold`, `score_thresh`,
#: `f1_cutoff`, `rel_tol`, `loss_tolerance`, `loss_eps`, `recall_epsilon`,
#: `loss_decay`, `target_f1`, `error_budget`, `loss_clip`.
TUNING_WORDS: Final[frozenset[str]] = frozenset(
    {
        "weight",
        "scale",
        "threshold",
        "thresh",
        "cutoff",
        "tol",
        "tolerance",
        "eps",
        "epsilon",
        "decay",
        "target",
        "budget",
        "clip",
    }
)

#: Words that make a name a value the **figure** was drawn with rather than a
#: value a run produced. This is the group a gate pointed only at figure code
#: cannot do without: qualifying an axis limit, an alpha, a bar width, a line
#: width, a dpi or a tick position *with the metric it renders* is the ordinary
#: idiom there -- `f1_ylim`, `loss_ymax`, `f1_vmin`, `loss_alpha`,
#: `f1_bar_width`, `loss_linewidth`, `f1_dpi`, `recall_tick_step`, `score_pad`,
#: `f1_xpos` -- and every one of them is a float literal. Flagging the
#: idiomatic spelling of the only code this gate reads is how a gate gets
#: switched off, and `tests/fixtures/violations/figure_clean.py` holds each of
#: those names so the veto has a witness rather than an argument.
#:
#: Note what is **not** here, and why the omissions are the load-bearing part.
#: Bare ``min`` and ``max`` would cost ``max_f1`` and ``min_loss``, which are a
#: reported best-of rather than geometry, so the axis forms are listed by their
#: own names (``ymax``, ``vmin``). Bare ``pos`` and ``step`` are absent for the
#: same reason -- they would cost ``f1_pos``, ``pos_f1`` and ``step_loss`` --
#: and they are not needed, because every idiom above is caught by a more
#: specific word: ``xpos``, ``ypos`` and ``tick`` do that work. A veto word
#: earns its place only when no narrower word already catches the idiom, since
#: a word that blocks a metric spelling is how a transcribed table ships.
PRESENTATION_WORDS: Final[frozenset[str]] = frozenset(
    {
        # Axes and limits, in the spellings matplotlib made idiomatic.
        "lim",
        "xlim",
        "ylim",
        "zlim",
        "xmin",
        "xmax",
        "ymin",
        "ymax",
        "vmin",
        "vmax",
        # Where a mark sits and how big it is.
        #
        # `xpos` and `ypos` are listed individually, and bare `pos` is
        # deliberately absent: a bare word would not have matched `xpos`
        # anyway -- that is why these two are here -- and it costs real recall,
        # because `f1_pos` and `pos_f1` are ordinary spellings for
        # positive-class F1 and a literal under either must be flagged. `tick`
        # is here for the same division of labour: it catches
        # `recall_tick_step`, so bare `step` is not needed and would have cost
        # `step_loss`, the loss at a training step.
        #
        # `size` stays, unlike those two, because it blocks no metric spelling
        # anybody uses -- `loss_size` names no reported number -- while it is
        # the only word that catches `f1_size` and `f1_marker_size`, which are
        # real matplotlib idioms.
        "xpos",
        "ypos",
        "offset",
        "pad",
        "margin",
        "size",
        "fontsize",
        "width",
        "height",
        "tick",
        "bins",
        # How a mark is drawn.
        "alpha",
        "linewidth",
        "lw",
        "dpi",
        "rotation",
        "zorder",
    }
)

#: The whole veto: a name carrying any of these is an input or a drawing
#: parameter, whatever metric word it also carries. Two groups because they are
#: justified differently -- one by how a run was configured, one by how a figure
#: was drawn -- and one union because :func:`names_a_metric` applies them alike.
VETO_WORDS: Final[frozenset[str]] = TUNING_WORDS | PRESENTATION_WORDS

#: A replay of one cited run: the project's own, because a gate has nowhere
#: honest to get the re-execution's provenance (see the module docstring). It is
#: handed the cited run id and the directory holding its record, and returns the
#: report :func:`~hephkit.lab.replay.replay` produced.
ReplayCheck = Callable[[str, Path], DiffReport]

#: Where a camel-case boundary sits, so `finalF1` reads as two words.
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

#: What separates words once the name is lowercased.
_SEPARATORS = re.compile(r"[^a-z0-9]+")


class GateError(RuntimeError):
    """An integrity gate refused (``HEPH-LAB-412``).

    :attr:`violations` is what was found, because the registry's detail hint for
    this code is that the response names the gate and what it found. Raised in
    one place only, :func:`raise_if_violated`.

    A ``RuntimeError`` rather than a :class:`hephkit.errors.HephError`, like
    every refusal in ``hephkit.lab``: this is research tooling below research
    code, not behind an HTTP boundary, so it carries no ``status``, ``title`` or
    ``type_url`` and ``.code`` is here for correlation and the registry's
    disambiguation.
    """

    code = CODE

    def __init__(self, message: str, violations: Sequence[Violation] = ()) -> None:
        super().__init__(message)
        self.violations = tuple(violations)


class MissingSubjectError(GateError):
    """The gate has no subject it can check (``HEPH-LAB-424``).

    Two ways that happens, and the class name only names the first. The subject
    is **not there**: a figure path that is neither a file nor a directory, a
    records root or a manuscript that does not exist. Or the subject is there
    and **cannot be read**: a manuscript that is not UTF-8 text, which leaves
    the citations gate with no citations to read. Both are the same failure in
    the sense that matters -- the gate would otherwise pass by checking nothing,
    which is the one way a gate fails silently -- and 412's own entry says a
    gate cannot pass on an artefact it cannot use.

    An unreadable figure *file* is deliberately not this: it is one subject
    among many, so it becomes a violation and the scan goes on (see
    :func:`_scan_file`). Only the gate's sole subject being unusable is a
    refusal. A :class:`GateError` subclass so one
    ``except GateError`` still catches every refusal this module makes, with
    ``.code`` telling them apart -- the pairing ``lab.config`` already uses for
    ``MissingConfigError``.
    """

    code = MISSING_CODE


class Violation(BaseModel):
    """One thing a gate found: which gate, what it was looking at, and what it is.

    Frozen and closed to extras, because a violation is the account of a check
    that already happened. ``strict`` as well, so a caller cannot hand a
    non-string in and have it coerced into a report CI prints.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    #: Which gate found it: :data:`FIGURES`, :data:`RECORDS` or :data:`CITATIONS`.
    gate: str
    #: What it is about: ``path:line`` for source, a record directory, a run id.
    subject: str
    #: What was found, in the words of the check that found it.
    detail: str

    def as_document(self) -> dict[str, str]:
        """This violation as a JSON-ready document."""
        return {"gate": self.gate, "subject": self.subject, "detail": self.detail}

    def __str__(self) -> str:
        return f"[{self.gate}] {self.subject}: {self.detail}"


def raise_if_violated(violations: Sequence[Violation]) -> None:
    """Refuse if anything was found (``HEPH-LAB-412``).

    The only raise site of ``HEPH-LAB-412`` in this module, and the one line a
    caller that has collected findings from individual gates writes. Silent on
    an empty sequence, so it may be called unconditionally.

    Not the only place a :class:`GateError` comes from: :class:`MissingSubjectError`
    is one too, and it is raised wherever a gate finds its subject absent.
    """
    if not violations:
        return
    found = "; ".join(str(violation) for violation in violations)
    raise GateError(
        f"{len(violations)} integrity violation(s): {found}",
        violations,
    )


def names_a_metric(name: str) -> bool:
    """Whether `name` names a number a run produced.

    True when a word of the name -- or the name with its separators dropped, so
    ``p_value`` reads as ``pvalue`` -- is in :data:`METRIC_WORDS`, and no word of
    it is in :data:`VETO_WORDS`. The veto wins, because a name carrying a tuning
    or presentation word is an input however much it looks like a result:
    ``loss_weight`` is a knob and ``f1_ylim`` is an axis limit.

    Words are split on separators and on camel-case boundaries, so ``f1_macro``,
    ``finalF1`` and ``ROC_AUC`` all match and ``learning_rate`` does not. A
    trailing ``s`` is dropped when what remains is itself a known word, which is
    what makes ``f1_scores`` a metric and leaves ``losses`` to be listed
    outright.
    """
    words = _words(name)
    if any(_singular(word) in VETO_WORDS for word in words):
        return False
    if any(_singular(word) in METRIC_WORDS for word in words):
        return True
    return _singular("".join(words)) in METRIC_WORDS


def _words(name: str) -> tuple[str, ...]:
    """`name` as lowercase words, split on separators and camel-case boundaries."""
    spaced = _CAMEL.sub("_", name).lower()
    return tuple(word for word in _SEPARATORS.split(spaced) if word)


def _singular(word: str) -> str:
    """`word` without a trailing `s`, when what remains is a word we know.

    Only then: stripping unconditionally would turn ``loss`` into ``los`` and
    delete the most common metric word there is.
    """
    stem = word[:-1]
    if word.endswith("s") and (stem in METRIC_WORDS or stem in VETO_WORDS):
        return stem
    return word


def find_hardcoded_metrics(paths: Iterable[Path]) -> list[Violation]:
    """Flag every float literal bound to a metric name under `paths` (the figures gate).

    A path may be a Python file or a directory, which is walked recursively for
    ``*.py``. A path that is neither raises :class:`MissingSubjectError`: a gate
    pointed at nothing would pass by checking nothing.

    Point this at the figure and table code, not at a project root: the walk
    follows every subdirectory, so a repository root would drag in a vendored
    ``.venv``, generated code and the test suite, and nothing here excludes
    them.

    The source is parsed rather than matched, so a comment never reaches the
    scan and a docstring is never an assignment target. What is flagged is a
    float literal reached from a name :func:`names_a_metric` recognises -- as an
    assignment, an annotated assignment, an attribute, a string subscript, an
    element of an unpacking, or a string key of a dict literal -- including one
    nested in a list, tuple, set or dict under such a name. Each literal is
    reported once however many names it was bound to, because the finding is the
    literal.

    A file that does not parse is itself a violation: a file the gate could not
    read is not a file the gate passed.
    """
    violations: list[Violation] = []
    for path in paths:
        for file in _python_files(path):
            violations.extend(_scan_file(file))
    return violations


def _python_files(path: Path) -> list[Path]:
    """The Python files `path` names: itself, or every one under it."""
    if path.is_dir():
        return sorted(path.rglob("*.py"))
    if path.is_file():
        return [path]
    raise MissingSubjectError(
        f"the figures gate was pointed at {path}, which is neither a file nor a "
        "directory; a gate with no subject passes by checking nothing"
    )


def _unreadable(file: Path, line: int, why: str) -> Violation:
    """The finding for a file the gate could not read: not read is not passed."""
    return Violation(
        gate=FIGURES,
        subject=f"{file}:{line}",
        detail=(
            f"the gate could not read this file, so it holds no assurance about it: "
            f"{why}"
        ),
    )


def _scan_file(file: Path) -> list[Violation]:
    """Every hardcoded metric in one file, in the order the file gives them.

    A file the gate cannot read is a finding rather than an abort, for both of
    the ways reading can fail: it is **one of many subjects**, so raising would
    leave every remaining file unchecked and hand the author a reason to exclude
    the path. The one subject the gate has, by contrast, is what
    :func:`cited_runs` refuses over.
    """
    try:
        source = file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [_unreadable(file, 1, f"it is not UTF-8 text ({exc.reason})")]
    try:
        tree = ast.parse(source, filename=str(file))
    except SyntaxError as exc:
        return [_unreadable(file, exc.lineno or 1, f"it could not be parsed: {exc.msg}")]
    found: dict[tuple[int, int], Violation] = {}
    for name, literal in _hardcoded(tree):
        found.setdefault(
            (literal.lineno, literal.col_offset),
            Violation(
                gate=FIGURES,
                subject=f"{file}:{literal.lineno}",
                detail=(
                    f"{name} is assigned the literal {literal.value!r}; a reported "
                    "metric is read from a run record (spec 8.1), not transcribed "
                    "into the code that renders it"
                ),
            ),
        )
    return [found[position] for position in sorted(found)]


def _hardcoded(tree: ast.Module) -> Iterator[tuple[str, ast.Constant]]:
    """Every (name, float literal) pair in `tree` whose name is a metric.

    Two shapes, and only two: a target assigned a value, and a string key of a
    dict literal. Neither can be a docstring, which is what makes this scan
    docstring-aware by construction rather than by exclusion.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                yield from _assigned(target, node.value)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None:
                yield from _assigned(node.target, node.value)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and names_a_metric(key.value)
                ):
                    yield from ((f"the key {key.value!r}", lit) for lit in _literals(value))


def _assigned(target: ast.expr, value: ast.expr) -> Iterator[tuple[str, ast.Constant]]:
    """The pairs one assignment target contributes.

    An unpacking is paired element by element with the value when the two have
    the same length, and otherwise each element is checked against the whole
    value -- ``f1, *rest = [0.474]`` does assign ``0.474`` to ``f1``, and a gate
    that gave up there would miss it.
    """
    if isinstance(target, ast.Tuple | ast.List):
        parts: Sequence[ast.expr] = (
            value.elts
            if isinstance(value, ast.Tuple | ast.List) and len(value.elts) == len(target.elts)
            else [value] * len(target.elts)
        )
        for element, part in zip(target.elts, parts, strict=True):
            yield from _assigned(element, part)
        return
    name = _target_name(target)
    if name is None or not names_a_metric(name):
        return
    yield from ((name, literal) for literal in _literals(value))


def _target_name(target: ast.expr) -> str | None:
    """The name an assignment target binds, or `None` for one with no name.

    A subscript counts when its key is a string literal, because
    ``table["rmse"] = 1.2048`` is how a results dict gets filled in. A computed
    subscript, a starred target and anything else has no name to match.
    """
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    if (
        isinstance(target, ast.Subscript)
        and isinstance(target.slice, ast.Constant)
        and isinstance(target.slice.value, str)
    ):
        return target.slice.value
    return None


def _literals(value: ast.expr) -> Iterator[ast.Constant]:
    """Every float literal in `value`, descending through literal containers.

    A negative literal is a unary operation over a constant, so the sign is
    stepped through. An integer is not a float in Python and a boolean is
    neither, so neither reaches this: an integer in research code is a count,
    an epoch or a seed.
    """
    if isinstance(value, ast.Constant):
        if isinstance(value.value, float):
            yield value
    elif isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.USub | ast.UAdd):
        yield from _literals(value.operand)
    elif isinstance(value, ast.Tuple | ast.List | ast.Set):
        for element in value.elts:
            yield from _literals(element)
    elif isinstance(value, ast.Dict):
        for element in value.values:
            yield from _literals(element)


def record_directories(root: Path) -> list[Path]:
    """Every directory under `root` that claims to be a run record (spec 8.1).

    A directory claims to be one by holding ``provenance.json``: 8.1 makes that
    the first document a record has, written before the run's first cell, so a
    run that died immediately still has one. Public so a test can assert the
    scan has subjects -- an empty scan would make the records gate pass by
    covering nothing.
    """
    _existing_directory(root, "the records gate")
    return sorted(path.parent for path in root.rglob(PROVENANCE_NAME))


def check_records_wellformed(root: Path) -> list[Violation]:
    """Flag every record under `root` that is not a record of what it claims.

    :func:`~hephkit.lab.record.read_record` is the check: it refuses a record
    whose stored summary disagrees with its rows (8.4), a line that is not a row
    document, and a cell named twice (8.2). Each refusal becomes one violation
    carrying the reader's own words.

    A record **missing** one of its three documents is not re-labelled: that is
    :class:`~hephkit.lab.record.RecordError` (``HEPH-LAB-424``) and it
    propagates, because 424's registry entry names an absent record as its own
    example and 412's says a gate cannot pass on an artefact that is not there.

    An **unfinished** record is not a violation either: 8.4 makes a record with
    no summary a run that died rather than a broken artefact, and
    :func:`check_cited_runs` is where citing one is refused.
    """
    violations: list[Violation] = []
    for directory in record_directories(root):
        try:
            read_record(directory)
        except ValueError as exc:
            violations.append(
                Violation(
                    gate=RECORDS,
                    subject=str(directory),
                    detail=f"this is not a record of the run it claims: {exc}",
                )
            )
    return violations


def cited_runs(manuscript: Path) -> list[str]:
    """Every run `manuscript` cites, in order of first mention and without repeats.

    The citation form is :data:`CITATION`. A manuscript that is not there, or
    that is not UTF-8 text, raises :class:`MissingSubjectError`: the manuscript
    is this gate's **one** subject, so a manuscript it cannot read leaves
    nothing to check, and returning "no citations" would be the silent pass the
    class exists to prevent. That is the other side of the figures gate's rule,
    where an unreadable file is one subject among many and becomes a finding so
    the rest still get checked.
    """
    path = _existing_file(manuscript, "the citations gate")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise MissingSubjectError(
            f"the citations gate cannot read {path} as UTF-8 text ({exc.reason}), so "
            "it has no citations to read; a gate with no subject passes by checking "
            "nothing"
        ) from exc
    seen: dict[str, None] = {}
    for match in CITATION.finditer(text):
        seen.setdefault(match["run_id"], None)
    return list(seen)


def check_cited_runs(
    manuscript: Path,
    records: Path,
    *,
    replay_check: ReplayCheck | None = None,
) -> list[Violation]:
    """Flag every run `manuscript` cites that is not citable (the citations gate).

    A citation resolves to ``records / run_id`` (see the module docstring on why
    a record directory is named by its run), and four things make it a finding:
    there is no record there, the record is not well-formed, the record is
    unfinished so the run never reached its end (8.4), or the record filed under
    that name is the record of another run.

    Those four are **replayability**: everything that must hold before
    :func:`~hephkit.lab.replay.replay` could be called at all. The reproduction
    itself is `replay_check`, which the project supplies, because a gate has
    nowhere honest to get the re-execution's provenance and a record does not
    name the experiment that produced it. Given one, a report that did not match
    becomes a violation by way of
    :meth:`~hephkit.lab.replay.DiffReport.raise_if_diverged`, so the positions
    that moved are named in the finding.

    `replay_check` is called only for a citation that passed the four checks
    above: there is nothing to reproduce where there is no finished record.
    """
    _existing_directory(records, "the citations gate")
    violations: list[Violation] = []
    for run_id in cited_runs(manuscript):
        directory = records / run_id
        try:
            record = read_record(directory)
        except RecordError as exc:
            violations.append(
                _cited(run_id, f"is cited, and there is no record of it at {directory}: {exc}")
            )
            continue
        except ValueError as exc:
            violations.append(
                _cited(run_id, f"is cited, and its record at {directory} is not one: {exc}")
            )
            continue
        if not record.complete:
            violations.append(
                _cited(
                    run_id,
                    f"is cited, and its record at {directory} is unfinished: it holds "
                    "rows and no summary, which spec 8.4 makes a run that did not "
                    "reach its end",
                )
            )
            continue
        if record.provenance.run_id != run_id:
            violations.append(
                _cited(
                    run_id,
                    f"is cited, and {directory} holds the record of "
                    f"{record.provenance.run_id!r} instead",
                )
            )
            continue
        if replay_check is None:
            continue
        try:
            replay_check(run_id, directory).raise_if_diverged()
        except ReplayError as exc:
            violations.append(_cited(run_id, f"is cited and does not reproduce: {exc}"))
    return violations


def _cited(run_id: str, detail: str) -> Violation:
    """One finding of the citations gate, whose subject is the cited run."""
    return Violation(gate=CITATIONS, subject=run_id, detail=detail)


def check_all(
    *,
    figures: Iterable[Path] = (),
    records: Path | None = None,
    manuscript: Path | None = None,
    replay_check: ReplayCheck | None = None,
) -> list[Violation]:
    """Run every gate it was given and refuse on what they found: the call CI makes.

    Each argument switches a gate on: `figures` the metric scan, `records` the
    well-formed check over a record tree, `manuscript` the citations check
    (which needs `records` to resolve a citation against). `replay_check` is
    passed through to :func:`check_cited_runs`.

    Raises :class:`GateError` when anything was found, with every violation on
    the error. The returned list is therefore empty whenever this returns at
    all; a caller that wants the findings without a refusal calls the individual
    checks, or reads :attr:`GateError.violations`.

    The gates run in order and each one's findings are collected, but a gate
    that cannot check at all stops the call: a
    :class:`~hephkit.lab.record.RecordError` (``HEPH-LAB-424``) from a record
    missing one of its documents propagates, as does
    :class:`MissingSubjectError` from a gate pointed at an absent or unreadable
    subject. **Findings already collected are lost when that happens**, and
    gates after it never run: a 424 about one absent ``rows.jsonl`` is NOT
    evidence that the figures gate passed, only that the records gate could not
    finish. Produce the artefact and run again to see the full account. That is
    deliberate -- 424 is a refusal to check rather than a finding -- but it does
    mean CI's one call has two failure codes and only the 412 carries every
    violation.

    Being asked to check nothing is a :class:`ValueError` rather than a pass: a
    gate run over no subject is the one way a gate fails silently.
    """
    paths = list(figures)
    if not paths and records is None and manuscript is None:
        raise ValueError(
            "check_all was given nothing to check: pass at least one of `figures`, "
            "`records` or `manuscript`, because a gate over no subject passes by "
            "checking nothing"
        )
    if manuscript is not None and records is None:
        raise ValueError(
            "a manuscript cites runs, so `records` is required to resolve its "
            "citations against"
        )
    violations: list[Violation] = []
    if paths:
        violations.extend(find_hardcoded_metrics(paths))
    if records is not None:
        violations.extend(check_records_wellformed(records))
    if manuscript is not None and records is not None:
        violations.extend(check_cited_runs(manuscript, records, replay_check=replay_check))
    raise_if_violated(violations)
    return violations


def _existing_file(path: Path, gate: str) -> Path:
    """`path`, or :class:`MissingSubjectError` when it is not a file."""
    if not path.is_file():
        raise MissingSubjectError(
            f"{gate} was pointed at {path}, which is not a file; a gate with no "
            "subject passes by checking nothing"
        )
    return path


def _existing_directory(path: Path, gate: str) -> Path:
    """`path`, or :class:`MissingSubjectError` when it is not a directory."""
    if not path.is_dir():
        raise MissingSubjectError(
            f"{gate} was pointed at {path}, which is not a directory; a gate with "
            "no subject passes by checking nothing"
        )
    return path
