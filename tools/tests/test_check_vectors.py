"""Tests for tools/check_vectors.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_vectors import check_vectors  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFORMANCE = REPO_ROOT / "conformance"
ERRORS = REPO_ROOT / "spec" / "errors.yaml"

# Floors from the task brief; written out here so the test does not import them
# from the module under test.
MINIMUM_CASES = {
    "money.currency": 12,
    "money.parse": 30,
    "money.format": 10,
    "money.arith": 8,
    "money.compare": 20,
    "money.allocate": 10,
    "hashing.jcs": 12,
    "hashing.content": 6,
    "signatures.sign": 4,
    "signatures.verify": 10,
    "idempotency.key": 12,
    "idempotency.fingerprint": 16,
    "lab.config": 10,
    "lab.record": 12,
    "lab.diff": 8,
}


def _count(suite: str) -> int:
    area, name = suite.split(".")
    data = json.loads((CONFORMANCE / area / f"{name}.json").read_text(encoding="utf-8"))
    return len(data["cases"])


def test_all_vector_files_match_schema() -> None:
    assert check_vectors(CONFORMANCE, ERRORS) == []
    files = sorted(p.relative_to(CONFORMANCE).as_posix() for p in CONFORMANCE.glob("*/*.json"))
    # A literal, not len(MINIMUM_CASES) + 1: this is meant to fail when a suite
    # is added, so that adding one is a decision somebody records here rather
    # than something a derived count absorbs silently.
    assert len(files) == 16, files  # fifteen suites plus the schema


def test_minimum_case_counts() -> None:
    for suite, floor in MINIMUM_CASES.items():
        assert _count(suite) >= floor, suite


def _scratch(tmp_path: Path, file_suite: str, cases: object, **top: object) -> Path:
    area, name = file_suite.split(".")
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "vector-file.schema.json").write_text(
        (CONFORMANCE / "schema" / "vector-file.schema.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / area).mkdir()
    body = {"suite": file_suite, "spec": "0.5.0", "cases": cases}
    body.update(top)
    (tmp_path / area / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")
    return tmp_path


def _good(tmp_path: Path, cases: object, **top: object) -> list[str]:
    return check_vectors(_scratch(tmp_path, "money.format", cases, **top), ERRORS, require_all=False)


GOOD = {"name": "a", "input": {"minor": "1", "currency": "KES"}, "expect": {"amount": "0.01"}}


def test_accepts_well_formed_file(tmp_path: Path) -> None:
    assert _good(tmp_path, [GOOD]) == []


def test_rejects_unknown_suite(tmp_path: Path) -> None:
    # File name matches the bogus suite, so only the schema enum can object.
    root = _scratch(tmp_path, "money.nope", [GOOD])
    findings = check_vectors(root, ERRORS, require_all=False)
    assert any("is not one of" in f for f in findings), findings


def test_rejects_case_with_neither_expect_nor_error(tmp_path: Path) -> None:
    bad = {"name": "a", "input": {"minor": "1", "currency": "KES"}}
    assert _good(tmp_path, [bad])


def test_rejects_error_code_outside_registry(tmp_path: Path) -> None:
    bad = {"name": "a", "input": {"minor": "1", "currency": "KES"}, "expect": {"error": "HEPH-MONEY-999"}}
    assert any("registry" in f for f in _good(tmp_path, [bad]))


def test_rejects_malformed_error_code(tmp_path: Path) -> None:
    bad = {"name": "a", "input": {"minor": "1", "currency": "KES"}, "expect": {"error": "heph-money-422"}}
    assert _good(tmp_path, [bad])


def test_rejects_wrong_input_shape_for_suite(tmp_path: Path) -> None:
    bad = {"name": "a", "input": {"amount": "1", "currency": "KES"}, "expect": {"amount": "0.01"}}
    assert _good(tmp_path, [bad])


def test_rejects_duplicate_case_names(tmp_path: Path) -> None:
    assert any("duplicate" in f for f in _good(tmp_path, [GOOD, GOOD]))


def test_rejects_wrong_spec_version(tmp_path: Path) -> None:
    findings = _good(tmp_path, [GOOD], spec="0.1.0")
    assert any("was expected" in f for f in findings), findings


def test_rejects_suite_not_matching_filename(tmp_path: Path) -> None:
    root = _scratch(tmp_path, "money.format", [GOOD], suite="money.parse")
    assert check_vectors(root, ERRORS, require_all=False)


def test_missing_suite_files_reported_when_required(tmp_path: Path) -> None:
    root = _scratch(tmp_path, "money.format", [GOOD])
    assert any("missing" in f for f in check_vectors(root, ERRORS))


def test_rejects_count_below_floor(tmp_path: Path) -> None:
    root = _scratch(tmp_path, "money.format", [GOOD])
    assert any("minimum is 10" in f for f in check_vectors(root, ERRORS))


def test_reports_unreadable_json(tmp_path: Path) -> None:
    root = _scratch(tmp_path, "money.format", [GOOD])
    (root / "money" / "format.json").write_text("{not json", encoding="utf-8")
    assert any("cannot read" in f for f in check_vectors(root, ERRORS, require_all=False))


def test_reports_unreadable_registry(tmp_path: Path) -> None:
    root = _scratch(tmp_path, "money.format", [GOOD])
    findings = check_vectors(root, tmp_path / "nope.yaml", require_all=False)
    assert any("cannot read error registry" in f for f in findings), findings


def test_reports_unloadable_schema(tmp_path: Path) -> None:
    root = _scratch(tmp_path, "money.format", [GOOD])
    (root / "schema" / "vector-file.schema.json").unlink()
    assert any("cannot load schema" in f for f in check_vectors(root, ERRORS, require_all=False))
