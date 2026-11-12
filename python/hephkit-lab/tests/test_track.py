"""Contract tests for `lab.track`: the wrapper that no-ops when unconfigured.

Design section 9.3 assigns this module contract tests rather than conformance
vectors -- there is no wire format here to pin, only four promises:

1. every call is a no-op when ``MLFLOW_TRACKING_URI`` is unset;
2. the context manager enters even when MLflow is unreachable;
3. the provenance class is logged as a tag;
4. importing the module does not require mlflow.

**Each no-op promise is paired with a positive twin.** A test that asserts
"nothing happened" passes just as well against a module that does nothing ever,
including when it should, so every negative here has a sibling that runs the
same code path with ``MLFLOW_TRACKING_URI`` set and asserts the call *was* made.
The pair is what distinguishes "no-ops when unset" from "never works": neither
test alone can tell them apart.

**How MLflow is faked, and why this way.** :func:`fake_mlflow` returns a
``types.ModuleType`` carrying exactly the attributes the wrapper is allowed to
touch, reached through ``sys.modules`` or through the real import machinery so
the lazy ``import mlflow`` finds it. Three properties earn it over a
``MagicMock``:

* a call the wrapper invents -- ``log_metric`` for ``log_metrics``, a renamed
  keyword -- raises ``AttributeError`` or ``TypeError`` here instead of being
  auto-created and passing silently;
* ``sys.modules`` is where the real import lands, so the stub is reachable
  *only* by executing ``import mlflow``: every assertion that a call arrived is
  also an assertion that the lazy import ran; and
* the recorder captures arguments in order, so "the class was tagged" is an
  assertion about a value, not about a call having happened.

It is the pattern ``test_repro.py`` uses for its torch stub, for the same
reasons.

An unreachable server is modelled by making a named stub call raise. The real
failure is an ``MlflowException`` or a ``ConnectionError`` out of these same
fluent entry points, and the wrapper catches ``Exception``, so the stub's
exception type is immaterial to what is being tested. No test here needs a live
MLflow, and none may: ``mlflow`` is not a spine dependency (ADR 0023).

``[tool.pytest.ini_options].filterwarnings = ["error"]`` makes every one of
these warnings load-bearing. A swallowed failure that warned nothing would fail
its ``pytest.warns`` assertion, and a warning raised where none is expected
fails that test outright.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import types
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Any

import pytest
from hephkit.lab import track
from hephkit.lab.repro import ProvenanceRecord
from hephkit.lab.track import TrackedRun, is_enabled, tracked_run

MODULE = Path(track.__file__)

CONFIG_HASH = "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
DATA_HASH = "sha256:74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"
DEPS_HASH = "sha256:0e3c2d4b2a8a5c01f8a4ca17a9e9b2d4d9b3c3b4e3f1a2d6c5b4a3928170605f"
CODE_SHA = "a" * 40

#: A URI nothing ever connects to: every test that sets the variable also
#: installs a stub, so no test here resolves a host.
URI = "http://127.0.0.1:54399"

#: The run id the stub's `start_run` reports. Distinct from any record's
#: `run_id`, because the two are different things.
RUN_ID = "mlflow-run-7"


def a_provenance(
    run_id: str = "run-0001",
    *,
    run_class: str = "deterministic",
) -> ProvenanceRecord:
    """A section 7 record, built by hand rather than captured.

    Hand-built for the reason `test_record.py` gives: `lab.track` tags the
    record it is handed, so a captured one would make every assertion here
    depend on the machine the suite runs on.
    """
    deterministic = run_class == "deterministic"
    return ProvenanceRecord.model_validate(
        {
            "run_id": run_id,
            "config_hash": CONFIG_HASH,
            "data_hash": DATA_HASH,
            "deps_hash": DEPS_HASH if deterministic else None,
            "code_sha": CODE_SHA if deterministic else None,
            "class": run_class,
            "environment": {"platform": "linux-x86_64", "python": "3.12.7"},
        }
    )


class _Recorder:
    """A stand-in MLflow that records the calls the wrapper made on it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def record(self, name: str, *, raises: BaseException | None = None) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            if raises is not None:
                raise raises
            return None

        return call

    def named(self) -> list[str]:
        return [name for name, _, _ in self.calls]

    def args(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(args, kwargs) for called, args, kwargs in self.calls if called == name]

    def only(self, name: str) -> tuple[tuple[Any, ...], dict[str, Any]]:
        found = self.args(name)
        assert len(found) == 1, f"expected exactly one {name} call, got {found!r}"
        return found[0]

    def tags(self, index: int = 0) -> dict[str, str]:
        (mapping,), _ = self.args("set_tags")[index]
        assert isinstance(mapping, dict)
        return mapping


