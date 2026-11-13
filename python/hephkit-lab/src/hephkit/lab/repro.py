"""Seeding, deterministic flags and provenance capture (spec section 7).

:func:`seed_everything` seeds what a research run draws randomness from.
:func:`capture` builds the :class:`ProvenanceRecord` that describes one run and
classifies it ``deterministic`` or ``provenance-only``. Nothing here decides
what the spec already decides; the clauses worth restating are the ones an
implementation gets wrong by being helpful.

**A dirty tree keeps its ``code_sha``.** ``code_sha`` is the commit ``HEAD``
resolves to and is non-null whenever ``HEAD`` resolves, *regardless of whether
the working tree is clean* (7.1). A dirty tree does not null the field; it costs
the run the ``deterministic`` class instead (7.3). ``code_sha`` is therefore
``null`` in exactly one circumstance -- ``HEAD`` resolves to no commit -- and
that one circumstance covers code under no version control, a git repository
with no commit yet, and a tree held in another version-control system. Omitting
the member is never an alternative to the ``null``.

**Degrading is not failing.** No git, no commit, no git binary on the PATH, a
directory that is not there, an unreadable lockfile: each of those costs the run
the ``deterministic`` class and nothing else. A capture that raised would deny a
run its record over the very fact the record exists to state, and 7.3 says in as
many words that such a run "is still recorded in full". **There is consequently
no exception class in this module.** The task brief proposed
``ReproError`` carrying ``HEPH-LAB-424``, and the code's own guidance in
``spec/errors.yaml`` is about an artefact an operation *depends on* -- the record
being replayed, the manifest being read -- which is Task 9's territory, not this
one. Every failure reachable from :func:`capture` is one section 7 classifies
rather than refuses, so there is no honest raise site, and an exception class
with no raise site is worse than none. A malformed *record* is a different
thing: that is pydantic's :class:`~pydantic.ValidationError`, because a record
whose ``class`` is spelled ``provenance_only`` is a programming error in the
caller rather than a condition of the run.

**``deps_hash`` is over the lockfile's bytes exactly as read**, not over a
parsed or re-serialised form, because a lockfile is not required to be JSON and
spec 4.1's canonicalisation therefore does not apply to it (7.1). It is
:func:`hephkit.hashing.content_hash_bytes` of those bytes, and ``null`` exactly
when there is no lockfile to read.

**``data_hash`` is a parameter.** Its digest scope -- raw bytes or canonical
JSON, and how a multi-file dataset combines into one value -- is deliberately
deferred to spec section 10, which does not exist yet (7.1). This module
therefore records the value it is handed and computes nothing, rather than
inventing a scope that section 10 would have to contradict.

**``environment`` is descriptive and a replay MUST NOT compare it** (7.2). It
carries 7.4's four reserved members: ``platform``, ``python``, ``frameworks``
(a ``null`` for a library that was looked for and not found, which is recorded
rather than omitted) and ``accelerator`` (``null`` when the run used no
accelerator). 7.5 forbids it from carrying the hostname of the machine, the name
of the user who ran it, or any filesystem path, "under those or any other member
names", because a record is committed and published alongside its result. That
MUST has no automated guard: this module holds no blacklist of member names,
since 7.4 reserves four names and expressly permits further ones, and a model
refusing every member name that resembles a path would be inventing a rule the
spec does not state. ``tests/env_rules.py`` is where the prohibition becomes
checkable, and the tests there assert it of a real captured record.

Conventions this module fixes, because the spec does not:

* **The lockfile is ``uv.lock`` beside the code**, overridable per call. The
  spec says "a dependency lockfile exists" and names no file.
* **The accelerator probe reads ``nvidia-smi``**, which reports exactly 7.4's
  two members, and is a parameter so a project with other hardware supplies its
  own. No accelerator is reported for Apple's Metal or for a TPU: 7.4 wants a
  model and a driver version, neither of those platforms publishes a driver
  version in the sense NVIDIA does, and guessing one would put a made-up string
  in a published record.
* **Framework versions come from installed distribution metadata**
  (:mod:`importlib.metadata`), so looking for a framework never imports it. A
  capture of a torch-using run must not pay a torch import.
* **NumPy and PyTorch are imported inside the seeding functions and nowhere
  else.** They are not spine dependencies (ADR 0023) and must never become
  importable-at-module-scope requirements of it.

Maturity: experimental.
"""

from __future__ import annotations

