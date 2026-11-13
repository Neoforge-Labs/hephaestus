"""MLflow tracking that no-ops cleanly when it is not configured.

``MLFLOW_TRACKING_URI`` is the only knob this module has, and **it has no
default**. Unset (or empty, or whitespace) means tracking is off -- not tracking
against ``localhost``. :func:`is_enabled` is the cheap probe that says which it
is, so a caller can skip preparing an expensive artifact that nothing would
receive::

    if track.is_enabled():
        figure = render_expensive_figure(rows)

Everything else lives behind :func:`tracked_run`, which always enters::

    with track.tracked_run("fit-v3", provenance=provenance) as run:
        run.log_params({"lr": 3e-4})
        run.log_metrics({"auc": 0.91}, step=epoch)
        run.log_dict(provenance.as_document(), "provenance.json")
        run.log_artifact(record.path / "summary.json")

**Why this module swallows and `lab.record` raises.** The asymmetry is
deliberate and it is the whole design. A record that cannot be written is a
failed run: there is no result without a record (ADR 0022), so
:mod:`hephkit.lab.record` raises. A metric that cannot be logged is *not* a
failed run: the record still holds it, the result still exists, and all that is
lost is a view onto it. So every call here catches its exception and warns. A
tracking server that is missing, unreachable, misconfigured or simply not
installed must never break a research run -- and a reviewer sees the drop as a
``RuntimeWarning`` on stderr rather than as a stack trace in place of a result.
This is the biggest reason tracking gets shelved: a library that can fail a run
gets removed from the run. This one cannot.

The consequences of that, stated rather than discovered:

* The context manager enters even when there is no reachable MLflow. The body
  runs, :attr:`TrackedRun.enabled` is then false, and every logging call is a
  silent no-op -- the single warning raised at entry already said tracking is
  off, and repeating it per metric would be noise.
* An individual call that fails warns and leaves the rest of the run tracked:
  one rejected metric does not switch tracking off for the ones after it.
* A run MLflow refuses to start is left alone rather than cleaned up, because
  "already active" is one of the reasons it refuses and the active run is then
  somebody else's (see :func:`_start`). A nested run that cannot start is
  untracked; the run around it is untouched.
* Warnings use the standard once-per-unique-message filter, so a call that
  fails identically every epoch is reported once. Pass ``-W always`` (or
  ``PYTHONWARNINGS=always``) to see each occurrence. Under ``-W error``, which
  some CI sets globally, this module's defining property **inverts**: every
  swallowed failure becomes a raised ``RuntimeWarning`` and a missing tracking
  server does fail the run. Do not set it for a research run; filter
  ``RuntimeWarning`` back to ``always`` if the rest of the suite needs it.

``mlflow`` is imported lazily, inside the call :func:`tracked_run` starts a run
with, and only when the variable is set. It is never imported at module scope:
it belongs to the ``track`` extra, the spine's required dependencies are
``hephkit`` and pydantic (ADR 0023), and ``tests/test_package.py`` fails if
importing ``hephkit.lab`` reaches any heavy stack.

**Tags.** The six scalar members of a :class:`~hephkit.lab.repro.ProvenanceRecord`
go on the run as tags, read off the record rather than recomputed, which is how
a reviewer finds a run's class in the MLflow UI (the design's section 11 gate
requires a run to appear there with its provenance class). ``environment`` is
not tagged: it is nested, and spec 7.2 forbids a replay from comparing it, so
the record -- or an explicit :meth:`TrackedRun.log_dict` of
``provenance.as_document()`` -- is its home. A caller's own tags are applied
too, but cannot displace a provenance tag: the class a reviewer reads is the
record's.

**No exception class.** This module defines none, and raises none of its own.
Its entire purpose is that it does not fail a run, so an exception type here
would have no site that could raise it. An exception the module never raises is
worse than no exception at all: the next reader would hunt for the path that
throws it.

Nothing in this module does relational or money work, so nothing here needs a
registry error code either; a dropped metric is a warning, not a `HEPH-` code.

Maturity: experimental.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Final, NamedTuple

from hephkit.lab.repro import ProvenanceRecord

__all__ = [
    "TAG_CODE_SHA",
    "TAG_CONFIG_HASH",
    "TAG_DATA_HASH",
    "TAG_DEPS_HASH",
    "TAG_RUN_CLASS",
    "TAG_RUN_ID",
    "TRACKING_URI_VARIABLE",
    "TrackedRun",
    "is_enabled",
    "provenance_tags",
    "tracked_run",
    "tracking_uri",
]

#: The one knob. No default: unset means tracking is off (see the module
#: docstring). MLflow's own variables -- `MLFLOW_EXPERIMENT_NAME` and the rest
#: -- are read by mlflow itself; this module adds none of its own.
TRACKING_URI_VARIABLE: Final = "MLFLOW_TRACKING_URI"

#: Tag names for the six scalar members of spec 7.1. Prefixed rather than bare
#: because MLflow's own tags live under `mlflow.`, and an unprefixed `run_id`
#: would read like one of them.
TAG_RUN_ID: Final = "heph.run_id"
TAG_RUN_CLASS: Final = "heph.run_class"
TAG_CONFIG_HASH: Final = "heph.config_hash"
TAG_DATA_HASH: Final = "heph.data_hash"
TAG_DEPS_HASH: Final = "heph.deps_hash"
TAG_CODE_SHA: Final = "heph.code_sha"

#: MLflow run statuses. Spelled rather than imported from `mlflow.entities`,
#: which would be a module-scope dependency on the extra.
_FINISHED: Final = "FINISHED"
_FAILED: Final = "FAILED"

#: `stacklevel` for a warning raised from :meth:`TrackedRun._attempt`:
#: `_attempt` -> the public method -> the caller. Exact for a call the caller
#: makes itself, which is every call that can report a dropped metric.
_CALL_STACKLEVEL: Final = 3

#: `stacklevel` for a warning about the run itself: the raising frame -> the
#: :func:`tracked_run` generator -> `contextmanager.__enter__`/`__exit__` ->
#: the caller's `with` statement.
_MANAGER_STACKLEVEL: Final = 4


def tracking_uri() -> str | None:
    """The configured tracking URI, or `None` when there is none.

    Whitespace is stripped and an empty value is `None`, so a variable exported
    as ``MLFLOW_TRACKING_URI=`` -- which is how CI usually unsets one -- means
    off rather than "track against the empty string".
    """
    return os.environ.get(TRACKING_URI_VARIABLE, "").strip() or None


def is_enabled() -> bool:
    """Whether tracking is configured at all.

    A cheap probe, by design: it reads one environment variable and imports
    nothing, so a caller can guard expensive artifact preparation with it
    without paying for mlflow to decide.
    """
    return tracking_uri() is not None


def provenance_tags(provenance: ProvenanceRecord) -> dict[str, str]:
    """The record's six scalar members as MLflow tags.

    A member that is `None` is omitted rather than tagged. A `provenance-only`
    run has no `code_sha` and no `deps_hash` (spec 7.3), and a tag reading
    ``"None"`` is exactly the plausible wrong value this kit exists to refuse:
    absent says absent.

    `environment` is not here -- see the module docstring.
    """
    members: dict[str, str | None] = {
        TAG_RUN_ID: provenance.run_id,
        TAG_RUN_CLASS: provenance.run_class,
        TAG_CONFIG_HASH: provenance.config_hash,
        TAG_DATA_HASH: provenance.data_hash,
        TAG_DEPS_HASH: provenance.deps_hash,
        TAG_CODE_SHA: provenance.code_sha,
    }
    return {name: value for name, value in members.items() if value is not None}


class _Started(NamedTuple):
    """A live MLflow run: the fluent module, and the id it assigned."""

    sink: Any
    run_id: str


def _start(name: str) -> _Started | None:
    """Begin an MLflow run, or warn and return `None`.

    Every failure mode lands on `None`: the variable is unset, mlflow could not
    be imported, or the server refused. The caller cannot tell them apart and
    does not need to -- all three mean "this run is not tracked".

    **Nothing already running is touched here.** The two failures are kept in
    separate blocks because they have opposite cleanups: a `start_run` that
    raised started nothing, while a `start_run` that succeeded leaves a run
    active in mlflow's process-global state that only this call can close. See
    the second block's comment for what conflating them would do.
    """
    uri = tracking_uri()
    if uri is None:
        return None
    try:
        import mlflow
    # Not `ImportError`: a half-installed `track` extra -- the classic protobuf
    # or NumPy ABI mismatch somewhere under mlflow's transitive stack -- raises
    # `TypeError`, `RuntimeError` or `OSError` out of a module body instead, and
    # a broken install is no more a failed run than a missing one.
    except Exception as exc:  # noqa: BLE001 - see above
        warnings.warn(
            f"{TRACKING_URI_VARIABLE} is set but mlflow could not be imported, so "
            f"the run {name!r} is not tracked; install the `track` extra "
            f"(hephkit-lab[track]) or unset the variable: {exc!r}",
            RuntimeWarning,
            stacklevel=_MANAGER_STACKLEVEL,
        )
        return None
    try:
        mlflow.set_tracking_uri(uri)
        active = mlflow.start_run(run_name=name)
    except Exception as exc:  # noqa: BLE001 - an unreachable server is not a failed run
        # No `end_run` here, deliberately. A refused `start_run` can mean
        # another run is already active -- mlflow raises "Run with UUID ... is
        # already active", which is what an inner per-fold or per-trial
        # `tracked_run` gets -- and ending it would mark somebody ELSE's run
        # FAILED and split its remaining metrics into a fresh run, because
        # mlflow's fluent calls go through `_get_or_start_run()`. A module whose
        # premise is that it cannot corrupt a run must not do that; an untracked
        # inner run is the correct outcome.
        warnings.warn(
            f"the run {name!r} could not be started against {TRACKING_URI_VARIABLE} "
            f"{uri!r}, so it is not tracked; the run itself continues: {exc!r}",
            RuntimeWarning,
            stacklevel=_MANAGER_STACKLEVEL,
        )
        return None
    try:
        return _Started(mlflow, str(active.info.run_id))
    except Exception as exc:  # noqa: BLE001 - see above
        # This one IS ours: the run started, so left active it would refuse the
        # next one. Closing it is the only cleanup in this function, and it is
        # reachable only on the one path where the run being closed is the run
        # this call just created.
        with suppress(Exception):
            mlflow.end_run(status=_FAILED)
        warnings.warn(
            f"the run {name!r} started against {TRACKING_URI_VARIABLE} {uri!r} but "
            f"its id could not be read, so it is not tracked and has been closed; "
            f"the run itself continues: {exc!r}",
            RuntimeWarning,
            stacklevel=_MANAGER_STACKLEVEL,
        )
        return None


class TrackedRun:
    """One run's handle. Every method is best-effort and none of them raise.

    Built by :func:`tracked_run`; construct one directly only to obtain a
    disabled handle, which is what the default arguments give.
    """

    def __init__(self, sink: Any = None, run_id: str | None = None) -> None:
        self._sink = sink
        self._run_id = run_id

    @property
    def enabled(self) -> bool:
        """Whether this run is actually reaching MLflow.

        False when the variable was unset, and equally false when it was set and
        the server could not be reached: the body of the `with` ran either way.
        """
        return self._sink is not None

    @property
    def run_id(self) -> str | None:
        """The id MLflow assigned, or `None` when this run is not tracked.

        Not the record's `run_id`, which is on the run as :data:`TAG_RUN_ID`.
        """
        return self._run_id

    def log_params(self, params: Mapping[str, Any]) -> None:
        """Record the run's parameters."""
        self._attempt("log_params", lambda sink: sink.log_params(dict(params)))

    def log_metrics(self, metrics: Mapping[str, float], *, step: int | None = None) -> None:
        """Record measurements, optionally at a step."""
        self._attempt("log_metrics", lambda sink: sink.log_metrics(dict(metrics), step=step))

    def log_artifact(self, path: Path | str, *, artifact_path: str | None = None) -> None:
        """Upload a file. A missing or unreadable one warns; it does not raise."""
        self._attempt(
            "log_artifact",
            lambda sink: sink.log_artifact(str(path), artifact_path=artifact_path),
        )

    def log_dict(self, document: Mapping[str, Any], artifact_file: str) -> None:
        """Upload a mapping as a JSON (or YAML, by extension) artifact."""
        self._attempt("log_dict", lambda sink: sink.log_dict(dict(document), artifact_file))

    def set_tags(self, tags: Mapping[str, str]) -> None:
        """Tag the run."""
        self._attempt("set_tags", lambda sink: sink.set_tags(dict(tags)))

    def _attempt(self, what: str, call: Callable[[Any], object]) -> None:
        """Make one MLflow call, or warn and carry on.

        The handle is NOT disabled by a failure: the next call tries again, so
        one metric the server rejected does not silently drop the rest.
        """
        if self._sink is None:
            return
        try:
            call(self._sink)
        except Exception as exc:  # noqa: BLE001 - a dropped metric is not a failed run
            warnings.warn(
                f"mlflow {what} failed for run {self._run_id!r} and the data was "
                f"dropped; the run itself continues: {exc!r}",
                RuntimeWarning,
                stacklevel=_CALL_STACKLEVEL,
            )

    def _end(self, status: str) -> None:
        """Close the MLflow run, best-effort, and disable this handle."""
        sink, self._sink = self._sink, None
        if sink is None:
            return
        try:
            sink.end_run(status=status)
        except Exception as exc:  # noqa: BLE001 - see the module docstring
            warnings.warn(
                f"mlflow could not close the run {self._run_id!r} with status "
                f"{status}: {exc!r}",
                RuntimeWarning,
                stacklevel=_MANAGER_STACKLEVEL,
            )


@contextmanager
def tracked_run(
    name: str,
    *,
    provenance: ProvenanceRecord,
    tags: Mapping[str, str] | None = None,
) -> Iterator[TrackedRun]:
    """Enter a tracked run. Always enters; never raises on MLflow's behalf.

    `name` becomes the MLflow run name. `provenance` is tagged onto the run by
    :func:`provenance_tags` and is otherwise untouched -- nothing here captures
    or recomputes provenance, which is :mod:`hephkit.lab.repro`'s job. `tags`
    are the caller's own, applied first so that a provenance tag wins a
    collision.

    An exception from the body closes the MLflow run as ``FAILED`` and then
    propagates: the experiment's failures are the experiment's, and only
    *tracking* failures are swallowed here.
    """
    started = _start(name)
    tracked = (
        TrackedRun(started.sink, started.run_id) if started is not None else TrackedRun()
    )
    tracked.set_tags({**(tags or {}), **provenance_tags(provenance)})
    try:
        yield tracked
    except BaseException:
        tracked._end(_FAILED)
        raise
    else:
        tracked._end(_FINISHED)