#: Every fluent attribute the wrapper is allowed to touch. Anything else it
#: called would be an `AttributeError` from the stub.
SINK_CALLS = (
    "set_tracking_uri",
    "start_run",
    "log_params",
    "log_metrics",
    "log_artifact",
    "log_dict",
    "set_tags",
    "end_run",
)


def fake_mlflow(
    recorder: _Recorder,
    *,
    failing: frozenset[str] = frozenset(),
    broken_run_info: bool = False,
) -> types.ModuleType:
    """A recording `mlflow`, in which the calls named in `failing` raise.

    It **models mlflow's one active run**: a second `start_run` raises the
    refusal mlflow really raises, and `end_run` releases it. Without that state
    the stub cannot express the failure that matters most here -- an inner
    per-fold run being refused while an outer run is live -- and a cleanup that
    ended the outer run would look fine.

    `broken_run_info` starts the run successfully but returns an object with no
    `.info`, which is the only shape in which the wrapper's own cleanup is
    allowed to fire.
    """
    module = types.ModuleType("mlflow")
    active: list[str] = []

    def entry(name: str) -> Any:
        broken = RuntimeError(f"mlflow {name} is unreachable") if name in failing else None
        return recorder.record(name, raises=broken)

    for name in SINK_CALLS:
        setattr(module, name, entry(name))

    started, ended = entry("start_run"), entry("end_run")

    def start_run(**kwargs: Any) -> Any:
        started(**kwargs)
        if active:
            raise RuntimeError(f"Run with UUID {active[-1]} is already active.")
        active.append(RUN_ID)
        if broken_run_info:
            return types.SimpleNamespace()
        return types.SimpleNamespace(info=types.SimpleNamespace(run_id=RUN_ID))

    def end_run(**kwargs: Any) -> Any:
        ended(**kwargs)
        if active:
            active.pop()

    setattr(module, "start_run", start_run)  # noqa: B010 - a ModuleType attribute
    setattr(module, "end_run", end_run)  # noqa: B010 - a ModuleType attribute
    return module


class _Blocker:
    """A meta-path finder that refuses mlflow, whatever is installed.

    `error` is the exception the import raises. It defaults to the `ImportError`
    of a missing extra, and a half-installed one is any other exception out of a
    module body -- which is why the wrapper catches more than `ImportError`.
    """

    def __init__(self, error: BaseException | None = None) -> None:
        self._error = error

    def find_spec(self, name: str, path: Any = None, target: Any = None) -> None:
        if name.split(".")[0] == "mlflow":
            raise self._error or ImportError(f"{name} is blocked for this test")
        return None


class _StubLoader:
    """A loader that hands back a module object we already built."""

    def __init__(self, module: types.ModuleType) -> None:
        self._module = module

    def create_module(self, spec: ModuleSpec) -> types.ModuleType:
        return self._module

    def exec_module(self, module: types.ModuleType) -> None:
        """Already built, so there is nothing to execute."""


class _CountingFinder:
    """Supplies the stub through the real import machinery, counting imports.

    Used where the *timing* of the import is the claim: unlike a `sys.modules`
    entry, this records the moment the import statement runs.
    """

    def __init__(self, module: types.ModuleType) -> None:
        self._module = module
        self.imported: list[str] = []

    def find_spec(self, name: str, path: Any = None, target: Any = None) -> ModuleSpec | None:
        if name != "mlflow":
            return None
        self.imported.append(name)
        return importlib.util.spec_from_loader(name, _StubLoader(self._module))


