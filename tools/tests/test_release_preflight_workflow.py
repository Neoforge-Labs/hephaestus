"""Scenario tests for release.yml's "Require a release token that can actually write".

The preflight exists to catch, in one second and in plain words, the thing that
otherwise surfaces six minutes into release-please as "Resource not accessible
by personal access token". Its first version asked the wrong question: it read
`.permissions.push` from `GET /repos/{repo}`, which reports the authenticated
USER's role on the repository, not the TOKEN's granted scopes. A fine-grained
PAT owned by someone with push access reads `true` while holding no
`Contents: write` at all. Release run 42117513449 failed twice that way, with
the preflight printing its success line both times.

So the step now performs the operation release-please needs -- creates a git
ref with the same token -- and removes it again. What has to be pinned is:

    a token that cannot create a ref fails the step, naming what to grant
    the probe ref is always deleted, however the rest of the step ends
    a failed delete never changes the verdict about the token

These tests execute the step's REAL `run:` block, extracted from the YAML, with
`gh` stubbed on PATH (the same idiom as test_currency_source_workflow.py), under
`bash -e`, which is what Actions runs for a step with no explicit `shell:`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
STEP_NAME = "Require a release token that can actually write"

REPO = "Neoforge-Labs/hephaestus"
SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"
RUN_ID = "42117513449"
ATTEMPT = "2"
REF = f"release-preflight-probe/{RUN_ID}-{ATTEMPT}"

# Records every call as one line, then answers per the scenario env. A repo
# GET answers `true` to the `.permissions.push` query: that is exactly what the
# old probe saw from the PAT that could not create a ref, so an implementation
# that still trusts the field passes the read and is caught by the create.
GH_STUB = r"""#!/usr/bin/env bash
method=GET; path=""; jq=""; prev=""
for a in "$@"; do
  case "$prev" in
    -X) method="$a" ;;
    --jq) jq="$a" ;;
  esac
  case "$a" in repos/*) path="$a" ;; esac
  prev="$a"
done
fields=""
for a in "$@"; do case "$a" in ref=*|sha=*) fields="$fields $a" ;; esac; done
echo "$method $path$fields" >> "$GH_LOG"
echo "token=$GH_TOKEN" >> "$GH_LOG.env"
refused() { echo "gh: Resource not accessible by personal access token (HTTP 403)" >&2; exit 1; }
case "$method" in
  GET)
    [ "$READ_STATE" = ok ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
    case "$jq" in
      .permissions.push) echo true ;;
      *) echo "$GITHUB_REPOSITORY" ;;
    esac ;;
  POST)
    case "$CREATE_STATE" in
      ok)        echo "$GITHUB_SHA" ;;
      noisy)     echo "gh: a new release is available" >&2; echo "$GITHUB_SHA" ;;
      wrong_sha) echo "$OTHER_SHA" ;;
      refused)   refused ;;
    esac ;;
  DELETE)
    case "$DELETE_STATE" in
      ok)   ;;
      fail) echo "gh: Reference does not exist (HTTP 422)" >&2; exit 1 ;;
    esac ;;
esac
exit 0
"""


def preflight_step() -> str:
    """The step's `run:` block, straight out of the workflow."""
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["release-please"]["steps"]
    runs = [s["run"] for s in steps if s.get("name") == STEP_NAME]
    assert len(runs) == 1, f"expected exactly one {STEP_NAME!r} step, found {len(runs)}"
    return runs[0]


def run_step(
    tmp_path: Path,
    *,
    token: str = "ghp_stub",
    read: str = "ok",
    create: str = "ok",
    delete: str = "ok",
    run_id: str = RUN_ID,
    attempt: str = ATTEMPT,
) -> tuple[int, str, list[str]]:
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    gh = stubs / "gh"
    gh.write_text(GH_STUB, encoding="utf-8")
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{stubs}{os.pathsep}{env['PATH']}"
    env.update(
        GH_TOKEN=token,
        GH_LOG=str(log),
        GITHUB_REPOSITORY=REPO,
        GITHUB_SHA=SHA,
        OTHER_SHA=OTHER_SHA,
        GITHUB_RUN_ID=run_id,
        GITHUB_RUN_ATTEMPT=attempt,
        READ_STATE=read,
        CREATE_STATE=create,
        DELETE_STATE=delete,
    )
    done = subprocess.run(
        ["bash", "-e", "-c", preflight_step()],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
    return done.returncode, done.stdout + done.stderr, calls


pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

CREATE_CALL = f"POST repos/{REPO}/git/refs ref=refs/heads/{REF} sha={SHA}"
DELETE_CALL = f"DELETE repos/{REPO}/git/refs/heads/{REF}"


def test_a_token_that_cannot_create_a_ref_fails_the_preflight(tmp_path: Path) -> None:
    """The acceptance bar. The repo read still says push=true (as it did for the
    PAT in run 42117513449); only the ref create is refused."""
    code, output, calls = run_step(tmp_path, create="refused")
    assert code != 0, f"preflight passed a token that cannot create a ref\n{output}"
    assert "write permissions" in output, output
    assert "create pull requests" in output, output
    assert "Resource not accessible by personal access token" in output, "the refusal itself must be shown"
    assert CREATE_CALL in calls, calls


def test_the_refusal_names_all_three_permission_levels_and_how_to_read_them(tmp_path: Path) -> None:
    """A refusal here is a SETTING, and the setting exists in three places --
    repository, organisation, enterprise -- where the lowest wins. Naming only
    one sends the reader to a page that already looks correct, which is exactly
    how this cost four failed releases."""
    _, output, _ = run_step(tmp_path, create="refused")
    assert "repository" in output and "organisation" in output and "enterprise" in output
    assert "Workflow permissions" in output, "name the setting, not just the symptom"
    assert "actions/permissions/workflow" in output, "give a command that reads the real value"
    assert REPO in output


def test_a_token_that_can_create_a_ref_passes_and_deletes_it(tmp_path: Path) -> None:
    code, output, calls = run_step(tmp_path)
    assert code == 0, output
    assert f"token can create refs in {REPO}" in output
    assert "can write" not in output, "the line must not claim more than the probe proved"
    assert CREATE_CALL in calls, calls
    assert DELETE_CALL in calls, calls
    assert calls.index(CREATE_CALL) < calls.index(DELETE_CALL), "delete must follow create"


def test_stderr_noise_on_a_successful_create_is_not_a_wrong_sha(tmp_path: Path) -> None:
    code, output, calls = run_step(tmp_path, create="noisy")
    assert code == 0, output
    assert DELETE_CALL in calls


def test_the_probe_is_made_with_the_release_token(tmp_path: Path) -> None:
    run_step(tmp_path, token="ghp_the_release_token")
    seen = set((tmp_path / "gh.log.env").read_text(encoding="utf-8").splitlines())
    assert seen == {"token=ghp_the_release_token"}, seen


def test_the_ref_is_deleted_even_when_something_after_the_create_fails(tmp_path: Path) -> None:
    """The create succeeded but the ref points somewhere other than $GITHUB_SHA,
    so the step cannot vouch for the token. It fails -- and still cleans up."""
    code, output, calls = run_step(tmp_path, create="wrong_sha")
    assert code != 0, output
    assert CREATE_CALL in calls and DELETE_CALL in calls, calls


def test_a_failed_delete_does_not_fail_a_token_that_proved_it_can_write(tmp_path: Path) -> None:
    code, output, calls = run_step(tmp_path, delete="fail")
    assert code == 0, f"a stray probe branch must not be reported as a token fault\n{output}"
    assert DELETE_CALL in calls
    assert "::warning" in output and REF in output, "a leftover branch must be named so it can be removed"


def test_a_failed_delete_does_not_mask_a_refused_create(tmp_path: Path) -> None:
    code, output, _ = run_step(tmp_path, create="refused", delete="fail")
    assert code != 0, output
    assert "write permissions" in output and "create pull requests" in output, output
    assert "::warning" not in output, "nothing was created, so there is nothing to warn about"


def test_cleanup_is_attempted_even_when_the_create_was_refused(tmp_path: Path) -> None:
    """A create that errors on the wire can still have landed. Deleting a ref
    that does not exist is harmless; leaving one behind is not."""
    _, _, calls = run_step(tmp_path, create="refused")
    assert DELETE_CALL in calls, calls


def test_the_ref_name_comes_from_the_run_and_attempt(tmp_path: Path) -> None:
    created = []
    for i, (run_id, attempt) in enumerate([("1001", "1"), ("1001", "2"), ("1002", "1")]):
        sub = tmp_path / str(i)
        sub.mkdir()
        _, _, calls = run_step(sub, run_id=run_id, attempt=attempt)
        created.append(next(c for c in calls if c.startswith("POST")))
    assert len(set(created)) == 3, f"re-runs and concurrent runs must not share a ref: {created}"
    assert "release-preflight-probe/1001-1" in created[0]
    assert "release-preflight-probe/1001-2" in created[1]
    assert "release-preflight-probe/1002-1" in created[2]


def test_a_missing_run_identity_fails_rather_than_probing_a_shared_name(tmp_path: Path) -> None:
    code, output, calls = run_step(tmp_path, run_id="")
    assert code != 0, output
    assert not any(c.startswith("POST") for c in calls), calls


def test_an_unset_token_still_fails_with_its_own_message_and_never_calls_gh(tmp_path: Path) -> None:
    code, output, calls = run_step(tmp_path, token="")
    assert code == 1, output
    assert "workflow token is empty" in output
    assert calls == [], calls


def test_a_token_that_cannot_read_the_repo_still_fails_with_its_own_message(tmp_path: Path) -> None:
    code, output, calls = run_step(tmp_path, read="dead")
    assert code == 1, output
    assert "cannot read this repository" in output
    assert "Not Found" in output, "gh's own words must be shown"
    assert not any(c.startswith(("POST", "DELETE")) for c in calls), "nothing to probe or clean up"


def test_the_step_does_not_trust_the_permissions_field() -> None:
    """The defect itself, as text: `.permissions.push` is the user's role. Comments
    may explain why it is not used; no executable line may query it."""
    code_lines = [ln for ln in preflight_step().splitlines() if not ln.lstrip().startswith("#")]
    assert not any("permissions.push" in ln for ln in code_lines), code_lines
