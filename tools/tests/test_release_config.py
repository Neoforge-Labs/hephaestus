"""Release-please and workflow contracts.

These pin the properties of the CI/release configuration that, if they
regressed, would leave a gate green while checking nothing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

LOCKSTEP = {
    "core/hephkit-core": "hephkit-core",
    "core/hephkit-py": "hephkit-py",
    "python/hephkit": "hephkit",
    "go": "heph",
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


def test_pr_ci_calls_every_gate() -> None:
    jobs = load_workflow("ci.yml")["jobs"]
    called = {j.get("uses", "") for j in jobs.values()}
    for name in ("python-ci", "rust-ci", "go-ci", "compose-boot", "docker-publish"):
        assert f"./.github/workflows/{name}.yml" in called, name
    assert "pull_request" in load_workflow("ci.yml")["on"]


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


def test_ecosystem_enables_only_examples_hello() -> None:
    doc = load_workflow("ecosystem.yml")
    include = doc["jobs"]["matrix"]["strategy"]["matrix"]["include"]
    enabled = {e["name"] for e in include if e["enabled"]}
    assert enabled == {"examples/hello"}
    assert {e["name"] for e in include} >= {"Collie", "Domus", "SAWA", "NeoRx"}


def test_release_publishes_with_trusted_publishing_and_no_token() -> None:
    text = (WORKFLOWS / "release.yml").read_text()
    assert "id-token: write" in text
    assert "pypa/gh-action-pypi-publish" in text
    assert not re.search(r"PYPI_(API_)?TOKEN|password:", text)


def test_enabled_ecosystem_rows_are_pinned_and_runnable() -> None:
    include = load_workflow("ecosystem.yml")["jobs"]["matrix"]["strategy"]["matrix"]["include"]
    for e in include:
        if e["enabled"]:
            assert re.fullmatch(r"[0-9a-f]{40}|\$\{\{ github\.sha \}\}", e["ref"]), e["name"]
            assert e["command"].strip(), e["name"]
        else:
            assert not re.fullmatch(r"[0-9a-f]{40}", e["ref"]) and e["ref"] != "main", e["name"]


def test_release_publishes_nothing_without_a_verified_version() -> None:
    jobs = load_workflow("release.yml")["jobs"]
    assert "python/hephkit--version" in (WORKFLOWS / "release.yml").read_text()
    for job in ("wheels", "images"):
        assert "verify-release" in jobs[job]["needs"], job


def test_ci_never_cancels_runs_on_main() -> None:
    cancel = load_workflow("ci.yml")["concurrency"]["cancel-in-progress"]
    assert "refs/heads/main" in cancel
