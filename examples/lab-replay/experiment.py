#!/usr/bin/env python
"""The fixture experiment behind the in-repo replay gate (design section 11).

The gate this backs is the whole of the lab stream's phase gate: a fixture
experiment records a run, replays it **with the network blocked** and matches, a
perturbed input produces a diff naming the value that moved, and every
``lab.gates`` check refuses a violating fixture. `gate_test.sh` is the gate; this
module is the subject it runs, and every assertion lives in that script so a
failure says which claim broke.

Three properties are deliberate and each one is load-bearing:

* **The frozen input is synthetic and this file generates it.** Nothing
  third-party is redistributed, and the perturbed variant is produced the same
  way, so "the input changed" is one number in a file this module wrote rather
  than a second dataset nobody can audit.
* **No I/O the network could serve.** The arithmetic is the standard library's,
  the data comes off the disk, and the gate runs under
  :func:`block_network`, which is self-tested rather than assumed: a block that
  silently stopped blocking would make "replayed with the network blocked" a
  claim nothing checks.
* **Determinism is earned, not asserted.** The bootstrap in the ``evaluate``
  cell draws from the global :mod:`random` after :func:`seed_everything`, so a
  replay that skipped the seeding diverges. The gate would then fail, which is
  the point: a fixture whose replay matches however it is run proves nothing
  about replay.

The experiment takes the open record and nothing else (spec 8.6). Its config and
its frozen input reach it through this module, which is the only way they can:
the signature has no room for a destination, and that is what makes the record
the only place a number can land.

Run `python experiment.py --help` for the steps `gate_test.sh` drives.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import socket
import statistics
import sys
import urllib.request
from pathlib import Path
from typing import Any, Final

from hephkit.errors import REGISTRY
from hephkit.hashing import canonical_json, content_hash
from hephkit.lab.config import ExperimentConfig, config_hash, resolve
from hephkit.lab.gates import (
    GateError,
    check_all,
    check_cited_runs,
    check_records_wellformed,
    find_hardcoded_metrics,
)
from hephkit.lab.record import PROVENANCE_NAME, ROWS_NAME, RunRecord, read_record, register, run
from hephkit.lab.replay import DiffReport, replay
from hephkit.lab.repro import ProvenanceRecord, capture, seed_everything

#: The name the fixture registers under (spec 8.6). `replay` is given this name,
#: because a record does not name the experiment that produced it.
EXPERIMENT: Final = "lab-replay-fixture"

#: The baseline run's id, which is also the name of its record directory: the
#: citations gate resolves `run:<id>` to `<records>/<id>`.
BASELINE_RUN: Final = "fixture-baseline"

#: This repository's root, two levels up from `examples/lab-replay/`. `capture`
#: resolves `HEAD` here, and the lockfile it hashes is the lab distribution's --
#: the repository root has none, and a `deps_hash` of `null` would make every
#: run `provenance-only` for a reason that is about this example's layout rather
#: than about the run.
REPO: Final = Path(__file__).resolve().parents[2]
LOCKFILE: Final = REPO / "python" / "hephkit-lab" / "uv.lock"

#: How much the perturbed variant moves one held-out observation. Large enough
#: that the metrics move well past 9.3's float tolerance, so the divergence is
#: the perturbation rather than arithmetic noise.
PERTURBATION: Final = 0.75


class FixtureConfig(ExperimentConfig):
    """The fixture's config: a seed, a shape and the line the data is drawn from.

    Frozen and closed to extras, from :class:`ExperimentConfig`. The gate
    resolves it from a file layer it writes, so `config_hash` covers a document
    on disk a reader can look at rather than a dict in this file.
    """

    seed: int = 20261112
    points: int = 64
    holdout: int = 16
    bootstrap: int = 48
    slope: float = 2.5
    intercept: float = -1.25
    spread: float = 0.5


class NetworkBlocked(RuntimeError):
    """An outbound connection was attempted while the gate's block was in force."""


