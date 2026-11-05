"""Scenario tests for currency-source.yml's fetch step.

This gate decides whether `spec/currencies.yaml` still matches the ISO 4217
publication it is pinned to, and it is the only check that catches a
hand-edited exponent on a code no conformance vector covers. Its hard part is
not the comparison but the *attribution*: three outcomes have to be told apart
and reported differently, and a 200 is not proof the right bytes arrived --
Wayback, SIX's CDN and rate limiters all answer 200 with error pages.

    registry drifted      our defect; someone hand-edited or moved the pin
    publisher republished news; the registry is intact and a re-pin is deliberate
    fetch failure         neither; the run cannot say, and must not guess

Getting that attribution wrong is expensive in a specific way: it sends someone
after a defect that does not exist, or advises a re-pin to bytes that are not
the standard. It has been got wrong repeatedly, including once in a review
prescription, and the workflow is deliberately advisory with no required status
-- so nothing but this file stops a future edit swapping the two fetch guards
and reintroducing all of it.

These tests execute the step's REAL `run:` block, extracted from the YAML, with
`curl` and `uv` stubbed on PATH. Nothing here paraphrases the workflow, so an
edit to it is covered whether or not anyone remembers this file exists.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "currency-source.yml"

LIVE_URL = "https://www.six-group.com/example/list-one.xml"
ARCHIVE_URL = "https://web.archive.org/web/20260929233225id_/SIX/list-one.xml"

# The stub serves these exact bodies. PINNED_BODY is what the pin's sha256 is
# computed over, so the workflow's real `sha256sum` call is exercised rather
# than stubbed -- that call IS the fix under test.
PINNED_BODY = "PINNED-XML"
NEWER_BODY = "NEWER-XML-FROM-SIX"  # a real later List One: parses, hash differs
GARBAGE_BODY = "<html>429 Too Many Requests</html>"  # a 200 that is not List One

CURL_STUB = r"""#!/usr/bin/env bash
# Records the request, then serves or refuses per the scenario env.
url="${@: -1}"
out=""; prev=""
for a in "$@"; do
  if [ "$prev" = "-o" ]; then out="$a"; fi
  prev="$a"
done
echo "GET $url" >> "$REQ_LOG"
serve() {
  case "$1" in
    ok)          printf '%s' "$PINNED_BODY"  > "$out"; exit 0 ;;
    republished) printf '%s' "$NEWER_BODY"   > "$out"; exit 0 ;;
    wrong)       printf '%s' "$GARBAGE_BODY" > "$out"; exit 0 ;;
    dead)        echo "curl: (22) The requested URL returned error: 503" >&2; exit 22 ;;
  esac
  echo "stub curl: unknown state $1" >&2; exit 98
}
case "$url" in
  "$LIVE_URL")    serve "$LIVE_STATE" ;;
  "$ARCHIVE_URL") serve "$ARCHIVE_STATE" ;;
esac
echo "stub curl: unexpected url $url" >&2; exit 99
"""

# Stands in for the three `uv run` invocations the step makes: reading a field
# out of the pin, --verify-source, and --derivable. The real tool's behaviour
# that matters here is pinned by tools/tests/test_gen_currencies.py; what this
# stub reproduces is only the exit-status contract the workflow branches on.
UV_STUB = r"""#!/usr/bin/env bash
if [ "$2" = "--with" ]; then
  case "${@: -1}" in
    url)         echo "$LIVE_URL";    exit 0 ;;
    archive_url) echo "$ARCHIVE_URL"; exit 0 ;;
    sha256)      echo "$PINNED_SHA";  exit 0 ;;
  esac
  echo "stub uv: unknown pin field ${@: -1}" >&2; exit 99
fi
file="${@: -1}"
bytes="$(cat "$file")"
for a in "$@"; do
  if [ "$a" = "--derivable" ]; then
    # Parses as List One? Says nothing about the pin.
    if [ "$bytes" = "$PINNED_BODY" ] || [ "$bytes" = "$NEWER_BODY" ]; then
      echo "$file derives 181 entries"; exit 0
    fi
    echo "$file: cannot derive entries: no <CcyTbl> element" >&2; exit 1
  fi
done
# --verify-source: hash first, then the registry comparison.
if [ "$bytes" != "$PINNED_BODY" ]; then
  echo "$file: sha256 deadbeef does not match the pinned $PINNED_SHA. This is a different publication." >&2
  exit 1
fi
if [ "$REGISTRY" = drifted ]; then
  echo "currencies.yaml: SZL disagrees with List One -- minor_units: registry 3, List One 2" >&2
  exit 1
