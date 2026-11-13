"""Seeding, deterministic flags and provenance capture (spec section 7).

Three habits in here are deliberate.

**Every git state is a fixture repository.** Not one test reads the repository
this suite runs in: a test that did would pass or fail on whether the developer
happened to have uncommitted work, and "clean tree" is exactly the condition
under test. Each fixture asserts its own precondition with git itself, so the
`<head>` a test expects comes from ``git rev-parse HEAD`` rather than from
``capture``, and a fixture that silently failed to be the state it claims fails
the test at the fixture rather than in the assertion.

**NumPy and PyTorch are tested by what the call hands them.** The spine
installs neither (ADR 0023), and the no-CUDA path of Review Focus 5 cannot be
reached on a machine with no GPU in any case. So the tests put a recording stub
in ``sys.modules`` and assert which calls ``seed_everything`` made on it --
deterministic, and it names its cause on failure. The two tests that need the
real libraries are marked ``importorskip`` on top of that, not instead of it.

**Spec 7.5 is asserted, not merely obeyed.** It is the one MUST in section 7
with no automated guard anywhere in the repository, so ``env_rules.py`` says
what checking it means and the tests here call it.
"""

from __future__ import annotations

import getpass
import json
import os
import platform as platform_module
import random
import socket
import subprocess
import sys
import tempfile
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import env_rules
import pytest
from hephkit.lab import repro as repro_module
from hephkit.lab.repro import (
    DEFAULT_FRAMEWORKS,
    LOCKFILE_NAME,
    Accelerator,
    Environment,
    ProvenanceRecord,
    capture,
    describe_environment,
    detect_accelerator,
    parse_accelerator,
    seed_everything,
)
from pydantic import ValidationError

# Two content hashes (spec 4.2) to stand in for the canonical config and the
# dataset digest. `capture` takes both as given -- section 7.1 defers the
# digest scope of `data_hash` to section 10 -- so their values are arbitrary
# here, and these two are quoted from `conformance/hashing/content.json` so no
# hash string in this file is of unknown origin.
CONFIG_HASH = "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
DATA_HASH = "sha256:74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"
# sha256 of the two bytes `{}`, which is also the content hash of the canonical
# JSON `{}` that the same vector file pins.
EMPTY_OBJECT_HASH = CONFIG_HASH


def git_env() -> dict[str, str]:
    """An environment in which git answers to nobody's global config."""
    return {
        "PATH": os.environ.get("PATH", ""),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Vector Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Vector Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }


def git(repo: Path, *args: str) -> str:
    """Run git in `repo` and return its stdout, failing the test on error."""
    done = subprocess.run(  # noqa: S603 - fixed argv, test fixture
        ["git", *args],  # noqa: S607 - git from PATH, as the module itself uses it
        cwd=repo,
        env=git_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, f"git {' '.join(args)} failed: {done.stderr}"
    return done.stdout


def head(repo: Path) -> str | None:
    """The commit `HEAD` resolves to in `repo`, or None when it resolves to none.

    This is the independent source for every `code_sha` these tests expect: git
    answers, not `capture`.
    """
    done = subprocess.run(  # noqa: S603 - fixed argv, test fixture
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=repo,
        env=git_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else None


def a_tree(tmp_path: Path, *, lockfile: str | None = "{}") -> Path:
    """A directory with code in it, under no version control at all."""
    root = tmp_path / "tree"
    (root / "ignored").mkdir(parents=True)
    (root / "train.py").write_text("print('train')\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    if lockfile is not None:
        (root / LOCKFILE_NAME).write_text(lockfile, encoding="utf-8")
    assert head(root) is None, "the fixture is meant to be under no version control"
    return root


def a_repository(tmp_path: Path, *, lockfile: str | None = "{}", commits: bool = True) -> Path:
    """A git repository, with or without a commit in it."""
    root = a_tree(tmp_path, lockfile=lockfile)
    git(root, "init", "-b", "main")
    if not commits:
        assert head(root) is None, "the fixture is meant to hold no commit"
        return root
    git(root, "add", "-A")
    git(root, "commit", "-m", "first")
    assert head(root) is not None, "the fixture is meant to hold a commit"
    assert git(root, "status", "--porcelain") == "", "the fixture is meant to be clean"
    return root


def captured(repo: Path, **kwargs: Any) -> ProvenanceRecord:
    return capture(
        run_id="run-under-test",
        config_hash=CONFIG_HASH,
        data_hash=DATA_HASH,
        repo=repo,
        **kwargs,
    )


# --- 7.3: the three conditions -------------------------------------------------


def test_a_clean_tree_with_a_lockfile_is_deterministic(tmp_path: Path) -> None:
    repo = a_repository(tmp_path)
    record = captured(repo)
    assert record.code_sha == head(repo)
    assert record.deps_hash == EMPTY_OBJECT_HASH
    assert record.run_class == "deterministic"


def test_a_modified_tracked_file_keeps_its_code_sha_and_is_provenance_only(
    tmp_path: Path,
) -> None:
    """Spec 7.1: a dirty tree does not null `code_sha`, it costs the class."""
    repo = a_repository(tmp_path)
    (repo / "train.py").write_text("print('changed')\n", encoding="utf-8")
    assert git(repo, "status", "--porcelain") != ""
    record = captured(repo)
    assert record.code_sha == head(repo)
    assert record.run_class == "provenance-only"


def test_an_untracked_file_is_not_a_clean_tree(tmp_path: Path) -> None:
    repo = a_repository(tmp_path)
    (repo / "scratch.py").write_text("x = 1\n", encoding="utf-8")
    record = captured(repo)
    assert record.code_sha == head(repo)
    assert record.run_class == "provenance-only"


def test_an_untracked_file_the_ignore_rules_exclude_leaves_the_tree_clean(
    tmp_path: Path,
) -> None:
    """7.3 excepts "those the repository's own ignore rules exclude"."""
    repo = a_repository(tmp_path)
    (repo / "ignored" / "checkpoint.bin").write_bytes(b"\x00")
    assert git(repo, "status", "--porcelain") == ""
    record = captured(repo)
    assert record.run_class == "deterministic"


def test_a_missing_lockfile_nulls_deps_hash_and_costs_the_class(tmp_path: Path) -> None:
    repo = a_repository(tmp_path, lockfile=None)
    record = captured(repo)
    assert record.code_sha == head(repo)
    assert record.deps_hash is None
    assert record.run_class == "provenance-only"


def test_the_lockfile_can_be_named_somewhere_other_than_the_default(tmp_path: Path) -> None:
    repo = a_repository(tmp_path, lockfile=None)
    # Outside the repository, so naming it cannot be confused with adding an
    # untracked file to the tree -- which would cost the run its class (7.3).
    other = tmp_path / "requirements.lock"
    other.write_bytes(b"")
    record = captured(repo, lockfile=other)
    # The published SHA-256 of the empty string (FIPS 180-4, RFC 6234).
    assert record.deps_hash == (
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert record.run_class == "deterministic"


def test_lockfile_bytes_are_hashed_as_read_rather_than_canonicalised(tmp_path: Path) -> None:
    """7.1 hashes the lockfile's bytes exactly as read: a lockfile need not be JSON.

    The same JSON document canonicalises (4.1) to `{"a":2,"b":1}`, whose content
    hash `conformance/hashing/content.json` pins as `sha256:d3626ac3...`. These
    bytes must not produce that digest.
    """
    repo = a_repository(tmp_path, lockfile=' { "b" : 1 , "a" : 2 } ')
    record = captured(repo)
    assert record.deps_hash == (
        "sha256:1ff73c34ab62b266b5852bb53ecb7064dc9fd64629b3397f59e76bc2ce7aa82a"
    )
    assert record.deps_hash != (
        "sha256:d3626ac30a87e6f7a6428233b3c68299976865fa5508e4267c5415c76af7a772"
    )


# --- Review Focus 2: the three git states --------------------------------------


def test_a_directory_under_no_version_control_is_provenance_only_not_an_error(
    tmp_path: Path,
) -> None:
    tree = a_tree(tmp_path)
    record = captured(tree)
    assert record.code_sha is None
    assert record.deps_hash == EMPTY_OBJECT_HASH
    assert record.run_class == "provenance-only"


def test_a_repository_with_no_commit_is_provenance_only_not_an_error(tmp_path: Path) -> None:
    repo = a_repository(tmp_path, commits=False)
    record = captured(repo)
    assert record.code_sha is None
    assert record.run_class == "provenance-only"


def test_a_detached_head_resolves_to_a_commit_and_is_an_ordinary_case(tmp_path: Path) -> None:
    repo = a_repository(tmp_path)
    commit = head(repo)
    assert commit is not None
    git(repo, "checkout", "--detach", commit)
    assert "HEAD detached" in git(repo, "status")
    record = captured(repo)
    assert record.code_sha == commit
    assert record.run_class == "deterministic"


def test_a_git_that_cannot_be_found_is_provenance_only_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A machine with no git at all: the capture degrades, it does not raise.

    The failure is injected rather than arranged, because what a missing binary
    *is* at this layer is a `FileNotFoundError` out of `subprocess.run`, and
    that is what the test hands the module. Emptying `PATH` would instead
    depend on how a path lookup treats an empty `PATH`, which POSIX leaves
    implementation-defined; the test below keeps that as a smoke test and says
    so, so that this one is the guarantee.

    The argv is recorded, so a version of this that degraded by never invoking
    git at all would fail here rather than pass quietly.
    """
    repo = a_repository(tmp_path)
    attempted: list[list[str]] = []

    def no_such_binary(args: Sequence[str], **kwargs: Any) -> None:
        attempted.append(list(args))
        raise FileNotFoundError(2, "No such file or directory", args[0])

    monkeypatch.setattr(repro_module.subprocess, "run", no_such_binary)
    record = captured(repo)
    assert ["git", "-C", str(repo), "rev-parse", "HEAD"] in attempted
    assert record.code_sha is None
    assert record.deps_hash == EMPTY_OBJECT_HASH, "the lockfile does not need git"
    assert record.run_class == "provenance-only"


def test_an_empty_path_degrades_the_same_way_smoke_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same degradation reached through a path lookup rather than injection.

    A smoke test, deliberately named one. It holds because CPython does its own
    `PATH` search for a bare program name and falls back to `os.defpath` only
    when `PATH` is *absent*, so a `PATH` that is present and empty yields the
    bare name as the one candidate and the exec fails. That is CPython's
    behaviour, not something section 7 guarantees, and
    `test_a_git_that_cannot_be_found_is_provenance_only_not_an_error` is the
    test that pins the guarantee.
    """
    repo = a_repository(tmp_path)
    monkeypatch.setenv("PATH", "")
    record = captured(repo)
    assert record.code_sha is None
    assert record.run_class == "provenance-only"


def test_output_that_is_not_valid_utf8_does_not_raise_out_of_a_probe() -> None:
    """A probe's output is decoded with replacement, never strictly.

    `text=True` decodes strictly, and `UnicodeDecodeError` is a `ValueError`,
    so it would escape the `OSError`/`SubprocessError` guard and make a capture
    raise. It is reachable through git: non-ASCII paths are escaped only while
    `core.quotePath` is true, and this module runs with the machine's own git
    config.

    Tested at `_run` with an interpreter that writes an invalid byte, because
    the real trigger -- a tracked filename that is not valid UTF-8 -- cannot be
    created portably: APFS rejects one outright.
    """
    out = repro_module._run(  # noqa: SLF001 - the decode is this function's business
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff\\n')"]
    )
    assert out is not None
    assert "\ufffd" in out


def test_a_subdirectory_of_a_repository_carries_that_repositorys_commit(
    tmp_path: Path,
) -> None:
    """A subdirectory of a repository is still that repository's code.

    Git resolves `HEAD` from an ancestor, which is what makes a run started in
    `experiments/` carry the commit of the repository it sits in rather than a
    `null`.
    """
    repo = a_repository(tmp_path)
    inner = repo / "experiments"
    inner.mkdir()
    record = captured(inner)
    assert record.code_sha == head(repo)
    assert record.deps_hash is None, "the lockfile is looked for where the run was told"


# --- 7.1 and 7.2: the record itself --------------------------------------------


def test_the_record_serialises_in_the_member_order_of_the_7_1_table(tmp_path: Path) -> None:
    document = captured(a_repository(tmp_path)).as_document()
    assert list(document) == [
        "run_id",
        "config_hash",
        "data_hash",
        "deps_hash",
        "code_sha",
        "class",
        "environment",
    ]
    assert document["class"] == "deterministic"
    assert isinstance(document["environment"], dict)


def test_the_record_carries_the_hashes_it_was_given(tmp_path: Path) -> None:
    """7.1 defers `data_hash`'s digest scope to section 10, so it is a parameter."""
    record = captured(a_repository(tmp_path))
    assert record.run_id == "run-under-test"
    assert record.config_hash == CONFIG_HASH
    assert record.data_hash == DATA_HASH


def test_a_deterministic_record_cannot_carry_a_null_code_sha() -> None:
    with pytest.raises(ValidationError):
        ProvenanceRecord.model_validate(
            {
                "run_id": "r",
                "config_hash": CONFIG_HASH,
                "data_hash": DATA_HASH,
                "deps_hash": EMPTY_OBJECT_HASH,
                "code_sha": None,
                "class": "deterministic",
                "environment": {},
            }
        )


def test_the_class_underscore_spelling_is_not_a_value_of_the_field() -> None:
    """7.2: the hyphen in `provenance-only` is normative."""
    with pytest.raises(ValidationError):
        ProvenanceRecord.model_validate(
            {
                "run_id": "r",
                "config_hash": CONFIG_HASH,
                "data_hash": DATA_HASH,
                "deps_hash": None,
                "code_sha": None,
                "class": "provenance_only",
                "environment": {},
            }
        )


def test_a_document_carrying_run_class_instead_of_class_is_refused() -> None:
    """7.1: `run_class` is this binding's attribute name, not a record member."""
    with pytest.raises(ValidationError):
        ProvenanceRecord.model_validate(
            {
                "run_id": "r",
                "config_hash": CONFIG_HASH,
                "data_hash": DATA_HASH,
                "deps_hash": None,
                "code_sha": None,
                "run_class": "provenance-only",
                "environment": {},
            }
        )


def test_the_record_is_frozen_so_a_captured_value_cannot_be_edited_afterwards(
    tmp_path: Path,
) -> None:
    record = captured(a_repository(tmp_path))
    with pytest.raises(ValidationError):
        record.run_id = "another"  # type: ignore[misc]


# --- 7.4 and 7.5: environment ---------------------------------------------------


def test_environment_carries_the_four_reserved_members(tmp_path: Path) -> None:
    environment = captured(a_repository(tmp_path)).as_document()["environment"]
    assert list(environment) == ["platform", "python", "frameworks", "accelerator"]


def test_an_absent_framework_is_recorded_as_a_null_rather_than_omitted() -> None:
    """7.4: "A `null` under `frameworks` means the library was looked for and was absent"."""
    environment = describe_environment(frameworks=("heph-no-such-framework",))
    assert environment.frameworks == {"heph-no-such-framework": None}
    assert "heph-no-such-framework" in environment.as_document()["frameworks"]


def test_the_default_frameworks_are_the_two_the_spec_names() -> None:
    assert DEFAULT_FRAMEWORKS == ("numpy", "torch")
    assert set(describe_environment().frameworks or {}) == {"numpy", "torch"}


def test_a_present_framework_records_its_version() -> None:
    """pydantic is a spine dependency (ADR 0023), so it is always there to find."""
    frameworks = describe_environment(frameworks=("pydantic",)).frameworks or {}
    assert frameworks["pydantic"] is not None


def test_no_accelerator_is_recorded_as_null() -> None:
    environment = describe_environment(accelerator_probe=lambda: None)
    assert environment.accelerator is None
    assert environment.as_document()["accelerator"] is None


def test_an_accelerator_records_its_model_and_driver() -> None:
    probe = Accelerator(model="NVIDIA RTX 4090", driver="550.54.14")
    environment = describe_environment(accelerator_probe=lambda: probe)
    assert environment.as_document()["accelerator"] == {
        "model": "NVIDIA RTX 4090",
        "driver": "550.54.14",
    }


def test_a_member_7_4_does_not_name_serialises_after_the_ones_it_does() -> None:
    """The convention `conformance/lab/provenance.json` states, pinned here too.

    7.4 permits further members and says nothing about their order, so this is
    a convention of this implementation rather than a clause of the spec.
    """
    environment = Environment.model_validate(
        {"go": "1.23.4", "platform": "Linux-6.8.0-x86_64", "accelerator": None}
    )
    assert list(environment.as_document()) == ["platform", "accelerator", "go"]


def test_an_environment_member_that_was_never_set_is_omitted_not_nulled() -> None:
    """7.4 makes each member optional, so an absent one is absent, not null.

    A record from a runtime that is not Python has no `python` to record, and
    writing `python: null` would state a fact 7.4 does not define.
    """
    document = Environment.model_validate({"platform": "Linux-6.8.0-x86_64"}).as_document()
    assert document == {"platform": "Linux-6.8.0-x86_64"}


def test_a_captured_record_writes_all_seven_members_with_a_null_among_them(
    tmp_path: Path,
) -> None:
    """7.1: a record carries every member of the table, nulls included.

    This pins what `capture` produces. It is **not** the guard against an
    `exclude_unset` dump -- `capture` passes all seven explicitly, so every one
    is in `model_fields_set` and an `exclude_unset` dump would emit them
    anyway. The test below is that guard.
    """
    document = captured(a_repository(tmp_path, lockfile=None)).as_document()
    assert document["deps_hash"] is None
    assert set(document) == {
        "run_id",
        "config_hash",
        "data_hash",
        "deps_hash",
        "code_sha",
        "class",
        "environment",
    }


def test_a_member_left_to_a_default_is_still_written_into_the_document() -> None:
    """7.1's "MUST carry every member", against the one way it could be lost.

    `exclude_unset` drops a member only when it has a default *and* was not
    supplied. None of the seven has a default today, which is why the test
    above cannot see the difference, and why a future member that acquired one
    would be dropped silently. This subclass is that future: `deps_hash` with a
    default, left unsupplied, so the member is genuinely unset. It must still
    be written.

    The subclass inherits `as_document` unchanged, so what is under test is the
    real method and not a copy of it.
    """

    class RecordWithADefaultedMember(ProvenanceRecord):
        deps_hash: str | None = None

    record = RecordWithADefaultedMember.model_validate(
        {
            "run_id": "r",
            "config_hash": CONFIG_HASH,
            "data_hash": DATA_HASH,
            "code_sha": None,
            "class": "provenance-only",
            "environment": {},
        }
    )
    assert "deps_hash" not in record.model_fields_set, "the member must be genuinely unset"
    document = record.as_document()
    assert "deps_hash" in document, "a defaulted member must not be dropped from a record"
    assert document["deps_hash"] is None


def test_environment_carries_no_hostname_username_or_filesystem_path(tmp_path: Path) -> None:
    """Spec 7.5, the MUST with no automated guard anywhere else in the repository."""
    environment = captured(a_repository(tmp_path)).as_document()["environment"]
    assert env_rules.forbidden_facts(environment) == []


def test_the_7_5_scan_bites_when_a_forbidden_fact_is_present() -> None:
    """The check above passing means something, demonstrated rather than assumed."""
    assert env_rules.hostname_findings({"platform": socket.gethostname()})
    assert env_rules.username_findings({"ran_by": getpass.getuser()})
    assert env_rules.path_findings({"platform": str(Path.home())})
    assert env_rules.member_name_findings({"hostname": "anything"})
    assert env_rules.forbidden_facts({"nested": {"cwd": "anything"}})


def test_the_platform_member_names_the_architecture(tmp_path: Path) -> None:
    """7.4: `platform` is "Operating system and architecture"."""
    environment = captured(a_repository(tmp_path)).as_document()["environment"]
    assert platform_module.machine() in environment["platform"]


def test_the_python_member_is_the_running_interpreters_version() -> None:
    assert describe_environment().python == platform_module.python_version()


# --- seeding --------------------------------------------------------------------


def test_seed_everything_makes_the_stdlib_sequence_repeat() -> None:
    seed_everything(1234)
    first = [random.random() for _ in range(5)]  # noqa: S311 - not cryptographic
    seed_everything(1234)
    assert [random.random() for _ in range(5)] == first  # noqa: S311
    # The sequence a freshly seeded `random.Random` gives, so the assertion is
    # about `random.seed(1234)` having happened rather than about two calls
    # happening to agree with each other.
    independent = random.Random(1234)  # noqa: S311
    assert first == [independent.random() for _ in range(5)]
    seed_everything(5678)
    assert [random.random() for _ in range(5)] != first  # noqa: S311


def test_seed_everything_sets_pythonhashseed_for_child_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The variable does nothing for this interpreter; it is set for the next one."""
    monkeypatch.setenv("PYTHONHASHSEED", "unset")
    seed_everything(99)
    assert os.environ["PYTHONHASHSEED"] == "99"
    done = subprocess.run(  # noqa: S603 - our own interpreter, fixed argv
        [sys.executable, "-c", "import os; print(os.environ['PYTHONHASHSEED'])"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.strip() == "99"


class _Recorder:
    """A stand-in library that records the calls a seeding made on it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def record(self, name: str) -> Any:
        def call(*args: Any) -> Any:
            self.calls.append((name, args))
            return None

        return call

    def named(self) -> list[str]:
        return [name for name, _ in self.calls]


def fake_numpy(recorder: _Recorder) -> types.ModuleType:
    module = types.ModuleType("numpy")
    module.random = types.SimpleNamespace(seed=recorder.record("numpy.random.seed"))  # type: ignore[attr-defined]
    return module


def fake_torch(recorder: _Recorder, *, cuda: bool) -> types.ModuleType:
    module = types.ModuleType("torch")
    module.manual_seed = recorder.record("torch.manual_seed")  # type: ignore[attr-defined]
    module.use_deterministic_algorithms = recorder.record(  # type: ignore[attr-defined]
        "torch.use_deterministic_algorithms"
    )
    module.cuda = types.SimpleNamespace(  # type: ignore[attr-defined]
        is_available=lambda: cuda,
        manual_seed_all=recorder.record("torch.cuda.manual_seed_all"),
    )
    return module


BLOCKED = ("numpy", "torch")


class _Blocker:
    """A meta-path finder that refuses the scientific stack."""

    def find_spec(
        self, name: str, path: Sequence[str] | None = None, target: Any = None
    ) -> None:
        if name.split(".")[0] in BLOCKED:
            raise ImportError(f"{name} is blocked for this test")
        return None


@pytest.fixture
def no_scientific_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `import numpy` and `import torch` fail, whatever is installed.

    `monkeypatch` restores both `sys.modules` and `sys.meta_path` afterwards.
    """
    for name in BLOCKED:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Blocker(), *sys.meta_path])


def test_seed_everything_without_numpy_or_torch_seeds_the_stdlib_and_stops(
    no_scientific_stack: None,
) -> None:
    """The spine installs neither, so this is the path every spine run takes."""
    seed_everything(7)
    assert random.random() == random.Random(7).random()  # noqa: S311


def test_seed_everything_seeds_a_numpy_that_is_importable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setitem(sys.modules, "numpy", fake_numpy(recorder))
    seed_everything(11)
    assert recorder.calls == [("numpy.random.seed", (11,))]


def test_seed_everything_is_reproducible_for_a_real_numpy_when_it_is_present() -> None:
    numpy = pytest.importorskip("numpy", reason="NumPy is not a spine dependency")
    seed_everything(2024)
    first = numpy.random.random(4).tolist()
    seed_everything(2024)
    assert numpy.random.random(4).tolist() == first


def unset_cublas_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave `CUBLAS_WORKSPACE_CONFIG` unset, and restored after the test.

    The `setenv` records whatever the variable was (usually nothing) so that
    monkeypatch puts it back; the `delenv` is what the test then observes
    against.
    """
    monkeypatch.setenv("CUBLAS_WORKSPACE_CONFIG", "recorded-for-restoration")
    monkeypatch.delenv("CUBLAS_WORKSPACE_CONFIG")


def test_torch_without_cuda_is_seeded_deterministically_and_no_device_is_seeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review Focus 5: the CUDA calls must not be made when there is no device."""
    recorder = _Recorder()
    unset_cublas_workspace(monkeypatch)
    monkeypatch.setitem(sys.modules, "torch", fake_torch(recorder, cuda=False))
    seed_everything(13)
    assert recorder.named() == ["torch.manual_seed", "torch.use_deterministic_algorithms"]
    assert recorder.calls[0] == ("torch.manual_seed", (13,))
    assert recorder.calls[1] == ("torch.use_deterministic_algorithms", (True,))
    assert "CUBLAS_WORKSPACE_CONFIG" not in os.environ, (
        "there is no cuBLAS to configure on a machine with no CUDA device"
    )


def test_torch_with_cuda_seeds_every_device_and_configures_cublas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    unset_cublas_workspace(monkeypatch)
    monkeypatch.setitem(sys.modules, "torch", fake_torch(recorder, cuda=True))
    seed_everything(13)
    assert recorder.named() == [
        "torch.manual_seed",
        "torch.cuda.manual_seed_all",
        "torch.use_deterministic_algorithms",
    ]
    assert recorder.calls[1] == ("torch.cuda.manual_seed_all", (13,))
    # cuBLAS reads this when it initialises, which is why it is set before the
    # deterministic-algorithms flag rather than after it.
    assert os.environ["CUBLAS_WORKSPACE_CONFIG"] == ":4096:8"


def test_a_cublas_workspace_the_run_already_chose_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setenv("CUBLAS_WORKSPACE_CONFIG", ":16:8")
    monkeypatch.setitem(sys.modules, "torch", fake_torch(recorder, cuda=True))
    seed_everything(13)
    assert os.environ["CUBLAS_WORKSPACE_CONFIG"] == ":16:8"


def test_a_real_torch_without_a_cuda_device_records_a_null_accelerator() -> None:
    """Review Focus 5, with the real library when a run has one installed."""
    torch = pytest.importorskip("torch", reason="PyTorch is not a spine dependency")
    if torch.cuda.is_available():
        pytest.skip("this machine has a CUDA device, so the accelerator is not null")
    seed_everything(3)
    assert detect_accelerator() is None
    assert describe_environment().accelerator is None


def test_the_accelerator_parse_reads_an_nvidia_smi_line() -> None:
    """`nvidia-smi --query-gpu=name,driver_version --format=csv,noheader`."""
    assert parse_accelerator("NVIDIA GeForce RTX 4090, 550.54.14") == Accelerator(
        model="NVIDIA GeForce RTX 4090", driver="550.54.14"
    )


def test_the_accelerator_parse_takes_the_first_of_several_devices() -> None:
    reported = "NVIDIA A100-SXM4-80GB, 535.161.08\nNVIDIA A100-SXM4-80GB, 535.161.08\n"
    accelerator = parse_accelerator(reported)
    assert accelerator is not None
    assert accelerator.model == "NVIDIA A100-SXM4-80GB"


@pytest.mark.parametrize(
    "reported",
    [None, "", "   ", "\n", "NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 4090, ", ", 550.54.14"],
    ids=["none", "empty", "blank", "newline", "no-driver-field", "empty-driver", "empty-name"],
)
def test_anything_that_is_not_two_fields_is_no_accelerator(reported: str | None) -> None:
    assert parse_accelerator(reported) is None


def test_the_accelerator_probe_answers_null_when_nvidia_smi_is_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`nvidia-smi` missing is "no accelerator", not a failed capture.

    Injected, for the reason given on the git equivalent: a missing binary is a
    `FileNotFoundError` out of `subprocess.run`, and that is what this hands
    the probe. Emptying `PATH` would answer `None` on this machine whatever the
    lookup did -- there is no `nvidia-smi` to find -- so it would not be
    testing the degradation on a machine that has one.
    """
    attempted: list[list[str]] = []

    def no_such_binary(args: Sequence[str], **kwargs: Any) -> None:
        attempted.append(list(args))
        raise FileNotFoundError(2, "No such file or directory", args[0])

    monkeypatch.setattr(repro_module.subprocess, "run", no_such_binary)
    assert detect_accelerator() is None
    assert attempted == [list(repro_module._NVIDIA_SMI)]  # noqa: SLF001 - the argv is the point


# --- the spine stays a spine ----------------------------------------------------


def test_importing_repro_imports_neither_numpy_nor_torch() -> None:
    """ADR 0023: nothing heavy at module scope, and a capture needs neither."""
    program = "\n".join(
        [
            "import json, pathlib, sys",
            "from hephkit.lab import repro",
            "repro.capture(",
            "    run_id='r',",
            f"    config_hash={CONFIG_HASH!r},",
            f"    data_hash={DATA_HASH!r},",
            f"    repo=pathlib.Path({tempfile.mkdtemp()!r}),",
            ")",
            "print(json.dumps(sorted(m for m in ('numpy', 'torch') if m in sys.modules)))",
        ]
    )
    done = subprocess.run(  # noqa: S603 - our own interpreter, fixed argv
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == []
