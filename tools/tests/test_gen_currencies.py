"""Tests for tools/gen_currencies.py."""

import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen_currencies import OUTPUT_RELPATH, main, render  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CURRENCIES = REPO_ROOT / "spec" / "currencies.yaml"

# The 19 codes the hand-written table accepted before the registry replaced it.
# Nothing accepted then may be rejected now, and no exponent may move.
PRE_REGISTRY_TABLE = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "KES": 2,
    "TZS": 2,
    "NGN": 2,
    "ZAR": 2,
    "UGX": 0,
    "JPY": 0,
    "BHD": 3,
    "KWD": 3,
    "OMR": 3,
    "KRW": 0,
    "ISK": 0,
    "XOF": 0,
    "JOD": 3,
    "CLF": 4,
    "CHF": 2,
    "CNY": 2,
}

# ISO 4217 List One publishes these with a minor-unit field of 'N.A.', so they
# have no exponent and must never reach the table (spec 3.3).
NO_EXPONENT_CODES = {
    "XXX",
    "XAU",
    "XAG",
    "XPT",
    "XPD",
    "XDR",
    "XTS",
    "XSU",
    "XUA",
    "XBA",
    "XBB",
    "XBC",
    "XBD",
}

# Funds codes: List One rows with a numeric minor-unit field, so ADR 0017
# accepts them.
FUNDS_CODES = {"CHE", "CHW", "USN", "MXV", "COU", "BOV", "CLF", "UYI", "UYW"}


def _root(tmp_path: Path) -> Path:
    (tmp_path / "spec").mkdir()
    shutil.copy(CURRENCIES, tmp_path / "spec" / "currencies.yaml")
    (tmp_path / OUTPUT_RELPATH).parent.mkdir(parents=True)
    return tmp_path


def _entries() -> list[dict[str, object]]:
    return yaml.safe_load(CURRENCIES.read_text(encoding="utf-8"))


def _table(text: str) -> dict[str, int]:
    rows: dict[str, int] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('(*b"'):
            code, exponent = line[4:].split('", ')
            rows[code] = int(exponent.rstrip("),"))
    return rows


def test_render_is_deterministic() -> None:
    assert render(_entries()) == render(_entries())


def test_generate_twice_gives_identical_bytes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert main([], root=root) == 0
    first = (root / OUTPUT_RELPATH).read_bytes()
    assert main([], root=root) == 0
    assert (root / OUTPUT_RELPATH).read_bytes() == first
    assert first


def test_output_has_a_generated_banner() -> None:
    text = render(_entries())
    assert "GENERATED" in text and "do not edit" in text.lower()
    assert "spec/currencies.yaml" in text


def test_table_length_matches_the_declared_array_length() -> None:
    text = render(_entries())
    rows = _table(text)
    assert f"const TABLE: [([u8; 3], u8); {len(rows)}] = [" in text


def test_every_numeric_registry_entry_is_in_the_table_and_no_other() -> None:
    entries = _entries()
    rows = _table(render(entries))
    expected = {
        str(e["code"]): e["minor_units"] for e in entries if isinstance(e["minor_units"], int)
    }
    assert rows == expected


def test_codes_without_an_exponent_are_excluded() -> None:
    rows = _table(render(_entries()))
    assert NO_EXPONENT_CODES.isdisjoint(rows), sorted(NO_EXPONENT_CODES & set(rows))


def test_funds_codes_are_included() -> None:
    rows = _table(render(_entries()))
    assert FUNDS_CODES <= set(rows), sorted(FUNDS_CODES - set(rows))


def test_the_pre_registry_table_is_a_subset_with_identical_exponents() -> None:
    rows = _table(render(_entries()))
    assert {code: rows.get(code) for code in PRE_REGISTRY_TABLE} == PRE_REGISTRY_TABLE


def test_table_is_sorted_by_code() -> None:
    # Currency::from_code binary searches, so order is load-bearing.
    codes = list(_table(render(_entries())))
    assert codes == sorted(codes)


def test_exponents_fit_a_u8_and_stay_within_what_iso_defines() -> None:
    assert set(_table(render(_entries())).values()) <= {0, 1, 2, 3, 4}


def test_check_passes_when_current_and_exits_1_when_stale(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert main(["--check"], root=root) == 1  # missing
    assert main([], root=root) == 0
    assert main(["--check"], root=root) == 0
    out = root / OUTPUT_RELPATH
    before = out.read_bytes()
    out.write_text(out.read_text(encoding="utf-8") + "// drift\n", encoding="utf-8")
    stale = out.read_bytes()
    assert main(["--check"], root=root) == 1
    assert out.read_bytes() == stale != before  # --check never writes


def test_check_is_stale_after_registry_change(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert main([], root=root) == 0
    reg = root / "spec" / "currencies.yaml"
    reg.write_text(
        reg.read_text(encoding="utf-8").replace(
            "- code: JPY\n  numeric: '392'\n  name: Yen\n  minor_units: 0",
            "- code: JPY\n  numeric: '392'\n  name: Yen\n  minor_units: 2",
        ),
        encoding="utf-8",
    )
    assert main(["--check"], root=root) == 1


def test_invalid_registry_writes_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "spec" / "currencies.yaml").write_text(
        "- code: usd\n  numeric: '840'\n  name: US Dollar\n  minor_units: 2\n", encoding="utf-8"
    )
    assert main([], root=root) == 1
    assert not (root / OUTPUT_RELPATH).exists()


def test_registry_with_an_out_of_range_exponent_writes_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "spec" / "currencies.yaml").write_text(
        "- code: USD\n  numeric: '840'\n  name: US Dollar\n  minor_units: 9\n", encoding="utf-8"
    )
    assert main([], root=root) == 1
    assert not (root / OUTPUT_RELPATH).exists()


def test_unordered_registry_writes_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "spec" / "currencies.yaml").write_text(
        "- code: USD\n  numeric: '840'\n  name: US Dollar\n  minor_units: 2\n"
        "- code: EUR\n  numeric: '978'\n  name: Euro\n  minor_units: 2\n",
        encoding="utf-8",
    )
    assert main([], root=root) == 1
    assert not (root / OUTPUT_RELPATH).exists()


def test_committed_output_matches_the_committed_registry() -> None:
    assert main(["--check"], root=REPO_ROOT) == 0


def test_unknown_argument_is_usage_error(tmp_path: Path) -> None:
    assert main(["--nope"], root=_root(tmp_path)) == 2