@pytest.fixture(autouse=True)
def tracking_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from "tracking is off", whatever the developer exported.

    Without this, a machine with `MLFLOW_TRACKING_URI` set in its shell would
    turn the unset-variable contract into a test of something else, and the
    suite would pass or fail by environment.
    """
    monkeypatch.delenv(track.TRACKING_URI_VARIABLE, raising=False)


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


def install(
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
    *,
    failing: frozenset[str] = frozenset(),
) -> None:
    """Put the stub where the lazy `import mlflow` will find it."""
    monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow(recorder, failing=failing))


def block_mlflow(
    monkeypatch: pytest.MonkeyPatch, error: BaseException | None = None
) -> None:
    """Make `import mlflow` fail, whatever is installed."""
    monkeypatch.delitem(sys.modules, "mlflow", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Blocker(error), *sys.meta_path])


def enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(track.TRACKING_URI_VARIABLE, URI)


def exercise(run: TrackedRun, tmp_path: Path) -> None:
    """Call every logging method once, with arguments worth asserting on."""
    artifact = tmp_path / "figure.png"
    artifact.write_bytes(b"\x89PNG")
    run.log_params({"lr": "3e-4"})
    run.log_metrics({"auc": 0.91}, step=3)
    run.log_artifact(artifact)
    run.log_dict({"seed": 7}, "config.json")
    run.set_tags({"owner": "lab"})


# --------------------------------------------------------------------------
# Contract 1: every call is a no-op when MLFLOW_TRACKING_URI is unset.
# --------------------------------------------------------------------------


def test_every_call_is_a_noop_when_tracking_uri_is_unset(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, tmp_path: Path
) -> None:
    """The defining property. The stub is installed and must stay untouched.

    Installing it is the point: mlflow is importable here and would answer every
    call, so an empty recorder says the wrapper declined to reach it rather than
    that there was nothing to reach.
    """
    install(monkeypatch, recorder)
    assert is_enabled() is False
    with tracked_run("fit", provenance=a_provenance()) as run:
        assert run.enabled is False
        assert run.run_id is None
        exercise(run, tmp_path)
    assert recorder.calls == []


def test_every_call_reaches_mlflow_when_the_uri_is_set(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, tmp_path: Path
) -> None:
    """The positive twin of the test above: same stub, same calls, one variable.

    Without this, "no-ops when unset" is indistinguishable from "never works".
    The stub is reachable only through `import mlflow`, so this is also the
    proof that the lazy import runs when a run is tracked.
    """
    install(monkeypatch, recorder)
    enable(monkeypatch)
    assert is_enabled() is True
    with tracked_run("fit", provenance=a_provenance()) as run:
        assert run.enabled is True
        assert run.run_id == RUN_ID
        exercise(run, tmp_path)
    assert recorder.named() == [
        "set_tracking_uri",
        "start_run",
        "set_tags",  # the provenance tags, applied on entry
        "log_params",
        "log_metrics",
        "log_artifact",
        "log_dict",
        "set_tags",  # the caller's own, from `exercise`
        "end_run",
    ]
    assert recorder.only("set_tracking_uri") == ((URI,), {})
    assert recorder.only("start_run") == ((), {"run_name": "fit"})
    assert recorder.only("log_params") == (({"lr": "3e-4"},), {})
    assert recorder.only("log_metrics") == (({"auc": 0.91},), {"step": 3})
    assert recorder.only("log_dict") == (({"seed": 7}, "config.json"), {})
    assert recorder.tags(1) == {"owner": "lab"}
    assert recorder.only("end_run") == ((), {"status": "FINISHED"})


def test_the_artifact_path_reaches_mlflow_as_the_file_the_caller_named(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, tmp_path: Path
) -> None:
    """A `Path` arrives as a string, and `artifact_path` is passed through."""
    install(monkeypatch, recorder)
    enable(monkeypatch)
    figure = tmp_path / "roc.png"
    figure.write_bytes(b"\x89PNG")
    with tracked_run("fit", provenance=a_provenance()) as run:
        run.log_artifact(figure, artifact_path="figures")
    assert recorder.only("log_artifact") == ((str(figure),), {"artifact_path": "figures"})


def test_a_metric_logged_without_a_step_still_passes_one(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """`step=None` is mlflow's own default, so it is forwarded rather than
    dropped."""
    install(monkeypatch, recorder)
    enable(monkeypatch)
    with tracked_run("fit", provenance=a_provenance()) as run:
        run.log_metrics({"auc": 0.5})
    assert recorder.only("log_metrics") == (({"auc": 0.5},), {"step": None})


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_a_blank_variable_is_off_rather_than_a_uri(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """`MLFLOW_TRACKING_URI=` is how CI unsets one; it must not mean localhost."""
    monkeypatch.setenv(track.TRACKING_URI_VARIABLE, value)
    assert track.tracking_uri() is None
    assert is_enabled() is False


def test_a_uri_that_is_set_is_reported_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    """The twin of the blank-value test: a real value is neither defaulted nor
    rewritten."""
    monkeypatch.setenv(track.TRACKING_URI_VARIABLE, f"  {URI}  ")
    assert track.tracking_uri() == URI
    assert is_enabled() is True


def test_there_is_no_default_tracking_uri() -> None:
    """Named separately because it is the decision, not an implementation detail.

    An unset variable means off. It does not mean `http://localhost:5000`, which
    is what a wrapper with a default does and what makes a suite depend on
    whether a server happens to be listening.
    """
    assert track.TRACKING_URI_VARIABLE not in os.environ
    assert track.tracking_uri() is None
    assert is_enabled() is False


# --------------------------------------------------------------------------
# Contract 2: the context manager enters even when MLflow is unreachable.
# --------------------------------------------------------------------------


def test_context_manager_enters_even_when_mlflow_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, tmp_path: Path
) -> None:
    """A refused `start_run` must not keep the body from running."""
    install(monkeypatch, recorder, failing=frozenset({"start_run"}))
    enable(monkeypatch)
    entered = False
    with pytest.warns(RuntimeWarning, match="could not be started"):
        with tracked_run("fit", provenance=a_provenance()) as run:
            entered = True
            assert run.enabled is False
            assert run.run_id is None
            exercise(run, tmp_path)
    assert entered, "the body of the `with` did not run"
    # The start was attempted, nothing was logged against a run that does not
    # exist, and -- see the nested test below -- nothing was closed either.
    assert recorder.named() == ["set_tracking_uri", "start_run"]


def test_a_nested_run_that_mlflow_refuses_does_not_end_the_outer_run(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """A per-fold or per-trial inner run is an ordinary research shape.

    MLflow allows one active run per process, so the inner `start_run` is
    refused with "already active". A cleanup that called `end_run` on that
    refusal would close the **outer** run, mark it `FAILED`, and send its
    remaining metrics into a fresh run that mlflow's `_get_or_start_run()`
    creates -- one run silently split in two, the first labelled failed. That is
    worse than not tracking at all, and it is the one failure this module exists
    to rule out, so it gets its own test.
    """
    install(monkeypatch, recorder)
    enable(monkeypatch)
    with tracked_run("outer", provenance=a_provenance("run-outer")) as outer:
        with pytest.warns(RuntimeWarning, match="already active"):
            with tracked_run("inner", provenance=a_provenance("run-inner")) as inner:
                assert inner.enabled is False, "the inner run is untracked"
                inner.log_metrics({"fold_auc": 0.7})
        assert outer.enabled is True, "the outer run survived the inner refusal"
        assert recorder.args("end_run") == [], "nothing closed the outer run"
        assert outer.run_id == RUN_ID
        outer.log_metrics({"auc": 0.9})
    # One run started, one run closed, and it closed FINISHED rather than FAILED.
    assert recorder.only("end_run") == ((), {"status": "FINISHED"})
    assert len(recorder.args("start_run")) == 2
    # And the untracked inner run tagged nothing onto the outer one.
    assert len(recorder.args("set_tags")) == 1
    assert recorder.tags()[track.TAG_RUN_ID] == "run-outer"
    assert recorder.only("log_metrics") == (({"auc": 0.9},), {"step": None})


def test_a_run_whose_id_cannot_be_read_is_closed_so_the_next_one_can_start(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """The one path on which the wrapper's own cleanup is allowed to fire.

    Here `start_run` succeeded, so the active run is this call's own and leaving
    it active would refuse every later run. The second `tracked_run` is the
    assertion that matters: it succeeds only because the first released the
    process-global state.
    """
    monkeypatch.setitem(
        sys.modules, "mlflow", fake_mlflow(recorder, broken_run_info=True)
    )
    enable(monkeypatch)
    with pytest.warns(RuntimeWarning, match="its id could not be read"):
        with tracked_run("fit", provenance=a_provenance()) as run:
            assert run.enabled is False
    assert recorder.only("end_run") == ((), {"status": "FAILED"})
    # The second run reaches the SAME failure, which is the point: it got far
    # enough to start. Had the first left its run active, this would have been
    # refused with "already active" and warned "could not be started" instead.
    with pytest.warns(RuntimeWarning, match="its id could not be read"):
        with tracked_run("fit-again", provenance=a_provenance()) as again:
            assert again.enabled is False
    assert [kwargs for _, kwargs in recorder.args("start_run")] == [
        {"run_name": "fit"},
        {"run_name": "fit-again"},
    ], "the second start was not refused by a run left active"


def test_the_run_is_started_and_closed_when_mlflow_is_reachable(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """The positive twin: "enters" is not satisfied by never starting a run."""
    install(monkeypatch, recorder)
    enable(monkeypatch)
    with tracked_run("fit", provenance=a_provenance()) as run:
        assert run.enabled is True
    assert recorder.named()[:2] == ["set_tracking_uri", "start_run"]
    assert recorder.only("end_run") == ((), {"status": "FINISHED"})


def test_an_import_error_leaves_the_run_untracked_and_entered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The `track` extra not installed is the commonest unreachable MLflow.

    This is the path the spine itself takes: ADR 0023 keeps mlflow out of the
    required dependencies, so a set-but-unusable variable on a plain install
    lands exactly here.

    No recorder: the blocker empties `sys.modules`, so there is no stub to
    assert against and a `recorder.calls == []` here could not fail. The
    `pytest.warns` and the unraised `exercise` are what carry the test.
    """
    block_mlflow(monkeypatch)
    enable(monkeypatch)
    with pytest.warns(RuntimeWarning, match="mlflow could not be imported"):
        with tracked_run("fit", provenance=a_provenance()) as run:
            assert run.enabled is False
            exercise(run, tmp_path)
    assert "mlflow" not in sys.modules


