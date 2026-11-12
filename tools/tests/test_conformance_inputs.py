"""Every conformance suite directory must be an input of `conformance:check`.

moon caches a task on its declared inputs. `conformance:check` runs
`tools/check_vectors.py`, which enforces the vector-file schema and a
per-suite minimum case count — so a suite directory with no matching glob
means editing a vector in it does not invalidate the task, and that gate
silently does not run. CI's `moon run conformance:check` can hit the same
cache.

That was not hypothetical. `conformance/idempotency/` was added in
`2b9fe82` (PR #16) and went days without a glob, across every commit that
touched its two vector files, until the omission was spotted by review
rather than by a failing check. Nothing held the directory listing and the
input list equal, so the sixth suite would have repeated it. This test is
that equality, in the shape `check_modules.py` and `test_release_config.py`
already use elsewhere in the repo.

**The rule is one-directional, deliberately: a directory requires a glob,
never the reverse.** A glob may legitimately precede its directory as a
forward declaration — `lab/*.json` was added to the task while
`conformance/lab/` was still several tasks away — and a bidirectional
check would fail on exactly the pattern this test protects. The asymmetry
is also the honest one: a directory with no glob fails *silently*, while a
glob pointing at nothing is inert.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFORMANCE = REPO_ROOT / "conformance"
MOON_YML = CONFORMANCE / "moon.yml"

# Inputs are read with a regex rather than a YAML parser so this test needs no
# third-party import: tools/tests runs under a bare `uv run pytest` carrying
# only the dependencies its siblings already pull in.
_INPUT_LINE = re.compile(r"^\s*-\s*'(?P<value>[^']+)'\s*$")


def suites_without_globs(directories: set[str], globs: set[str]) -> list[str]:
    """The suites that need a glob and have none, sorted.

    Pure, so the rule can be tested on cases the repository does not
    currently contain — above all the forward declaration, a glob whose
    directory does not exist yet, which must NOT be reported.
    """
    return sorted(directories - globs)


def _declared_suite_globs() -> set[str]:
    """Suite names globbed by the `check` task, e.g. ``{"money", ...}``.

    Repository-absolute inputs (those starting with ``/``, such as
    ``/spec/errors.yaml``) are task inputs but not suites, and are skipped.
    """
    globs: set[str] = set()
    for line in MOON_YML.read_text(encoding="utf-8").splitlines():
        match = _INPUT_LINE.match(line)
        if match is None:
            continue
        value = match.group("value")
        if value.startswith("/") or not value.endswith("/*.json"):
            continue
        globs.add(value.removesuffix("/*.json"))
    return globs


def _suite_directories() -> set[str]:
    """Every ``conformance/<name>/`` holding at least one ``.json`` file."""
    return {
        child.name
        for child in CONFORMANCE.iterdir()
        if child.is_dir() and any(child.glob("*.json"))
    }


def test_every_suite_directory_is_an_input() -> None:
    missing = suites_without_globs(_suite_directories(), _declared_suite_globs())
    assert not missing, (
        f"conformance suites with no input glob in {MOON_YML.relative_to(REPO_ROOT)}: "
        f"{missing}. moon caches `conformance:check` on its inputs, so edits to "
        f"these suites do not re-run check_vectors.py and its schema and "
        f"minimum-case checks silently pass. Add '<name>/*.json' for each."
    )


def test_a_missing_glob_is_reported() -> None:
    """The rule has teeth: drop a glob and the suite is named."""
    assert suites_without_globs({"money", "idempotency"}, {"money"}) == ["idempotency"]


def test_a_glob_without_its_directory_is_not_reported() -> None:
    """The forward declaration, pinned so nobody tightens this into a
    bidirectional check and breaks a suite globbed before it is written."""
    assert suites_without_globs({"money"}, {"money", "lab"}) == []


def test_the_parser_finds_the_globs_that_are_there() -> None:
    """Guard the regex: a parser that silently matched nothing would make
    the repository assertion pass for every possible state."""
    declared = _declared_suite_globs()
    assert "money" in declared
    assert len(declared) >= 4


def test_repository_absolute_inputs_are_not_read_as_suites() -> None:
    """``/spec/errors.yaml`` and ``/tools/check_vectors.py`` are inputs but
    not suites; counting them would let a missing glob hide behind them."""
    declared = _declared_suite_globs()
    assert "spec" not in declared
    assert "tools" not in declared
