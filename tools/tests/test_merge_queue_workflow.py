"""The invariants that keep the merge queue from wedging `main`.

The queue exists for one failure the repo has already produced twice: two
branches that are green alone and red together. #16 moved `idempotency` from
planned to shipped in `spec/modules.yaml`; #14 added the `site-data.json` that
is generated from that registry. Each branch was genuinely green, because
neither held both halves, and `main` went red the moment both landed. Per-PR CI
cannot see such a pair by construction -- it never builds the combination.

A merge queue does build it. What it cannot survive is a workflow that does not
answer when the queue asks, so these pin the three things that would break it
silently rather than loudly:

    ci.yml runs on merge_group, or a queued PR waits forever for checks that
        never start and no merge ever completes

    no job in ci.yml is conditioned on the event being a pull_request, or that
        job never reports in the queue and a required check hangs

    include-slow stays false in the queue, or every merge drags the
        multi-megabyte tests along and merging becomes too slow to use

The first is the expensive one: removing the trigger does not fail any test
that watches PRs, and the symptom is a queue that simply never finishes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github/workflows/ci.yml"


def _workflow() -> dict[str, Any]:
    data: dict[Any, Any] = yaml.safe_load(CI.read_text(encoding="utf-8"))
    # YAML 1.1 parses an unquoted `on:` key as the boolean True.
    return {("on" if k is True else k): v for k, v in data.items()}


def _triggers() -> dict[str, Any]:
    on = _workflow()["on"]
    return on if isinstance(on, dict) else {name: None for name in on}


def test_ci_runs_on_merge_group() -> None:
    """Without this the queue asks for checks that never start, forever."""
    assert "merge_group" in _triggers(), (
        "ci.yml must keep its `merge_group:` trigger. The merge queue waits for "
        "the required checks to report on the queued merge commit; with no "
        "merge_group trigger they never run and no PR ever merges."
    )


def test_ci_still_runs_on_pull_request() -> None:
    """The queue is an extra gate, not a replacement for per-PR CI."""
    assert "pull_request" in _triggers()


def test_no_job_is_gated_on_the_event_being_a_pull_request() -> None:
    """A job skipped in the queue never reports, so a required check hangs."""
    offenders = [
        name
        for name, job in _workflow()["jobs"].items()
        if "pull_request" in str(job.get("if", ""))
    ]
    assert not offenders, (
        f"jobs gated on a pull_request event: {offenders}. Such a job does not "
        "run in a merge_group, so if it is a required check the queue blocks. "
        "Gate on something the queue also satisfies, or drop it from the "
        "required set."
    )


def test_slow_tests_stay_out_of_the_queue() -> None:
    """A merge_group run is pre-merge, so it belongs with pull_request here.

    The ref in a queue run is `refs/heads/gh-readonly-queue/...`, which does not
    start with `refs/heads/work/`, so the original expression evaluated TRUE for
    merge_group and would have run the 64 MB and 10M-char tests on every merge.
    They still run on the push to main straight afterwards.
    """
    include_slow = str(_workflow()["jobs"]["python"]["with"]["include-slow"])
    assert "merge_group" in include_slow, (
        "python's include-slow must exclude merge_group explicitly. Its ref is "
        "not under refs/heads/work/, so any check that only excludes "
        "pull_request and work branches lets the slow tests into every queued "
        f"merge. Current expression: {include_slow}"
    )