@pytest.mark.parametrize(
    "error",
    [
        TypeError("bases must be types"),
        RuntimeError("module compiled against a different NumPy ABI"),
        OSError("cannot load library libstdc++"),
    ],
    ids=["TypeError", "RuntimeError", "OSError"],
)
def test_a_half_installed_extra_leaves_the_run_untracked_and_entered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: BaseException
) -> None:
    """`ImportError` is not the only way an import fails.

    A half-installed `track` extra -- the classic protobuf or NumPy ABI mismatch
    under mlflow's transitive stack -- raises out of a module body with whatever
    type that body raised. Catching only `ImportError` would let it propagate
    and break the research run, against this module's whole premise.
    """
    block_mlflow(monkeypatch, error)
    enable(monkeypatch)
    with pytest.warns(RuntimeWarning, match="mlflow could not be imported"):
        with tracked_run("fit", provenance=a_provenance()) as run:
            assert run.enabled is False
            exercise(run, tmp_path)


def test_a_logging_call_that_fails_warns_and_the_run_continues(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """One rejected metric must not switch tracking off for the rest.

    The `log_params` assertion is the one that matters: a wrapper that disabled
    the handle on first failure would pass a "the call did not raise" test and
    silently lose every metric after the first.
    """
    install(monkeypatch, recorder, failing=frozenset({"log_metrics"}))
    enable(monkeypatch)
    with tracked_run("fit", provenance=a_provenance()) as run:
        with pytest.warns(RuntimeWarning, match="mlflow log_metrics failed"):
            run.log_metrics({"auc": 0.5})
        assert run.enabled is True, "a failed call must not disable the handle"
        run.log_params({"lr": "1e-3"})
    assert recorder.named()[-3:] == ["log_metrics", "log_params", "end_run"]
    assert run.enabled is False, "the handle is closed once the `with` is left"


def test_a_failing_call_does_not_warn_when_tracking_is_off(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """The twin: with the variable unset there is nothing to fail and no noise.

    `filterwarnings = ["error"]` is what enforces it -- a warning raised here
    fails the test rather than being counted.
    """
    install(monkeypatch, recorder, failing=frozenset(SINK_CALLS))
    with tracked_run("fit", provenance=a_provenance()) as run:
        run.log_metrics({"auc": 0.5})
    assert recorder.calls == []


def test_a_failure_to_close_the_run_warns_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """The server going away mid-run must not turn a finished run into a crash."""
    install(monkeypatch, recorder, failing=frozenset({"end_run"}))
    enable(monkeypatch)
    with pytest.warns(RuntimeWarning, match="could not close the run"):
        with tracked_run("fit", provenance=a_provenance()) as run:
            run.log_params({"lr": "1e-3"})
    assert recorder.named()[-1] == "end_run"


def test_an_exception_from_the_body_fails_the_run_and_propagates(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """Only *tracking* failures are swallowed. The experiment's are the
    experiment's."""
    install(monkeypatch, recorder)
    enable(monkeypatch)
    with pytest.raises(ZeroDivisionError):
        with tracked_run("fit", provenance=a_provenance()):
            raise ZeroDivisionError("the experiment blew up")
    assert recorder.only("end_run") == ((), {"status": "FAILED"})


def test_an_exception_from_the_body_propagates_when_tracking_is_off(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """The twin: the no-op path must not swallow the body's exception either."""
    install(monkeypatch, recorder)
    with pytest.raises(ZeroDivisionError):
        with tracked_run("fit", provenance=a_provenance()):
            raise ZeroDivisionError("the experiment blew up")
    assert recorder.calls == []


# --------------------------------------------------------------------------
# Contract 3: the provenance class is logged as a tag.
# --------------------------------------------------------------------------


def test_provenance_class_is_logged_as_a_tag(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """Design section 11's gate: a run appears in MLflow with its class."""
    install(monkeypatch, recorder)
    enable(monkeypatch)
    with tracked_run("fit", provenance=a_provenance("run-0042")):
        pass
    assert recorder.tags() == {
        track.TAG_RUN_ID: "run-0042",
        track.TAG_RUN_CLASS: "deterministic",
        track.TAG_CONFIG_HASH: CONFIG_HASH,
        track.TAG_DATA_HASH: DATA_HASH,
        track.TAG_DEPS_HASH: DEPS_HASH,
        track.TAG_CODE_SHA: CODE_SHA,
    }


def test_a_provenance_only_record_is_tagged_provenance_only(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """The class comes off the record. A constant would pass the test above.

    This is the test a hardcoded `"deterministic"` fails, and nothing else
    catches it: the deterministic record is the one every other test here uses.
    """
    install(monkeypatch, recorder)
    enable(monkeypatch)
    with tracked_run("fit", provenance=a_provenance(run_class="provenance-only")):
        pass
    assert recorder.tags()[track.TAG_RUN_CLASS] == "provenance-only"


def test_a_null_member_is_omitted_rather_than_tagged_as_the_string_none(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """A `provenance-only` run has no code or deps hash (spec 7.3).

    `"None"` as a tag value is the plausible wrong value: a reviewer filtering
    on `heph.code_sha` would find one and read it as a commit.
    """
    install(monkeypatch, recorder)
    enable(monkeypatch)
    with tracked_run("fit", provenance=a_provenance(run_class="provenance-only")):
        pass
    tags = recorder.tags()
    assert track.TAG_CODE_SHA not in tags
    assert track.TAG_DEPS_HASH not in tags
    assert "None" not in tags.values()


def test_provenance_tags_is_a_pure_reading_of_the_record() -> None:
    """The mapping, with no MLflow in sight -- the unit a reviewer can check."""
    assert track.provenance_tags(a_provenance("run-9")) == {
        track.TAG_RUN_ID: "run-9",
        track.TAG_RUN_CLASS: "deterministic",
        track.TAG_CONFIG_HASH: CONFIG_HASH,
        track.TAG_DATA_HASH: DATA_HASH,
        track.TAG_DEPS_HASH: DEPS_HASH,
        track.TAG_CODE_SHA: CODE_SHA,
    }


def test_the_environment_is_not_tagged() -> None:
    """Spec 7.2 forbids comparing it, so the record is its home, not a tag."""
    tags = track.provenance_tags(a_provenance())
    assert not [name for name in tags if "platform" in name or "python" in name]
    assert "linux-x86_64" not in tags.values()


def test_a_callers_tag_cannot_displace_a_provenance_tag(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """The class a reviewer reads is the record's, not the caller's."""
    install(monkeypatch, recorder)
    enable(monkeypatch)
    with tracked_run(
        "fit",
        provenance=a_provenance(),
        tags={track.TAG_RUN_CLASS: "a lie", "owner": "lab"},
    ):
        pass
    tags = recorder.tags()
    assert tags[track.TAG_RUN_CLASS] == "deterministic"
    assert tags["owner"] == "lab", "the caller's other tags still arrive"


def test_no_tag_is_set_when_tracking_is_off(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """The no-op twin of the tagging contract: entry tags nothing when off."""
    install(monkeypatch, recorder)
    with tracked_run("fit", provenance=a_provenance(), tags={"owner": "lab"}):
        pass
    assert recorder.args("set_tags") == []


# --------------------------------------------------------------------------
# Contract 4: importing the module does not require mlflow.
# --------------------------------------------------------------------------


#: Installs a counting meta-path finder for mlflow BEFORE importing
#: `hephkit.lab.track`, then reports what the import attempted. The finder is
#: what makes this total: it records the *attempt*, so it catches a plain
#: `import mlflow`, an `importlib.import_module("mlflow")` (a `Call`, which no
#: AST import scan sees), and a module-scope call of a function that imports --
#: and it does so whether or not the `track` extra is installed, because a
#: `sys.modules` check alone comes up clean when the import simply fails.
_IMPORT_PROBE = """
import json, sys

attempted = []


class Finder:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "mlflow":
            attempted.append(name)
        return None


sys.meta_path.insert(0, Finder())
import hephkit.lab.track

print(json.dumps({"attempted": attempted, "loaded": "mlflow" in sys.modules}))
"""


def test_import_does_not_require_mlflow() -> None:
    """Importing `lab.track` must not reach mlflow at all, by any route.

    A subprocess rather than this session, which has a stub in `sys.modules`
    and has already imported half the package.
    """
    done = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
        [sys.executable, "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, f"importing hephkit.lab.track failed:\n{done.stderr}"
    assert json.loads(done.stdout) == {"attempted": [], "loaded": False}


def test_the_import_probe_sees_an_import_it_should_catch() -> None:
    """The probe biting, demonstrated rather than assumed.

    The probe is only worth anything if its finder really records an attempt, so
    the same program is run with one line added that imports mlflow by the route
    an AST scan cannot see.
    """
    program = _IMPORT_PROBE.replace(
        "import hephkit.lab.track",
        "import contextlib, importlib\n"
        "with contextlib.suppress(Exception):\n"
        "    importlib.import_module('mlflow')\n"
        "import hephkit.lab.track",
    )
    done = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["attempted"] == ["mlflow"]


def imports_outside_a_function(source: str) -> list[str]:
    """Every module imported anywhere except inside a function body.

    The whole tree, not `tree.body`. The realistic defect is not a bare
    top-level `import mlflow` -- that would break the spine outright -- but a
    module-scope ``try: import mlflow`` / ``except ImportError: mlflow = None``,
    whose `Import` node is nested inside a `Try` and so never appears in
    `tree.body`. On a machine without the extra it also leaves `sys.modules`
    clean, so the subprocess check above would pass against it too. This is the
    check that would not.
    """
    tree = ast.parse(source)
    inside = {
        id(child)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for child in ast.walk(node)
        if isinstance(child, (ast.Import, ast.ImportFrom))
    }
    found: list[str] = []
    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
    return found


def test_the_module_imports_mlflow_only_inside_a_function() -> None:
    """A static second opinion, kept for the error message it gives.

    The subprocess probe above is the total check -- it catches shapes this scan
    cannot see, and this scan flags shapes that are legal at run time. What this
    one adds is a failure that names the import, rather than a boolean out of
    another interpreter.
    """
    found = imports_outside_a_function(MODULE.read_text(encoding="utf-8"))
    assert not [name for name in found if name.split(".")[0] == "mlflow"], found
    # Non-vacuous: the scan does find the module-scope imports there are.
    assert {"os", "warnings", "hephkit.lab.repro"} <= set(found), found


def test_the_scan_catches_a_module_scope_import_of_mlflow() -> None:
    """The check above biting, demonstrated rather than assumed."""
    assert imports_outside_a_function("import mlflow\n") == ["mlflow"]
    assert imports_outside_a_function("from mlflow import log_metrics\n") == ["mlflow"]
    # The form that a `tree.body`-only scan misses.
    guarded = "try:\n    import mlflow\nexcept ImportError:\n    mlflow = None\n"
    assert imports_outside_a_function(guarded) == ["mlflow"]
    # And the form the module actually uses, which is allowed.
    assert imports_outside_a_function("def f():\n    import mlflow\n") == []
    assert imports_outside_a_function(
        "def f():\n    try:\n        import mlflow\n    except ImportError:\n        pass\n"
    ) == []


def test_mlflow_is_imported_when_and_only_when_a_run_is_tracked(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """The positive twin: the lazy import is wired, not merely absent.

    The stub is supplied through the real import machinery rather than through
    `sys.modules`, so the finder records the moment the import statement runs.
    That distinguishes "imported at use" from "already imported", which a
    `sys.modules` entry cannot.
    """
    finder = _CountingFinder(fake_mlflow(recorder))
    monkeypatch.delitem(sys.modules, "mlflow", raising=False)
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    enable(monkeypatch)
    assert finder.imported == [], "nothing may import mlflow before a run starts"
    with tracked_run("fit", provenance=a_provenance()) as run:
        assert run.enabled is True
    assert finder.imported == ["mlflow"]
    assert recorder.named()[:2] == ["set_tracking_uri", "start_run"]


def test_nothing_imports_mlflow_when_tracking_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The no-op twin: with the variable unset, the import is not even attempted.

    Blocking mlflow on the meta path proves it rather than asserting it -- an
    eager import would raise the blocker's `ImportError` here, and a lazy one
    that ignored the variable would warn, which `filterwarnings = ["error"]`
    turns into a failure.
    """
    block_mlflow(monkeypatch)
    assert is_enabled() is False
    with tracked_run("fit", provenance=a_provenance()) as run:
        assert run.enabled is False
    assert "mlflow" not in sys.modules


def test_is_enabled_imports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The probe exists so a caller can skip expensive work; it must be cheap.

    With the variable set and mlflow blocked, a probe that imported mlflow to
    decide would raise here instead of answering.
    """
    block_mlflow(monkeypatch)
    enable(monkeypatch)
    assert is_enabled() is True
    assert "mlflow" not in sys.modules


# --------------------------------------------------------------------------
# The decisions recorded in the module docstring.
# --------------------------------------------------------------------------


def test_the_module_defines_no_exception_class_and_raises_nothing_of_its_own() -> None:
    """`lab.track` raises nothing of its own, so it declares nothing.

    The asymmetry with `lab.record`, which raises `RecordError` because a record
    that cannot be written is a failed run. An exception class here would have
    no site that could raise it, and an unused one sends the next reader hunting
    for the path that throws it.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    # The whole tree, not `tree.body`: a class defined inside a `try` or an `if`
    # is still a class this module defines, and a `tree.body` scan would miss
    # it -- the same shape hole that let a guarded module-scope import through.
    classes = sorted(
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    )
    assert classes == ["TrackedRun", "_Started"], classes
    raised = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise) and node.exc is not None
    ]
    assert raised == [], f"lab.track raises at lines {raised}"
    # Non-vacuous: there IS a `raise` in the module -- the bare re-raise that
    # lets the experiment's own exception out of the context manager.
    bare = [node for node in ast.walk(tree) if isinstance(node, ast.Raise)]
    assert len(bare) == 1


def test_the_module_docstring_states_the_asymmetry_with_lab_record() -> None:
    """It looks inconsistent without the reason, and the reason is the design."""
    doc = track.__doc__ or ""
    assert "lab.record" in doc
    assert doc.rstrip().endswith("Maturity: experimental.")


def test_a_disabled_handle_can_be_built_directly() -> None:
    """The documented way to obtain a no-op handle: the default arguments."""
    run = TrackedRun()
    assert run.enabled is False
    assert run.run_id is None
    run.log_metrics({"auc": 1.0})