import importlib.metadata
import os
import platform as _platform
import random
import re
import subprocess  # noqa: S404 - fixed argv, no shell, see `_run`
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from hephkit.hashing import content_hash_bytes
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

__all__ = [
    "DEFAULT_FRAMEWORKS",
    "DETERMINISTIC",
    "LOCKFILE_NAME",
    "PROVENANCE_ONLY",
    "Accelerator",
    "CommitSha",
    "ContentHash",
    "Environment",
    "ProvenanceRecord",
    "RunClass",
    "capture",
    "describe_environment",
    "detect_accelerator",
    "parse_accelerator",
    "seed_everything",
]

#: The two values of `class` (spec 7.2). The hyphen in `provenance-only` is
#: normative, so it is spelled here and referred to everywhere else.
DETERMINISTIC: Final = "deterministic"
PROVENANCE_ONLY: Final = "provenance-only"

#: The type of `class`. It restates the two values because `Literal` takes
#: literals and nothing else (PEP 586): the constants above cannot stand in it.
RunClass = Literal["deterministic", "provenance-only"]

#: The lockfile a run is assumed to have, relative to the code (a convention;
#: spec 7.3 says only that one exists).
LOCKFILE_NAME: Final = "uv.lock"

#: The libraries a capture looks for unless told otherwise. 7.4's own example.
DEFAULT_FRAMEWORKS: Final[tuple[str, ...]] = ("numpy", "torch")

#: How long a probe may take before the capture gives up on it and degrades.
#: A hung `git` must not hang a research run.
_COMMAND_TIMEOUT: Final = 30.0

#: What `nvidia-smi` is asked for: exactly 7.4's two accelerator members.
_NVIDIA_SMI: Final[tuple[str, ...]] = (
    "nvidia-smi",
    "--query-gpu=name,driver_version",
    "--format=csv,noheader",
)

#: A content hash (spec 4.2): `sha256:` and 64 lowercase hex characters.
ContentHash = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]

#: A git commit, as lowercase hex (7.1). Both of git's object formats: SHA-1 is
#: 40 characters and SHA-256 is 64.
_COMMIT_PATTERN = r"^([0-9a-f]{40}|[0-9a-f]{64})$"
CommitSha = Annotated[str, StringConstraints(pattern=_COMMIT_PATTERN)]

# The same pattern the model enforces, so what a capture believes and what a
# record accepts cannot drift apart.
_COMMIT_RE = re.compile(_COMMIT_PATTERN)


def _run(args: Sequence[str]) -> str | None:
    """Run `args` and return its stdout, or None if it did not succeed.

    One place turns every way an external command can fail -- a missing binary,
    a non-zero exit, a hang, a working directory that is not there -- into the
    same `None`, because section 7 classifies all of them identically and none
    of them may raise out of a capture.

    `errors="replace"` is load-bearing, not tidiness. `text=True` decodes
    strictly, and a strict decode raises `UnicodeDecodeError`, which is a
    `ValueError` and so escapes both excepts above -- the one way out of this
    function that would contradict the paragraph above. It is reachable: git
    escapes non-ASCII paths only while `core.quotePath` is true, this module
    runs with whatever git config the machine has, and a repository holding a
    filename that is not valid UTF-8 would otherwise make a capture raise.
    Nothing here parses the output byte for byte, so a replacement character in
    a `git status` line costs nothing: the line is still non-empty, which is the
    only thing 7.3 asks of it.
    """
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            list(args),
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=_COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _git(repo: Path, *args: str) -> str | None:
    return _run(["git", "-C", str(repo), *args])


def _head_commit(repo: Path) -> str | None:
    """The commit `HEAD` resolves to in `repo`, or None when it resolves to none.

    The output is matched against the shape of a commit before it is believed:
    a record carries a commit SHA or a `null`, and a capture that cannot read
    one records the `null` rather than putting whatever git printed into a
    published record.
    """
    out = _git(repo, "rev-parse", "HEAD")
    if out is None:
        return None
    candidate = out.strip()
    return candidate if _COMMIT_RE.fullmatch(candidate) else None


def _is_clean(repo: Path) -> bool:
    """Whether `git status --porcelain` prints nothing in `repo` (7.3).

    A tree git cannot report on is not clean: without a report there is nothing
    to say that the commit `code_sha` names is what ran.
    """
    out = _git(repo, "status", "--porcelain")
    return out is not None and out.strip() == ""