def block_network() -> None:
    """Refuse every outbound connection this process can make.

    In-process rather than by container or namespace, for one reason: the gate
    must run on every pull request and on a developer's machine, which rules out
    Docker and rules out `unshare`, which does not exist on macOS. What this
    reaches is every path a Python client takes to a socket -- name resolution,
    :func:`socket.create_connection`, and `connect` on the socket class itself,
    which is what :mod:`urllib` and `urllib3` end up calling.

    It is not a sandbox: a subprocess is unaffected, and so is anything holding
    a reference to the real functions from before this call. It is installed
    after every import for exactly that reason. The claim it supports is
    narrow and it is checked rather than trusted -- :func:`self_test_block` is
    what makes "the network was blocked" falsifiable.
    """

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise NetworkBlocked(
            "the replay gate blocks the network: a replay that reaches off the "
            "machine is reading something its record does not name "
            f"(attempted {args!r})"
        )

    socket.getaddrinfo = refuse
    socket.gethostbyname = refuse
    socket.create_connection = refuse
    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.socket.sendto = refuse


def self_test_block() -> list[str]:
    """Probe the block and return one line per path proved to be refused.

    Four paths, because a block that stopped one of them would leave a replay
    able to reach the network while the gate still said it could not: DNS, the
    connection helper, `connect` on a socket this process makes itself, and the
    URL fetch a tracking client performs. A probe that does **not** raise
    :class:`NetworkBlocked` is reported as a failure by the caller.
    """
    proved: list[str] = []

    def probe(name: str, call: Any) -> None:
        try:
            call()
        except NetworkBlocked:
            proved.append(name)
        except Exception as exc:  # noqa: BLE001 - any other outcome is a failed block
            print(f"      {name}: NOT blocked, raised {exc!r} instead", file=sys.stderr)
        else:
            print(f"      {name}: NOT blocked, the call returned", file=sys.stderr)

    # 54999 is deliberately a port nothing in the 54xxx block allocates. The
    # probe only has to reach the blocking layer, never a server, and pointing
    # it at a port we do own -- MLflow's 54500, say -- would couple this
    # self-test to whether that service happens to be up and read as though the
    # block were being tested against it.
    probe("getaddrinfo", lambda: socket.getaddrinfo("localhost", 80))
    probe("create_connection", lambda: socket.create_connection(("127.0.0.1", 54999), 1))
    probe("socket.connect", lambda: socket.socket().connect(("127.0.0.1", 54999)))
    probe(
        "urlopen",
        lambda: urllib.request.urlopen("http://127.0.0.1:54999/health", timeout=1),
    )
    return proved


# --- the frozen input --------------------------------------------------------


def synthesise(cfg: FixtureConfig) -> dict[str, list[float]]:
    """The fixture's own synthetic dataset: a noisy line, from the config's seed.

    Drawn with a :class:`random.Random` of its own rather than the global
    generator, so freezing the input and running the experiment cannot interfere
    with each other's draws. Values are rounded to twelve decimals, which every
    IEEE double round-trips exactly, so the file on disk and the numbers the
    experiment reads are the same numbers.
    """
    rng = random.Random(cfg.seed)
    xs: list[float] = []
    ys: list[float] = []
    for index in range(cfg.points):
        x = index / cfg.points
        y = cfg.slope * x + cfg.intercept + cfg.spread * rng.uniform(-1.0, 1.0)
        xs.append(round(x, 12))
        ys.append(round(y, 12))
    return {"x": xs, "y": ys}


def perturbed(cfg: FixtureConfig, dataset: dict[str, list[float]]) -> tuple[dict[str, list[float]], int]:
    """`dataset` with one held-out observation moved, and the index that moved.

    The first held-out point, so the ``fit`` cell reads exactly the same
    training split in both runs. That is what makes the diff the gate asserts on
    a *targeted* one: the metrics of ``evaluate`` move, the parameters of ``fit``
    do not, and a report that named both would mean the perturbation leaked.
    """
    index = cfg.points - cfg.holdout
    moved = dict(dataset)
    ys = list(dataset["y"])
    ys[index] = round(ys[index] + PERTURBATION, 12)
    moved["y"] = ys
    return moved, index