fi
echo "spec/currencies.yaml is exactly what $file derives to, and that file matches the pinned sha256"
exit 0
"""

DRIFTED = "::error title=Currency registry does not match its pinned publication"
REPUBLISHED = "::error title=Live ISO 4217 publication has changed"
REPUBLISHED_NOTICE = "::notice title=ISO 4217 has been republished"
LIVE_UNFETCHABLE = "::error title=Could not fetch the live ISO 4217 publication"
AMBIGUOUS = "::error title=Cannot tell the two causes apart"
NEITHER = "::error title=Neither location yielded the pinned publication"


def fetch_step() -> str:
    """The fetch step's `run:` block, straight out of the workflow."""
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["verify-source"]["steps"]
    runs = [s["run"] for s in steps if "run" in s and s.get("id") != "scope"]
    assert len(runs) == 1, f"expected one non-scope run block, found {len(runs)}"
    return runs[0]


@dataclass(frozen=True)
class Scenario:
    name: str
    event: str
    live: str
    archive: str
    registry: str
    exit_code: int
    expect: str
    forbid: str | None = None
    requests: list[str] | None = field(default=None)


# Every row states what the run must CONCLUDE, not merely that it failed: an
# exit code alone would let any of the three attributions pass for any other.
SCENARIOS = [
    # --- verifying a committed registry (pull_request / push): archive first,
    # --- so an upstream republication cannot turn a PR red for something the
    # --- PR did not cause.
    Scenario("pr-healthy", "pull_request", "ok", "ok", "intact", 0,
             "the registry is exactly what its pinned publication derives to"),
    Scenario("pr-upstream-republished-is-not-this-prs-problem", "pull_request", "republished", "ok", "intact", 0,
             "the registry is exactly what its pinned publication derives to",
             requests=["GET ARCHIVE"]),
    Scenario("pr-registry-drifted", "pull_request", "ok", "ok", "drifted", 1, DRIFTED),
    Scenario("pr-archive-unreachable-live-healthy", "pull_request", "ok", "dead", "intact", 0,
             "the registry verifies against the live file"),
    Scenario("pr-both-locations-unreachable", "pull_request", "dead", "dead", "intact", 1, NEITHER),
    Scenario("pr-archive-unreachable-and-registry-drifted", "pull_request", "ok", "dead", "drifted", 1, DRIFTED),
    # A capture answering 200 with an error page used to be annotated "the
    # registry was hand-edited". It is a fetch failure: it says nothing at all
    # about spec/currencies.yaml.
    Scenario("pr-archive-200-with-garbage-is-a-fetch-failure", "pull_request", "ok", "wrong", "intact", 0,
             "the registry verifies against the live file", forbid=DRIFTED),
    Scenario("pr-archive-200-garbage-and-live-dead", "pull_request", "dead", "wrong", "intact", 1,
             NEITHER, forbid=DRIFTED),
    Scenario("pr-archive-unreachable-and-live-republished", "pull_request", "republished", "dead", "intact", 1,
             NEITHER, forbid=DRIFTED),

    # --- checking whether the publisher moved on (schedule / dispatch): live
    # --- first, because that is the only thing the live file can tell us.
    Scenario("weekly-healthy", "schedule", "ok", "ok", "intact", 0,
             "the live publication still serves those bytes"),
    Scenario("weekly-live-unreachable", "schedule", "dead", "ok", "intact", 1,
             LIVE_UNFETCHABLE, forbid=REPUBLISHED),
    Scenario("weekly-republished-registry-intact", "schedule", "republished", "ok", "intact", 1, REPUBLISHED),
    Scenario("weekly-drifted-and-republished-reports-drift", "schedule", "republished", "ok", "drifted", 1,
             DRIFTED, forbid=REPUBLISHED_NOTICE),
    Scenario("weekly-drifted-only", "schedule", "ok", "ok", "drifted", 1, DRIFTED),
    Scenario("weekly-republished-and-archive-unreachable", "schedule", "republished", "dead", "intact", 1, AMBIGUOUS),
    # A live 200 serving a rate-limit page used to be reported as a
    # republication, advising a re-pin to bytes that are not the standard.
    Scenario("weekly-live-200-with-garbage-is-a-fetch-failure", "schedule", "wrong", "ok", "intact", 1,
             LIVE_UNFETCHABLE, forbid=REPUBLISHED),
    Scenario("weekly-archive-200-garbage-live-republished", "schedule", "republished", "wrong", "intact", 1,
             AMBIGUOUS, forbid=REPUBLISHED),
    # A dispatch exists to answer "has SIX republished?", so it must take the
    # live-first path and never the archive-first one.
    Scenario("dispatch-republished", "workflow_dispatch", "republished", "ok", "intact", 1, REPUBLISHED),
    Scenario("dispatch-healthy", "workflow_dispatch", "ok", "ok", "intact", 0,
             "the live publication still serves those bytes"),
    Scenario("dispatch-live-unreachable", "workflow_dispatch", "dead", "ok", "intact", 1,
             LIVE_UNFETCHABLE, forbid=REPUBLISHED),
    Scenario("dispatch-live-200-with-garbage-is-a-fetch-failure", "workflow_dispatch", "wrong", "ok", "intact", 1,
             LIVE_UNFETCHABLE, forbid=REPUBLISHED),
]