def _lockfile_hash(lockfile: Path) -> str | None:
    """The content hash of `lockfile`'s bytes as read, or None if it cannot be read.

    An unreadable lockfile is treated as no lockfile: nothing in the record
    pins the dependency set either way, which is what 7.3's third condition
    turns on.
    """
    try:
        data = lockfile.read_bytes()
    except OSError:
        return None
    return content_hash_bytes(data)


def _framework_version(name: str) -> str | None:
    """The installed version of `name`, or None when it is not installed.

    Read from distribution metadata, so looking for a framework never imports
    it.
    """
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


class Accelerator(BaseModel):
    """What ran the arithmetic (spec 7.4): a model and a driver version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    driver: str


class Environment(BaseModel):
    """Descriptive facts about the machine that ran a run (spec 7.4).

    Every member is optional, because 7.4 makes them individually optional: an
    implementation records only what it can observe, and one whose runtime is
    not Python omits `python` and records its own runtime under a member named
    for it. Further members are permitted, subject to 7.5, so extras are
    accepted and preserved. This implementation always records all four.

    It takes no part in any comparison: 7.2 forbids a replay from comparing it,
    and forbids reporting two records that differ only here as a divergence.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    platform: str | None = None
    python: str | None = None
    frameworks: dict[str, str | None] | None = None
    accelerator: Accelerator | None = None

    def as_document(self) -> dict[str, Any]:
        """This environment as JSON-ready members, omitting what was never set."""
        return self.model_dump(mode="json", exclude_unset=True)


class ProvenanceRecord(BaseModel):
    """One research run, described by the seven members of spec 7.1.

    Frozen, and closed to extras: 7.1 says a record "MUST NOT carry a top-level
    member this specification does not define", and frozen because a record is
    the account of a run that already happened.

    `class` is a Python keyword, so the attribute is `run_class` and the member
    is its alias. Serialise with :meth:`as_document`, never with a plain
    ``model_dump()``, which would write the attribute name. Validation is by
    the member name only -- `populate_by_name` is deliberately off -- because a
    document carrying `run_class` instead of `class` carries a top-level member
    7.1 does not define, and nothing should accept one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    config_hash: ContentHash
    data_hash: ContentHash
    deps_hash: ContentHash | None
    code_sha: CommitSha | None
    run_class: RunClass = Field(alias="class")
    environment: Environment

    @model_validator(mode="after")
    def _deterministic_names_its_code_and_its_dependencies(self) -> ProvenanceRecord:
        """7.3: a `deterministic` record carries both hashes non-null."""
        if self.run_class != DETERMINISTIC:
            return self
        missing = [
            name
            for name, value in (("code_sha", self.code_sha), ("deps_hash", self.deps_hash))
            if value is None
        ]
        if missing:
            raise ValueError(
                f"a {DETERMINISTIC} record must carry a non-null "
                f"{' and a non-null '.join(missing)} (spec 7.3); this run is "
                f"{PROVENANCE_ONLY}"
            )
        return self

    def as_document(self) -> dict[str, Any]:
        """This record as JSON-ready members, in the order of 7.1's table.

        No `exclude_unset` at this level: 7.1 says a record MUST carry every
        member of its table, so if one of the seven ever gained a default, an
        `exclude_unset` dump would quietly start omitting it. `environment` is
        replaced rather than left to the nested dump, because it is the one
        member whose own members are individually optional (7.4) and must
        therefore keep the `exclude_unset` that :meth:`Environment.as_document`
        applies -- a plain nested dump would write `python: null` into a record
        from a runtime that never had a `python` to record.
        """
        document: dict[str, Any] = self.model_dump(mode="json", by_alias=True)
        document["environment"] = self.environment.as_document()
        return document


def parse_accelerator(reported: str | None) -> Accelerator | None:
    """Read `nvidia-smi --format=csv,noheader` output into an accelerator.

    One line per device, `<name>, <driver_version>`. The first device is the one
    recorded: 7.4's `accelerator` is a single object, and which of several
    devices a run actually used is not something this probe can know. Anything
    that is not two non-empty fields is no accelerator rather than a failure --
    including `None`, which is what :func:`_run` returns when there is no
    `nvidia-smi` to run at all.

    Separate from :func:`detect_accelerator` so that the parse is testable on a
    machine with no NVIDIA hardware, which is every machine this suite runs on.
    """
    if reported is None or not reported.strip():
        return None
    name, _, driver = reported.strip().splitlines()[0].partition(",")
    if not name.strip() or not driver.strip():
        return None
    return Accelerator(model=name.strip(), driver=driver.strip())


def detect_accelerator() -> Accelerator | None:
    """The accelerator this machine reports, or None when it reports none.

    Reads `nvidia-smi`, which publishes exactly 7.4's two members. A machine
    with no NVIDIA tooling, or one whose `nvidia-smi` reports no device, has no
    accelerator to record; that is a `null`, not a failure.
    """
    return parse_accelerator(_run(_NVIDIA_SMI))


def describe_environment(
    *,
    frameworks: Sequence[str] = DEFAULT_FRAMEWORKS,
    accelerator_probe: Callable[[], Accelerator | None] = detect_accelerator,
) -> Environment:
    """Describe this machine, as spec 7.4 defines `environment`.

    `frameworks` are the libraries to look for; each one that is not installed
    is recorded as a `null`, because 7.4 records absence rather than assuming
    it. Nothing here reads the hostname, the user or any path (7.5).
    """
    parts = [part for part in (_platform.platform(terse=True), _platform.machine()) if part]
    return Environment(
        platform="-".join(parts),
        python=_platform.python_version(),
        frameworks={name: _framework_version(name) for name in frameworks},
        accelerator=accelerator_probe(),
    )


def _seed_numpy(seed: int) -> None:
    """Seed NumPy's legacy global generator, if NumPy is importable."""
    try:
        import numpy
    except ImportError:
        return
    numpy.random.seed(seed)