def write_json(path: Path, document: Any) -> str:
    """Write `document` as canonical JSON (spec 4.1) and return its content hash.

    Canonical rather than pretty: the frozen input's hash is a member of the
    provenance record, so the bytes on disk have to be the bytes that were
    hashed, and 4.1's form is the one every implementation agrees on.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(document) + "\n", encoding="utf-8")
    return content_hash(document)


# --- the experiment ----------------------------------------------------------

#: What the runner loaded for this process. An experiment takes the open record
#: and nothing else (8.6), so the config and the frozen input reach it here.
_CONFIG: FixtureConfig | None = None
_DATA: dict[str, list[float]] | None = None


def load(cfg: FixtureConfig, dataset: dict[str, list[float]]) -> None:
    """Put the config and the frozen input where the experiment will read them."""
    global _CONFIG, _DATA
    _CONFIG, _DATA = cfg, dataset


def _loaded() -> tuple[FixtureConfig, dict[str, list[float]]]:
    if _CONFIG is None or _DATA is None:  # pragma: no cover - the CLI always loads
        raise RuntimeError("the runner must call load() before running the experiment")
    return _CONFIG, _DATA


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Ordinary least squares, closed form: no iteration, so no tolerance to tune."""
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys, strict=True))
    denominator = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / denominator
    return slope, (sy - slope * sx) / n


def _residuals(xs: list[float], ys: list[float], slope: float, intercept: float) -> list[float]:
    return [y - (slope * x + intercept) for x, y in zip(xs, ys, strict=True)]


def _rmse(residuals: list[float]) -> float:
    return math.sqrt(sum(r * r for r in residuals) / len(residuals))


@register(EXPERIMENT)
def fixture(record: RunRecord) -> None:
    """Two cells over the frozen input: fit the line, then score the holdout.

    The seeding is the first thing that happens and it matters: the standard
    error in ``evaluate`` is a bootstrap over the global generator, so a replay
    that did not seed identically would diverge there and the gate would fail.
    """
    cfg, data = _loaded()
    seed_everything(cfg.seed)
    split = cfg.points - cfg.holdout
    train_x, train_y = data["x"][:split], data["y"][:split]
    test_x, test_y = data["x"][split:], data["y"][split:]

    slope, intercept = _fit(train_x, train_y)
    record.append_row(
        "fit",
        {
            "slope": slope,
            "intercept": intercept,
            "train_rmse": _rmse(_residuals(train_x, train_y, slope, intercept)),
        },
    )

    residuals = _residuals(test_x, test_y, slope, intercept)
    mean_y = sum(test_y) / len(test_y)
    total = sum((y - mean_y) ** 2 for y in test_y)
    resampled = [
        _rmse([residuals[random.randrange(len(residuals))] for _ in residuals])
        for _ in range(cfg.bootstrap)
    ]
    rmse = _rmse(residuals)
    mae = sum(abs(r) for r in residuals) / len(residuals)
    r2 = (total - sum(r * r for r in residuals)) / total
    record.append_row(
        "evaluate",
        {
            "rmse": rmse,
            "mae": mae,
            "r2": r2,
            "rmse_bootstrap_se": statistics.stdev(resampled),
            # A string value, because a row holds `float | str` (8.2) and a
            # replay compares the two kinds differently (9.3): the gate would
            # not otherwise exercise the string half of that comparison.
            "model": "ordinary-least-squares",
        },
    )


# --- the steps `gate_test.sh` drives -----------------------------------------


class Paths:
    """Where each step of the gate puts what it produces."""

    def __init__(self, work: Path) -> None:
        self.work = work
        self.config = work / "config.json"
        self.baseline_input = work / "inputs" / "baseline.json"
        self.perturbed_input = work / "inputs" / "perturbed.json"
        self.records = work / "records"
        self.replays = work / "replays"
        self.reports = work / "reports"
        self.gates = work / "gates"


def _config(paths: Paths) -> FixtureConfig:
    """The config, resolved from the file layer the freeze step wrote."""
    return resolve(FixtureConfig, file=paths.config)


def _provenance(run_id: str, cfg: FixtureConfig, data_hash: str) -> ProvenanceRecord:
    """The section 7 record of a run about to start, captured rather than invented."""
    return capture(
        run_id=run_id,
        config_hash=config_hash(cfg),
        data_hash=data_hash,
        repo=REPO,
        lockfile=LOCKFILE,
    )


def step_freeze(paths: Paths) -> int:
    """Write the config and the fixture's own synthetic frozen input."""
    cfg = FixtureConfig()
    paths.config.parent.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(canonical_json(cfg.model_dump(mode="json")) + "\n", encoding="utf-8")
    cfg = _config(paths)
    dataset = synthesise(cfg)
    baseline = write_json(paths.baseline_input, dataset)
    moved, index = perturbed(cfg, dataset)
    perturb_hash = write_json(paths.perturbed_input, moved)
    print(f"FROZEN baseline points={cfg.points} data_hash={baseline}")
    print(
        f"FROZEN perturbed index={index} delta={PERTURBATION!r} "
        f"data_hash={perturb_hash} differs={perturb_hash != baseline}"
    )
    return 0


def step_record(paths: Paths) -> int:
    """Run the fixture and record it. The record is the run; there is nowhere else."""
    cfg = _config(paths)
    dataset = json.loads(paths.baseline_input.read_text(encoding="utf-8"))
    load(cfg, dataset)
    provenance = _provenance(BASELINE_RUN, cfg, content_hash(dataset))
    record = run(EXPERIMENT, paths.records / BASELINE_RUN, provenance=provenance)
    read_back = read_record(record.path)
    cells = ",".join(row.cell for row in read_back.rows)
    print(
        f"RECORD run_id={read_back.provenance.run_id} class={read_back.provenance.run_class} "
        f"complete={'yes' if read_back.complete else 'no'} rows={len(read_back.rows)} cells={cells}"
    )
    for row in read_back.rows:
        for key, value in row.values.items():
            print(f"VALUE cell={row.cell} key={key} value={value!r}")
    return 0


def _replay_under_block(
    paths: Paths, *, dataset_path: Path, into: Path, run_id: str
) -> DiffReport:
    """Replay the baseline record against `dataset_path`, with the network blocked.

    Everything is imported and read before the block goes in, because the block
    is a monkey-patch and not a sandbox: it stops the calls a replay would make,
    not the import machinery it already finished with.
    """
    cfg = _config(paths)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    load(cfg, dataset)
    provenance = _provenance(run_id, cfg, content_hash(dataset))

    block_network()
    proved = self_test_block()
    print(f"BLOCK proved={','.join(proved)} count={len(proved)}")
    return replay(
        paths.records / BASELINE_RUN, experiment=EXPERIMENT, into=into, provenance=provenance
    )


