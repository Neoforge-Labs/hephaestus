"""Tests for tools/check_registry.py."""

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_registry import check_registry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ERRORS = REPO_ROOT / "spec" / "errors.yaml"
ATTRIBUTES = REPO_ROOT / "conventions" / "attributes.yaml"

CODE_RE = re.compile(r"^HEPH-[A-Z]{2,6}-\d{3}$")
ATTR_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

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
    entries = _load(ERRORS)
    codes = [e["code"] for e in entries]
    assert len(codes) == len(set(codes)), "duplicate codes"
    for e in entries:
        assert CODE_RE.match(e["code"]), e["code"]
        assert 400 <= e["status"] <= 599, e["code"]
        assert e["area"] == e["code"].split("-")[1], e["code"]
        assert e["title"] and e["detail_hint"], e["code"]
    assert check_registry(ERRORS, ATTRIBUTES) == []


def test_registry_has_v01_codes() -> None:
    by_code = {e["code"]: e["status"] for e in _load(ERRORS)}
    for code, status in V01_CODES.items():
        assert by_code.get(code) == status, code


def test_attributes_valid() -> None:
    entries = _load(ATTRIBUTES)
    names = [a["name"] for a in entries]
    assert len(names) == len(set(names)), "duplicate attributes"
    for a in entries:
        assert ATTR_RE.match(a["name"]), a["name"]
        assert isinstance(a["pii"], bool), a["name"]
        assert a["type"] and a["description"], a["name"]
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