def _seed_torch(seed: int) -> None:
    """Seed PyTorch and ask it for deterministic kernels, if it is importable.

    The CUDA calls are made only when a device is there: on a machine with
    PyTorch and no CUDA device, `torch.cuda.manual_seed_all` has nothing to seed
    and `CUBLAS_WORKSPACE_CONFIG` has no cuBLAS to configure. The workspace
    variable is set before the deterministic-algorithms flag because cuBLAS
    reads it when it initialises, and without it a deterministic run on CUDA
    10.2 or later fails at the first affected kernel.
    """
    try:
        import torch
    except ImportError:
        return
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.use_deterministic_algorithms(True)


def seed_everything(seed: int) -> None:
    """Seed every source of randomness this process can reach.

    Seeds the standard library, then NumPy and PyTorch behind import guards, and
    sets `PYTHONHASHSEED`. That variable does **nothing** for the interpreter
    already running -- CPython reads it at startup -- and is set so that a child
    process this run spawns inherits the seed rather than randomising its hashes
    independently.

    Seeding is not by itself a determinism claim: a run is `deterministic` only
    if the three conditions of 7.3 hold, which is :func:`capture`'s business.
    """
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    _seed_numpy(seed)
    _seed_torch(seed)


def capture(
    *,
    run_id: str,
    config_hash: str,
    data_hash: str,
    repo: Path,
    lockfile: Path | None = None,
    frameworks: Sequence[str] = DEFAULT_FRAMEWORKS,
    accelerator_probe: Callable[[], Accelerator | None] = detect_accelerator,
) -> ProvenanceRecord:
    """Capture the provenance record of a run (spec 7.1), and classify it (7.3).

    `repo` is the directory the code ran from; `HEAD` is resolved there, which
    is git's own search, so a run started in a subdirectory carries the commit
    of the repository it sits in. `lockfile` defaults to ``uv.lock`` in `repo`.
    `config_hash` and `data_hash` are recorded as given: the digest scope of
    `data_hash` belongs to spec section 10.

    Nothing about a missing repository, a missing commit or a missing lockfile
    raises. Each one is a `provenance-only` record that still carries everything
    else, which is what 7.3 requires of a run whose code no commit names.
    """
    code_sha = _head_commit(repo)
    deps_hash = _lockfile_hash(lockfile if lockfile is not None else repo / LOCKFILE_NAME)
    deterministic = code_sha is not None and deps_hash is not None and _is_clean(repo)
    # By member name, through the same validation a record read from disk goes
    # through: `class` is not a Python identifier, so there is no keyword form
    # of this call to write instead.
    return ProvenanceRecord.model_validate(
        {
            "run_id": run_id,
            "config_hash": config_hash,
            "data_hash": data_hash,
            "deps_hash": deps_hash,
            "code_sha": code_sha,
            "class": DETERMINISTIC if deterministic else PROVENANCE_ONLY,
            "environment": describe_environment(
                frameworks=frameworks, accelerator_probe=accelerator_probe
            ),
        }
    )