def _report(label: str, report: DiffReport, paths: Paths) -> None:
    """Write the report and print one greppable line per position that moved."""
    paths.reports.mkdir(parents=True, exist_ok=True)
    (paths.reports / f"{label}.json").write_text(
        json.dumps(report.as_document(), indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"REPLAY {label} matched={'yes' if report.matched else 'no'} "
        f"differences={len(report.differences)} "
        f"record_unfinished={'yes' if report.record_unfinished else 'no'}"
    )
    for difference in report.differences:
        print(
            f"DIFF {label} cell={difference.cell or '-'} key={difference.key or '-'} "
            f"recorded={difference.recorded!r} replayed={difference.replayed!r}"
        )


def step_replay(paths: Paths) -> int:
    """Replay the recorded run from the same frozen input, network blocked."""
    report = _replay_under_block(
        paths,
        dataset_path=paths.baseline_input,
        into=paths.replays / "baseline",
        run_id=f"{BASELINE_RUN}-replay",
    )
    _report("baseline", report, paths)
    return 0


def step_perturb(paths: Paths) -> int:
    """Replay the recorded run from the perturbed input, network blocked."""
    report = _replay_under_block(
        paths,
        dataset_path=paths.perturbed_input,
        into=paths.replays / "perturbed",
        run_id=f"{BASELINE_RUN}-perturbed",
    )
    _report("perturbed", report, paths)
    return 0


# --- the gate fixtures -------------------------------------------------------

#: A figure script of the kind the audit `lab.gates` was harvested from found:
#: every number transcribed from a results table rather than read from a record.
#: Written out as text rather than committed, so this example ships no file that
#: reads like a real results table, and generated by the fixture for the same
#: reason the dataset is.
FIGURE_WITH_LITERALS: Final = '''\
"""Transcribed figure code. Generated by experiment.py; never imported."""

f1 = 0.474
final_accuracy: float = 0.912
table = {"rmse": 1.2048}
dice = [0.9412, 0.8893]
p_value = 0.031
'''

#: The same figure, drawn from a record instead. Every float literal here is
#: vetoed geometry -- an axis limit, an alpha, a bar width -- which is the
#: idiomatic spelling of the only code this gate reads. A gate that flagged
#: these is a gate a project switches off, so the clean side is asserted too.
FIGURE_CLEAN: Final = '''\
"""Figure code that reads its numbers from a record. Generated; never imported."""

from hephkit.lab.record import read_record

f1_ylim = 1.0
loss_alpha = 0.35
f1_bar_width = 0.8
score_pad = 0.05
f1_dpi = 144.0


def draw(directory):
    record = read_record(directory)
    return [row.values for row in record.rows]
'''


def _copy_record(source: Path, destination: Path) -> None:
    """Copy a record directory verbatim, including its summary."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in sorted(path.name for path in source.iterdir() if path.is_file()):
        (destination / name).write_bytes((source / name).read_bytes())


def _build_gate_fixtures(paths: Paths) -> dict[str, Path]:
    """Write every subject the gates run against: one clean, one violating each."""
    root = paths.gates
    figures = root / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    (figures / "transcribed.py").write_text(FIGURE_WITH_LITERALS, encoding="utf-8")
    clean_figures = root / "figures-clean"
    clean_figures.mkdir(parents=True, exist_ok=True)
    (clean_figures / "drawn.py").write_text(FIGURE_CLEAN, encoding="utf-8")

    good = paths.records / BASELINE_RUN
    clean_records = root / "records-clean"
    _copy_record(good, clean_records / BASELINE_RUN)

    broken_records = root / "records-broken"
    _copy_record(good, broken_records / BASELINE_RUN)
    # A record that says something its rows do not support: the same cell twice,
    # which spec 8.2 forbids and `read_record` refuses. Appended rather than
    # hand-written so the rest of the record stays the record of a real run.
    rows = broken_records / BASELINE_RUN / ROWS_NAME
    lines = rows.read_text(encoding="utf-8").splitlines(keepends=True)
    rows.write_text("".join(lines) + lines[0], encoding="utf-8")

    (root / "clean.md").write_text(
        f"The result is run:{BASELINE_RUN}, whose record is in this tree.\n",
        encoding="utf-8",
    )
    (root / "uncitable.md").write_text(
        "Table 1 reports run:fixture-never-ran, which no record names.\n",
        encoding="utf-8",
    )
    return {
        "figures": figures,
        "figures_clean": clean_figures,
        "records_clean": clean_records,
        "records_broken": broken_records,
        "clean_manuscript": root / "clean.md",
        "uncitable_manuscript": root / "uncitable.md",
    }


#: How many re-executions a gate step has started. Spec 8.3 forbids rewriting a
#: record, so every re-execution needs a destination of its own; a counter is
#: the simplest thing that gives one however many times a `replay_check` is
#: called.
_REPLAYS = 0


def _replay_check(paths: Paths, label: str, dataset_path: Path) -> Any:
    """A `replay_check` that replays each cited run from `dataset_path`.

    The citations gate's four checks are replayability; the reproduction itself
    is the project's, because a gate has nowhere honest to get the
    re-execution's provenance and a record does not name the experiment that
    produced it. This is that callable. Pointed at the perturbed input it is a
    run that does not reproduce; pointed at the baseline it is one that does,
    and the gate asserts both.
    """
    cfg = _config(paths)

    def check(run_id: str, directory: Path) -> DiffReport:
        global _REPLAYS
        _REPLAYS += 1
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        load(cfg, dataset)
        return replay(
            directory,
            experiment=EXPERIMENT,
            into=paths.replays / f"cited-{label}-{_REPLAYS}",
            provenance=_provenance(
                f"{run_id}-cited-{_REPLAYS}", cfg, content_hash(dataset)
            ),
        )

    return check


def _gate_line(name: str, violating: list[Any], clean: list[Any]) -> str:
    return f"GATE {name} violating={len(violating)} clean={len(clean)}"


def step_gates(paths: Paths) -> int:
    """Run every `lab.gates` check against a violating fixture and a clean one.

    Both sides, on purpose. "Fails on the violating fixture" alone is satisfied
    by a gate that fails on everything, which is as useless as one that fails on
    nothing; the pair is what pins the gate to the property it claims.
    """
    subject = _build_gate_fixtures(paths)
    lines: list[str] = []

    lines.append(
        _gate_line(
            "figures",
            find_hardcoded_metrics([subject["figures"]]),
            find_hardcoded_metrics([subject["figures_clean"]]),
        )
    )
    lines.append(
        _gate_line(
            "records",
            check_records_wellformed(subject["records_broken"]),
            check_records_wellformed(subject["records_clean"]),
        )
    )
    lines.append(
        _gate_line(
            "citations-missing",
            check_cited_runs(subject["uncitable_manuscript"], subject["records_clean"]),
            check_cited_runs(subject["clean_manuscript"], subject["records_clean"]),
        )
    )
    lines.append(
        _gate_line(
            "citations-replay",
            check_cited_runs(
                subject["clean_manuscript"],
                subject["records_clean"],
                replay_check=_replay_check(paths, "perturbed", paths.perturbed_input),
            ),
            check_cited_runs(
                subject["clean_manuscript"],
                subject["records_clean"],
                replay_check=_replay_check(paths, "baseline", paths.baseline_input),
            ),
        )
    )

    # `check_all` is the one call CI makes, and the only thing that refuses.
    try:
        check_all(
            figures=[subject["figures"]],
            records=subject["records_broken"],
            manuscript=subject["uncitable_manuscript"],
        )
    except GateError as exc:
        named = ",".join(sorted({violation.gate for violation in exc.violations}))
        # The code is resolved through the generated registry rather than
        # compared with the constant the exception already carries, which would
        # be a tautology: what is worth asserting is that the code a refusal
        # raises is a code `spec/errors.yaml` knows, with the status it gives.
        status, title = REGISTRY[exc.code]
        lines.append(
            f"GATE check-all refused=yes code={exc.code} status={status} "
            f"violations={len(exc.violations)} gates={named}"
        )
        lines.append(f"GATE check-all title={title}")
    else:
        lines.append("GATE check-all refused=no code=none status=0 violations=0 gates=")

    clean = check_all(
        figures=[subject["figures_clean"]],
        records=subject["records_clean"],
        manuscript=subject["clean_manuscript"],
        replay_check=_replay_check(paths, "baseline", paths.baseline_input),
    )
    lines.append(f"GATE check-all-clean refused=no violations={len(clean)}")

    # Being asked to check nothing is a refusal rather than a pass: a gate over
    # no subject is the one way a gate fails silently, which is the defect this
    # whole gate exists to make impossible.
    try:
        check_all()
    except ValueError as exc:
        lines.append(f"GATE check-all-nothing refused=yes kind={type(exc).__name__}")
    else:
        lines.append("GATE check-all-nothing refused=no kind=none")

    paths.reports.mkdir(parents=True, exist_ok=True)
    (paths.reports / "gates.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for line in lines:
        print(line)
    return 0


STEPS: Final = {
    "freeze": step_freeze,
    "record": step_record,
    "replay": step_replay,
    "perturb": step_perturb,
    "gates": step_gates,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument("step", choices=sorted(STEPS), help="the gate step to run")
    parser.add_argument(
        "--work", required=True, type=Path, help="the directory this gate run writes into"
    )
    args = parser.parse_args(argv)
    paths = Paths(args.work)
    # The record directory and the provenance document are what every later step
    # reads; name the missing one rather than failing inside a library.
    if args.step in {"replay", "perturb", "gates"}:
        provenance = paths.records / BASELINE_RUN / PROVENANCE_NAME
        if not provenance.is_file():
            parser.error(f"{provenance} is not there: run the `record` step first")
    return STEPS[args.step](paths)


if __name__ == "__main__":
    raise SystemExit(main())
