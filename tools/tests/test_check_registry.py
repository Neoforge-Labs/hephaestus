"""Tests for tools/check_registry.py."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_registry import check_registry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ERRORS = REPO_ROOT / "spec" / "errors.yaml"
ATTRIBUTES = REPO_ROOT / "conventions" / "attributes.yaml"

V01_CODES = {
    "HEPH-GEN-500": 500,
    "HEPH-VAL-422": 422,
    "HEPH-NF-404": 404,
    "HEPH-AUTH-401": 401,
    "HEPH-AUTH-403": 403,
    "HEPH-RATE-429": 429,
    "HEPH-IDEMP-400": 400,
    "HEPH-IDEMP-409": 409,
    "HEPH-IDEMP-422": 422,
    "HEPH-MONEY-422": 422,
    "HEPH-MONEY-409": 409,
    "HEPH-WH-401": 401,
}

V01_ATTRIBUTES = {
    "tenant.id",
    "user.id",
    "idempotency.key",
    "job.name",
    "webhook.provider",
    "money.currency",
    "heph.error.code",
}


def _load(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_registry_codes_valid() -> None:
    assert check_registry(ERRORS, ATTRIBUTES) == []
    entries = _load(ERRORS)
    assert len(entries) == 12
    assert {e["code"] for e in entries} == set(V01_CODES)
    assert {e["code"]: e["area"] for e in entries}["HEPH-NF-404"] == "NF"
    assert all(e["title"] and e["detail_hint"] for e in entries)


def test_registry_has_v01_codes() -> None:
    by_code = {e["code"]: e["status"] for e in _load(ERRORS)}
    for code, status in V01_CODES.items():
        assert by_code.get(code) == status, code


def test_attributes_valid() -> None:
    entries = _load(ATTRIBUTES)
    names = [a["name"] for a in entries]
    assert len(names) == len(set(names)), "duplicate attributes"
    assert check_registry(ERRORS, ATTRIBUTES) == []
    assert all(isinstance(a["pii"], bool) for a in entries)
    assert V01_ATTRIBUTES <= set(names)
    assert {a["name"]: a["pii"] for a in entries}["user.id"] is True


def _write(tmp_path: Path, errors: str, attributes: str) -> tuple[Path, Path]:
    e, a = tmp_path / "errors.yaml", tmp_path / "attributes.yaml"
    e.write_text(errors)
    a.write_text(attributes)
    return e, a


GOOD_ATTR = "- {name: user.id, type: string, description: d, pii: true}\n"
GOOD_ERR = "- {code: HEPH-GEN-500, status: 500, title: t, area: GEN, detail_hint: h}\n"


def test_rejects_bad_code_and_area(tmp_path: Path) -> None:
    bad = "- {code: HEPH-G-5, status: 500, title: t, area: X, detail_hint: h}\n"
    errors = check_registry(*_write(tmp_path, bad, GOOD_ATTR))
    assert any("HEPH-G-5" in e for e in errors)


def test_rejects_duplicates_and_bad_status(tmp_path: Path) -> None:
    dup = GOOD_ERR + GOOD_ERR.replace("500, title", "200, title")
    errors = check_registry(*_write(tmp_path, dup, GOOD_ATTR + GOOD_ATTR))
    assert any("duplicate code" in e for e in errors)
    assert any("status" in e for e in errors)
    assert any("duplicate attribute" in e for e in errors)


def test_rejects_non_boolean_pii(tmp_path: Path) -> None:
    attr = "- {name: user.id, type: string, description: d, pii: 'yes'}\n"
    errors = check_registry(*_write(tmp_path, GOOD_ERR, attr))
    assert any("pii" in e for e in errors)


def _errs(tmp_path: Path, errors: str = GOOD_ERR, attributes: str = GOOD_ATTR) -> list[str]:
    return check_registry(*_write(tmp_path, errors, attributes))


def test_rejects_area_mismatch_on_valid_code(tmp_path: Path) -> None:
    bad = "- {code: HEPH-GEN-500, status: 500, title: t, area: VAL, detail_hint: h}\n"
    assert any("area" in e for e in _errs(tmp_path, bad))


def test_rejects_trailing_newline_and_non_ascii_digits(tmp_path: Path) -> None:
    for code in ('"HEPH-GEN-500\\n"', "HEPH-GEN-\u0665\u0660\u0660"):
        bad = f'- {{code: {code}, status: 500, title: t, area: GEN, detail_hint: h}}\n'
        assert any("code must match" in e for e in _errs(tmp_path, bad)), code


def test_rejects_bad_attribute_name(tmp_path: Path) -> None:
    for name in ("UserId", "user", "user.Id", "user..id"):
        bad = f"- {{name: {name}, type: string, description: d, pii: false}}\n"
        assert any("dotted lowercase" in e for e in _errs(tmp_path, attributes=bad)), name


def test_rejects_missing_fields(tmp_path: Path) -> None:
    errors = _errs(tmp_path, "- {code: HEPH-GEN-500, status: 500}\n", "- {name: user.id, pii: true}\n")
    for field in ("title", "area", "detail_hint", "type", "description"):
        assert any(f"missing '{field}'" in e for e in errors), field


def test_rejects_non_list_missing_file_and_non_mapping(tmp_path: Path) -> None:
    assert any("list" in e for e in _errs(tmp_path, "code: x\n"))
    assert any("not a mapping" in e for e in _errs(tmp_path, "- just a string\n", "- 3\n"))
    missing = check_registry(tmp_path / "nope.yaml", tmp_path / "nope2.yaml")
    assert sum("does not exist" in e for e in missing) == 2


def test_reports_yaml_syntax_error(tmp_path: Path) -> None:
    errors = _errs(tmp_path, "- {code: [unclosed\n")
    assert any("invalid YAML" in e for e in errors)
