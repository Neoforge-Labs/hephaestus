"""Release-please and workflow contracts.

These pin the properties of the CI/release configuration that, if they
regressed, would leave a gate green while checking nothing.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

LOCKSTEP = {
    ".": "hephaestus",
    "core/hephkit-core": "hephkit-core",
    "core/hephkit-py": "hephkit-py",
    "python/hephkit": "hephkit",
    "go": "go",
}
EXPECTED_WORKFLOWS = [
    "ci.yml",
    "python-ci.yml",
    "rust-ci.yml",
    "go-ci.yml",
    "rust-wheels.yml",
    "docker-publish.yml",
    "compose-boot.yml",
    "ecosystem.yml",
    "docs-ci.yml",
    "five-minute.yml",
    "release.yml",
]
REUSABLE = [w for w in EXPECTED_WORKFLOWS if w not in ("ci.yml", "release.yml")]


def load_workflow(name: str) -> dict:
    doc = yaml.safe_load((WORKFLOWS / name).read_text())
    # YAML 1.1 parses the bare key `on` as boolean True.
    if True in doc:
        doc["on"] = doc.pop(True)
    return doc


def test_release_please_links_all_four_components() -> None:
    cfg = json.loads((ROOT / "release-please-config.json").read_text())
    assert set(cfg["packages"]) == set(LOCKSTEP)
    for path, component in LOCKSTEP.items():
        assert cfg["packages"][path]["component"] == component
    linked = [p for p in cfg["plugins"] if p["type"] == "linked-versions"]
    assert len(linked) == 1
    assert set(linked[0]["components"]) == set(LOCKSTEP.values())


def test_manifest_has_one_shared_version_for_every_package() -> None:
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    assert set(manifest) == set(LOCKSTEP)
    assert len(set(manifest.values())) == 1, manifest


def test_root_package_cuts_the_plain_tag() -> None:
    cfg = json.loads((ROOT / "release-please-config.json").read_text())
    assert cfg["include-component-in-tag"] is True
    root = cfg["packages"]["."]
    # An empty component is falsy and linked-versions silently skips it.
    assert isinstance(root["component"], str) and root["component"]
    assert root["include-component-in-tag"] is False
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    assert "." in manifest


def test_go_tags_are_go_slash_version() -> None:
    go = json.loads((ROOT / "release-please-config.json").read_text())["packages"]["go"]
    assert go["component"] == "go" and go["tag-separator"] == "/"


def test_linked_components_equal_package_components() -> None:
    cfg = json.loads((ROOT / "release-please-config.json").read_text())
    comps = {p["component"] for p in cfg["packages"].values()}
    linked = cfg["plugins"][0]["components"]
    assert set(linked) == comps and len(linked) == len(set(linked))


def test_release_reads_plain_outputs_and_moves_the_major_tag() -> None:
    text = (WORKFLOWS / "release.yml").read_text()
    assert "outputs.version" in text and "--version" not in text
    jobs = load_workflow("release.yml")["jobs"]
    assert "verify-release" in jobs["major-tag"]["needs"]
    assert jobs["major-tag"]["permissions"] == {"contents": "write"}


def test_manifest_matches_the_versions_in_the_tree() -> None:
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    version = manifest["python/hephkit"]
    for crate in ("hephkit-core", "hephkit-py"):
        text = (ROOT / "core" / crate / "Cargo.toml").read_text()
        assert re.search(rf'^version = "{re.escape(version)}"$', text, re.M), crate
    py = (ROOT / "python/hephkit/pyproject.toml").read_text()
    assert re.search(rf'^version = "{re.escape(version)}"$', py, re.M)


def test_go_version_is_updated_by_release_please() -> None:
    cfg = json.loads((ROOT / "release-please-config.json").read_text())
    extra = cfg["packages"]["go"]["extra-files"]
    assert extra, "go has no manifest, so release-please must edit a source file"
    # extra-files paths are relative to the package directory.
    target = ROOT / "go" / (extra[0] if isinstance(extra[0], str) else extra[0]["path"])
    assert "x-release-please-version" in target.read_text()


def test_every_expected_workflow_exists() -> None:
    for name in EXPECTED_WORKFLOWS:
        assert (WORKFLOWS / name).is_file(), name


@pytest.mark.parametrize("name", REUSABLE)
def test_reusable_workflows_are_workflow_call(name: str) -> None:
    assert "workflow_call" in load_workflow(name)["on"]


def test_no_workflow_swallows_failures() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text()
        assert "continue-on-error" not in text, path.name
        assert "|| true" not in text, path.name


def test_third_party_actions_are_pinned_to_full_shas() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        for ref in re.findall(r"^\s*-?\s*uses:\s*(\S+)", path.read_text(), re.M):
            if ref.startswith("./"):
                continue
            assert re.search(r"@[0-9a-f]{40}$", ref), f"{path.name}: {ref}"


def _service_images() -> list[tuple[str, str]]:
    """``(workflow, image)`` for every service container in every workflow.

    Read from the parsed YAML rather than by regex over the text: a conditional
    service writes its image as a folded scalar on the next line, which a
    line-oriented pattern misses, and a check that matches nothing passes.
    """
    return [
        (name, service["image"])
        for name in EXPECTED_WORKFLOWS
        for job in load_workflow(name)["jobs"].values()
        for service in (job.get("services") or {}).values()
    ]


def test_service_images_are_pinned_by_digest() -> None:
    """A service image is as much of a supply chain as an action.

    `postgres:17` moving is `pg_isready`, `gen_random_uuid()` and the default
    GUCs moving under the idempotency contract suite, four lines from an action
    pinned to a full sha.
    """
    images = _service_images()
    assert images, "no service container found, so this check proves nothing"
    for name, image in images:
        assert "@sha256:" in image, f"{name}: {image} is not pinned by digest"


def test_the_postgres_service_is_off_unless_the_caller_asks() -> None:
    """python-ci.yml is consumed by other repositories at @v0.

    A repository with no database test must not pull an image and wait on
    pg_isready to find that out, so the service and the DSN are both gated on
    the input and the input is off by default. This repository's own caller is
    where it is turned on.
    """
    workflow = load_workflow("python-ci.yml")
    assert workflow["on"]["workflow_call"]["inputs"]["postgres"]["default"] is False
    for name in ("python", "python-slow"):
        job = workflow["jobs"][name]
        assert "inputs.postgres" in job["services"]["postgres"]["image"], name
        assert "inputs.postgres" in job["env"]["HEPH_TEST_DATABASE_URL"], name

    caller = next(
        j for j in load_workflow("ci.yml")["jobs"].values()
        if j.get("uses", "").endswith("python-ci.yml")
    )
    assert caller["with"]["postgres"] is True


def test_pr_ci_calls_every_gate() -> None:
    jobs = load_workflow("ci.yml")["jobs"]
    called = {j.get("uses", "") for j in jobs.values()}
    for name in ("python-ci", "rust-ci", "go-ci", "compose-boot", "docker-publish", "docs-ci", "five-minute"):
        assert f"./.github/workflows/{name}.yml" in called, name
    assert "pull_request" in load_workflow("ci.yml")["on"]


def test_docs_job_runs_every_generator_check() -> None:
    """A stale generated page still renders, so only --check catches it.

    This is the failure this repository is most exposed to and the one a human
    reviewer is least likely to see, which is why each generator is named here
    rather than trusted to stay in the workflow.
    """
    text = (WORKFLOWS / "docs-ci.yml").read_text()
    for generator in ("gen_error_pages.py", "gen_site_pages.py", "gen_quickstart.py"):
        assert f"{generator} --check" in text, generator
    assert "bun run --cwd docs/site build" in text
    assert "bun test --cwd docs/site" in text
    assert "check_site_links.py" in text


def test_five_minute_runs_the_tutorial_and_enforces_only_on_schedule() -> None:
    """The tutorial is the five-minute claim; the budget is the number under it.

    `enforce-budget` must be off by default and on for the scheduled run: boot
    time on a shared runner is noisy, and a flaky gate gets muted rather than
    fixed.
    """
    workflow = load_workflow("five-minute.yml")
    text = (WORKFLOWS / "five-minute.yml").read_text()
    assert "bash examples/hello/tutorial_test.sh" in text
    assert "tools/dx_budget.sh" in text

    inputs = workflow["on"]["workflow_call"]["inputs"]
    assert inputs["enforce-budget"]["default"] is False

    ci = load_workflow("ci.yml")["jobs"]
    caller = next(j for j in ci.values() if j.get("uses", "").endswith("five-minute.yml"))
    assert caller["with"]["enforce-budget"] == "${{ github.event_name == 'schedule' }}"


def test_the_scripts_ci_runs_are_in_the_tree() -> None:
    """Every `bash <path>` a workflow runs names a file that exists.

    A workflow step pointing at a missing script fails only when the job runs,
    which for a scheduled gate can be a week after the mistake.
    """
    for path in WORKFLOWS.glob("*.yml"):
        for script in re.findall(r"bash\s+((?:tools|examples)/\S+\.sh)", path.read_text()):
            assert (ROOT / script).is_file(), f"{path.name} runs {script}, which is not in the tree"


def test_python_ci_runs_fast_path_and_every_generator_check() -> None:
    text = (WORKFLOWS / "python-ci.yml").read_text()
    assert "hephkit:test-fast" in text
    moon = yaml.safe_load((ROOT / "python/hephkit/moon.yml").read_text())
    assert "-m \"not slow\"" in moon["tasks"]["test-fast"]["script"]
    assert "not slow" not in moon["tasks"]["test"]["script"]
    for task in (
        "hephkit:gen-errors",
        "hephkit:gen-conventions",
        "hephkit:core-codes",
        "hephkit:typecheck",
        "conformance:check",
    ):
        assert task in text, task


def test_rust_ci_enforces_coverage_on_the_rustup_toolchain() -> None:
    text = (WORKFLOWS / "rust-ci.yml").read_text()
    assert "core:coverage" in text and "core:lint-py" in text
    moon = yaml.safe_load((ROOT / "core/moon.yml").read_text())["tasks"]
    assert "--fail-under-lines 90" in moon["coverage"]["command"]
    assert "-D warnings" in moon["lint-py"]["command"]
    assert "llvm-tools" in text


def test_trivy_gate_ignores_unfixed_and_fails_the_build() -> None:
    text = (WORKFLOWS / "docker-publish.yml").read_text()
    assert "ignore-unfixed" in text
    assert re.search(r"exit-code:\s*['\"]?1", text)
    assert "HIGH,CRITICAL" in text
    assert "linux/amd64" in text and "linux/arm64" in text


def test_wheels_cover_the_required_targets() -> None:
    text = (WORKFLOWS / "rust-wheels.yml").read_text()
    assert "PyO3/maturin-action" in text
    for needle in ("manylinux", "musllinux", "x86_64", "aarch64", "macos"):
        assert needle in text, needle


def test_release_please_uses_the_actions_token_with_the_permissions_it_needs() -> None:
    """The first release run failed with "GitHub Actions is not permitted to
    create or approve pull requests", and the workaround was a PAT -- which
    then failed three more times, on organisation policy and on token
    permissions. The cause was never the token: workflow permissions were
    pinned read-only and PR creation disabled at the enterprise, the
    organisation AND the repository, and the lowest setting wins.

    With those raised, GITHUB_TOKEN does the job and there is no secret to
    approve, expire or rotate. What must hold is that the job asks for the two
    permissions release-please needs, and that a preflight proves the setting
    still allows them -- because any of the three levels can take the write
    back without this repository changing at all."""
    doc = load_workflow("release.yml")
    job = doc["jobs"]["release-please"]
    steps = job["steps"]
    rp = next(s for s in steps if s.get("id") == "rp")
    token = rp["with"]["token"]
    assert "secrets.GITHUB_TOKEN" in token, token
    assert "RELEASE_PLEASE_TOKEN" not in (WORKFLOWS / "release.yml").read_text(), (
        "the PAT secret must be gone from the workflow, not merely unused"
    )
    # The permissions block is what grants GITHUB_TOKEN its scopes, so it is
    # now load-bearing rather than incidental.
    assert job["permissions"]["contents"] == "write", job["permissions"]
    assert job["permissions"]["pull-requests"] == "write", job["permissions"]
    assert any("Workflow write permissions are disabled" in str(s.get("run", "")) for s in steps)
    # Presence is not enough: the third release attempt failed with "Resource
    # not accessible by personal access token" from a token that WAS set. The
    # preflight must prove the token can write refs before release-please
    # spends a minute discovering it cannot.
    # `.permissions.push` is the USER's role, not the token's scopes, so it
    # cannot prove this; the probe must actually create a ref. Behaviour is
    # pinned in test_release_preflight_workflow.py.
    runs = [str(s.get("run", "")) for s in steps]
    assert any("git/refs" in r and "-X POST" in r for r in runs)


def test_breaking_changes_stay_in_zero_x() -> None:
    """Release-please's default for a 0.x version is to bump a breaking change
    to 1.0.0. Phase 1 carries two `feat(money)!:` commits, so without this the
    first published version is 1.0.0 -- and the first release run computed
    exactly that before it was blocked.

    1.0.0 is the semver claim that the API is committed. ADR 0015 says the
    opposite: "Everything in Phase 1 ships labelled `experimental`", and
    `stable` requires "use by two ingots in production, and passing ecosystem
    CI" -- there are no production ingots and every ecosystem row is disabled.
    So the version must stay in 0.x until the maturity labels say otherwise."""
    cfg = json.loads((ROOT / "release-please-config.json").read_text())
    assert cfg["bump-minor-pre-major"] is True


def test_ecosystem_enables_no_row_yet() -> None:
    """No row is enabled: examples/hello is the only candidate and Task 15 has
    not landed its tutorial script. This assertion used to read
    `enabled == {"examples/hello"}` while that row's command ran a
    tutorial_test.sh that does not exist -- a green test pinning a
    guaranteed-red gate."""
    doc = load_workflow("ecosystem.yml")
    include = doc["jobs"]["matrix"]["strategy"]["matrix"]["include"]
    assert {e["name"] for e in include if e["enabled"]} == set()
    assert {e["name"] for e in include} >= {"examples/hello", "Collie", "Domus", "SAWA", "NeoRx"}


def test_ecosystem_has_no_default_branch_privileged_trigger() -> None:
    """The job checks out a third-party repository at `matrix.ref` and runs its
    command. `schedule` and `workflow_dispatch` run in the default branch's
    context, where the job can write the Actions cache, so that combination is
    cache poisoning -- CodeQL alert 1,
    actions/cache-poisoning/poisonable-step, high. `workflow_call` leaves the
    context to the caller.

    Re-adding a trigger to restore the weekly run must fail here rather than
    quietly re-arm the alert. Running consumers on a timer needs them executed
    outside this repository's default-branch context, which is a design change
    and not a trigger."""
    on = load_workflow("ecosystem.yml")["on"]
    assert set(on) == {"workflow_call"}, on


def test_release_publishes_with_trusted_publishing_and_no_token() -> None:
    text = (WORKFLOWS / "release.yml").read_text()
    assert "id-token: write" in text
    assert "pypa/gh-action-pypi-publish" in text
    assert not re.search(r"PYPI_(API_)?TOKEN|password:", text)


def test_enabled_ecosystem_rows_are_pinned_and_runnable() -> None:
    """An enabled row must be able to pass. Pinning the ref and requiring a
    non-empty command was not enough: the command can name a script that is not
    in the tree, which is how examples/hello sat enabled and unrunnable. For a
    row that checks out THIS repo the paths its command names must exist, since
    they are paths we control and can therefore check."""
    include = load_workflow("ecosystem.yml")["jobs"]["matrix"]["strategy"]["matrix"]["include"]
    for e in include:
        if e["enabled"]:
            assert re.fullmatch(r"[0-9a-f]{40}|\$\{\{ github\.sha \}\}", e["ref"]), e["name"]
            assert e["command"].strip(), e["name"]
            if e["repo"] == "Neoforge-Labs/hephaestus":
                for target in _command_paths(e["command"]):
                    assert (ROOT / target).exists(), f"{e['name']} runs {target}, which is not in the tree"
        else:
            assert not re.fullmatch(r"[0-9a-f]{40}", e["ref"]) and e["ref"] != "main", e["name"]


def _command_paths(command: str) -> list[str]:
    """Repo-relative paths a shell command names: tokens holding a "/" that are
    not flags. Enough for the `bash <script>` shape these commands use."""
    return [t for t in shlex.split(command) if "/" in t and not t.startswith("-")]


def test_the_runnable_guard_would_catch_a_missing_script() -> None:
    """The guard above is the whole value of this change, so prove it fires
    rather than trusting that it would."""
    assert _command_paths("bash examples/hello/tutorial_test.sh") == ["examples/hello/tutorial_test.sh"]
    assert _command_paths("pytest -q") == []
    assert _command_paths("uv run --with pyyaml tools/check_registry.py") == ["tools/check_registry.py"]
    # A path that is absent by construction, not one that merely happened to be
    # absent when this was written: an earlier revision used
    # `examples/hello/tutorial_test.sh`, and the test broke the day that script
    # was added, because it was asserting the state of the tree rather than the
    # behaviour of the guard.
    assert not (ROOT / "tools/this-script-does-not-exist.sh").exists()
    assert (ROOT / "tools/check_registry.py").exists()


def test_release_publishes_nothing_without_a_verified_version() -> None:
    jobs = load_workflow("release.yml")["jobs"]
    for job in ("wheels", "images"):
        assert "verify-release" in jobs[job]["needs"], job


def test_release_moves_both_major_aliases() -> None:
    """The repo is consumed two ways and release-please creates neither alias.
    Reusable workflows resolve `...@v0` from the plain `v0` tag; the Go
    submodule resolves only from the `go/`-prefixed tags the release config
    cuts, so `go install .../go/cmd/heph@v0` needs `go/v0`. Both are moved by
    one job, in one push, so a partial failure cannot leave a half-moved pair."""
    job = load_workflow("release.yml")["jobs"]["major-tag"]
    assert job["permissions"] == {"contents": "write"}
    assert "verify-release" in job["needs"]
    (script,) = [s["run"] for s in job["steps"] if "run" in s]
    assert 'git tag -f "$major"' in script
    assert 'git tag -f "go/$major"' in script
    pushes = [line.strip() for line in script.splitlines() if "git push" in line]
    assert len(pushes) == 1, f"both refs must move in one push, found {pushes}"
    assert 'refs/tags/$major' in pushes[0] and 'refs/tags/go/$major' in pushes[0]
    assert "set -euo pipefail" in script, "a failed tag must fail the job"


def test_the_go_alias_prefix_matches_the_release_config() -> None:
    """`go/v0` is only the right alias while the `go` package's released tags
    are `go/vX.Y.Z`. If the tag-separator or component ever changed, the alias
    would point at a prefix nothing resolves from."""
    config = json.loads((ROOT / "release-please-config.json").read_text())
    go = config["packages"]["go"]
    assert go["component"] == "go" and go["tag-separator"] == "/"
    assert config["include-component-in-tag"] is True


def test_ci_never_cancels_runs_on_main() -> None:
    cancel = load_workflow("ci.yml")["concurrency"]["cancel-in-progress"]
    assert "refs/heads/main" in cancel


def test_tooling_test_step_pins_rfc8785_to_the_generators_own_header() -> None:
    """The reference canonicaliser is pinned in two places; keep them equal.

    tools/gen_idempotency_vectors.py declares it in a PEP 723 header, and
    python-ci installs it for the tooling tests that import that generator. A
    drift between them means CI validates the vectors with a different
    canonicaliser than the one that produced them, which is the one thing the
    provenance rule exists to prevent.
    """
    header = (ROOT / "tools" / "gen_idempotency_vectors.py").read_text()
    pinned = re.search(r'"(rfc8785==[0-9.]+)"', header)
    assert pinned, "gen_idempotency_vectors.py no longer pins rfc8785 in its PEP 723 header"
    workflow = (WORKFLOWS / "python-ci.yml").read_text()
    assert f"--with {pinned.group(1)}" in workflow, (
        f"python-ci.yml must install {pinned.group(1)} for the tooling tests"
    )