def run_scenario(scenario: Scenario, tmp_path: Path) -> tuple[int, str, list[str]]:
    import hashlib

    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("curl", CURL_STUB), ("uv", UV_STUB)):
        path = stubs / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    log = tmp_path / "requests.log"
    log.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{stubs}{os.pathsep}{env['PATH']}"
    env.update(
        EVENT=scenario.event,
        RUNNER_TEMP=str(tmp_path),
        REQ_LOG=str(log),
        LIVE_URL=LIVE_URL,
        ARCHIVE_URL=ARCHIVE_URL,
        LIVE_STATE=scenario.live,
        ARCHIVE_STATE=scenario.archive,
        REGISTRY=scenario.registry,
        PINNED_BODY=PINNED_BODY,
        NEWER_BODY=NEWER_BODY,
        GARBAGE_BODY=GARBAGE_BODY,
        PINNED_SHA=hashlib.sha256(PINNED_BODY.encode()).hexdigest(),
    )
    done = subprocess.run(
        ["bash", "-c", fetch_step()], cwd=ROOT, env=env, capture_output=True, text=True
    )
    requests = [
        line.replace(LIVE_URL, "LIVE").replace(ARCHIVE_URL, "ARCHIVE")
        for line in log.read_text(encoding="utf-8").splitlines()
        if line
    ]
    return done.returncode, done.stdout + done.stderr, requests


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="needs sha256sum (the step calls it)")
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_fetch_step_attributes_the_outcome_correctly(scenario: Scenario, tmp_path: Path) -> None:
    code, output, requests = run_scenario(scenario, tmp_path)
    assert code == scenario.exit_code, f"exit {code}, want {scenario.exit_code}\n{output}"
    assert scenario.expect in output, f"missing {scenario.expect!r}\n{output}"
    if scenario.forbid is not None:
        assert scenario.forbid not in output, f"wrongly reported {scenario.forbid!r}\n{output}"
    if scenario.requests is not None:
        assert requests == scenario.requests, f"{requests} != {scenario.requests}"


def test_the_two_fetch_guards_are_used_on_the_right_locations() -> None:
    """The guards are not interchangeable, and swapping them is the single edit
    that reintroduces every misdiagnosis above. `fetch_pinned` hash-gates, which
    is right for the immutable capture and wrong for the live file on a schedule
    -- a hash gate there can never detect a republication, which is that run's
    whole purpose. Asserted on the text because the scenarios cannot see which
    helper ran, only what it concluded."""
    step = fetch_step()
    assert "fetch_pinned archive" in step, "the immutable capture must be hash-gated"
    assert "fetch_current live" in step, "the live file must be derivability-gated, not hash-gated"
    assert "fetch_pinned live" in step, "the PR fallback to live must be hash-gated"
    assert "fetch_current archive" not in step, "the capture must never be merely derivability-gated"
    assert "sha256sum" in step, "fetch_pinned must actually hash"
    assert "--derivable" in step, "fetch_current must actually check for a List One document"


def test_the_scope_and_fetch_steps_split_the_events_identically() -> None:
    """Both steps branch on the event and the workflow's own comments say the
    conditions must stay identical: if `scope` treated a dispatch as in scope
    while `fetch` sent it down the archive-first path, a hand-dispatched run
    would never look at the live file and so could never answer the question it
    was dispatched to answer."""
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["verify-source"]["steps"]
    blocks = {s.get("id", s.get("name")): s["run"] for s in steps if "run" in s}
    condition = '[ "$EVENT" = schedule ] || [ "$EVENT" = workflow_dispatch ]'
    for name, block in blocks.items():
        assert condition in block, f"{name} does not split the events the same way"
