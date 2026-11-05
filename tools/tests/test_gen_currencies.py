"""Tests for tools/gen_currencies.py."""

import hashlib
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen_currencies import (  # noqa: E402
    OUTPUT_RELPATH,
    derive_from_xml,
    load_source,
    main,
    render,
    render_registry,
    verify_source,
)
from check_registry import check_currencies  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CURRENCIES = REPO_ROOT / "spec" / "currencies.yaml"
SOURCE = REPO_ROOT / "spec" / "currencies.source.yaml"

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
    shutil.copy(SOURCE, tmp_path / "spec" / "currencies.source.yaml")
    (tmp_path / OUTPUT_RELPATH).parent.mkdir(parents=True)
    return tmp_path


def _source() -> dict[str, object]:
    return load_source(SOURCE)


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
    assert render(_entries(), _source()) == render(_entries(), _source())


def test_generate_twice_gives_identical_bytes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert main([], root=root) == 0
    first = (root / OUTPUT_RELPATH).read_bytes()
    assert main([], root=root) == 0
    assert (root / OUTPUT_RELPATH).read_bytes() == first
    assert first


def test_output_has_a_generated_banner() -> None:
    text = render(_entries(), _source())
    assert "GENERATED" in text and "do not edit" in text.lower()
    assert "spec/currencies.yaml" in text


def test_table_length_matches_the_declared_array_length() -> None:
    text = render(_entries(), _source())
    rows = _table(text)
    assert f"const TABLE: [([u8; 3], u8); {len(rows)}] = [" in text


def test_every_numeric_registry_entry_is_in_the_table_and_no_other() -> None:
    entries = _entries()
    rows = _table(render(entries, _source()))
    expected = {
        str(e["code"]): e["minor_units"] for e in entries if isinstance(e["minor_units"], int)
    }
    assert rows == expected


def test_codes_without_an_exponent_are_excluded() -> None:
    rows = _table(render(_entries(), _source()))
    assert NO_EXPONENT_CODES.isdisjoint(rows), sorted(NO_EXPONENT_CODES & set(rows))


def test_funds_codes_are_included() -> None:
    rows = _table(render(_entries(), _source()))
    assert FUNDS_CODES <= set(rows), sorted(FUNDS_CODES - set(rows))


def test_the_pre_registry_table_is_a_subset_with_identical_exponents() -> None:
    rows = _table(render(_entries(), _source()))
    assert {code: rows.get(code) for code in PRE_REGISTRY_TABLE} == PRE_REGISTRY_TABLE


def test_table_is_sorted_by_code() -> None:
    # Currency::from_code binary searches, so order is load-bearing.
    codes = list(_table(render(_entries(), _source())))
    assert codes == sorted(codes)


def test_exponents_fit_a_u8_and_stay_within_what_iso_defines() -> None:
    assert set(_table(render(_entries(), _source())).values()) <= {0, 1, 2, 3, 4}


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


# --- the source pin and the XML derivation -----------------------------------
#
# A synthetic List One of our own invention, not SIX's data: these tests must run
# offline, and the published file is not redistributable. It exercises the shapes
# that matter -- duplicate country rows for one code, a country row with no
# currency, an N.A. row, and out-of-order codes.
SYNTHETIC_XML = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ISO_4217 Pblshd="2026-09-17">
\t<CcyTbl>
\t\t<CcyNtry>
\t\t\t<CtryNm>ZEDLAND</CtryNm>
\t\t\t<CcyNm>Zed</CcyNm>
\t\t\t<Ccy>ZZD</Ccy>
\t\t\t<CcyNbr>001</CcyNbr>
\t\t\t<CcyMnrUnts>2</CcyMnrUnts>
\t\t</CcyNtry>
\t\t<CcyNtry>
\t\t\t<CtryNm>NOWHERE</CtryNm>
\t\t</CcyNtry>
\t\t<CcyNtry>
\t\t\t<CtryNm>ALPHALAND</CtryNm>
\t\t\t<CcyNm>Alpha</CcyNm>
\t\t\t<Ccy>AAA</Ccy>
\t\t\t<CcyNbr>002</CcyNbr>
\t\t\t<CcyMnrUnts>0</CcyMnrUnts>
\t\t</CcyNtry>
\t\t<CcyNtry>
\t\t\t<CtryNm>ALPHALAND SOUTH</CtryNm>
\t\t\t<CcyNm>Alpha</CcyNm>
\t\t\t<Ccy>AAA</Ccy>
\t\t\t<CcyNbr>002</CcyNbr>
\t\t\t<CcyMnrUnts>0</CcyMnrUnts>
\t\t</CcyNtry>
\t\t<CcyNtry>
\t\t\t<CtryNm>ZZ99_Nothing</CtryNm>
\t\t\t<CcyNm>No currency</CcyNm>
\t\t\t<Ccy>QQQ</Ccy>
\t\t\t<CcyNbr>003</CcyNbr>
\t\t\t<CcyMnrUnts>N.A.</CcyMnrUnts>
\t\t</CcyNtry>
\t</CcyTbl>
</ISO_4217>
"""


def test_derivation_collapses_country_rows_and_keeps_na_rows() -> None:
    assert derive_from_xml(SYNTHETIC_XML) == [
        {"code": "AAA", "numeric": "002", "name": "Alpha", "minor_units": 0},
        {"code": "QQQ", "numeric": "003", "name": "No currency", "minor_units": "N.A."},
        {"code": "ZZD", "numeric": "001", "name": "Zed", "minor_units": 2},
    ]


def test_derivation_refuses_to_pick_between_disagreeing_rows() -> None:
    # Silently picking one would quietly decide which exponent the core believes.
    clash = SYNTHETIC_XML.replace(
        b"<Ccy>ZZD</Ccy>\n\t\t\t<CcyNbr>001</CcyNbr>\n\t\t\t<CcyMnrUnts>2</CcyMnrUnts>",
        b"<Ccy>AAA</Ccy>\n\t\t\t<CcyNbr>002</CcyNbr>\n\t\t\t<CcyMnrUnts>3</CcyMnrUnts>",
    )
    with pytest.raises(ValueError, match="rows disagree"):
        derive_from_xml(clash)


def test_derivation_rejects_a_file_that_is_not_list_one() -> None:
    with pytest.raises(ValueError, match="CcyTbl"):
        derive_from_xml(b"<ISO_4217><Nope/></ISO_4217>")


def test_registry_render_round_trips_through_the_derivation() -> None:
    entries = derive_from_xml(SYNTHETIC_XML)
    text = render_registry(entries, _source())
    assert yaml.safe_load(text) == entries


def test_registry_render_carries_our_entry_notes() -> None:
    text = render_registry(_entries(), _source())
    assert "# the ariary divides into five iraimbilanja" in text
    assert "# the ouguiya divides into five khoums" in text
    # A note is a comment, so it never becomes data.
    loaded = {str(e["code"]): e for e in yaml.safe_load(text)}
    assert set(loaded["MGA"]) == {"code", "numeric", "name", "minor_units"}
    assert loaded["MGA"]["minor_units"] == 2 and loaded["MRU"]["minor_units"] == 2


def test_committed_registry_is_exactly_what_the_renderer_produces() -> None:
    # Closes the loop: the committed file is reproducible from the derivation,
    # so --verify-source against the pinned bytes is the only trusted hop.
    assert render_registry(_entries(), _source()) == CURRENCIES.read_text(encoding="utf-8")


def test_rust_banner_names_the_pinned_publication() -> None:
    source = _source()
    text = render(_entries(), source)
    for field in ("url", "archive_url", "published", "retrieved", "sha256"):
        assert str(source[field]) in text, field


def test_source_pins_an_immutable_fallback_location() -> None:
    # `url` is a rolling current-list file: once the publisher republishes it no
    # longer serves the pinned bytes, and --verify-source could never re-check
    # the committed registry again. archive_url must be a different location.
    source = _source()
    assert source["archive_url"] != source["url"]
    assert str(source["archive_url"]).startswith("https://")


def test_source_pin_is_a_well_formed_sha256() -> None:
    digest = str(_source()["sha256"])
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")


def test_source_missing_a_field_is_an_error(tmp_path: Path) -> None:
    bad = tmp_path / "currencies.source.yaml"
    bad.write_text("url: https://example.test/list-one.xml\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        load_source(bad)


def _pinned(tmp_path: Path, xml: bytes) -> Path:
    """A root whose source pin matches ``xml``, with a registry derived from it."""
    root = tmp_path / "repo"
    (root / "spec").mkdir(parents=True)
    source = dict(_source())
    source["sha256"] = hashlib.sha256(xml).hexdigest()
    source["bytes"] = len(xml)
    (root / "spec" / "currencies.source.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")
    (root / "spec" / "currencies.yaml").write_text(
        render_registry(derive_from_xml(xml), source), encoding="utf-8"
    )
    (root / OUTPUT_RELPATH).parent.mkdir(parents=True)
    (tmp_path / "list-one.xml").write_bytes(xml)
    return root


def test_verify_source_passes_on_a_matching_pair(tmp_path: Path) -> None:
    root = _pinned(tmp_path, SYNTHETIC_XML)
    assert verify_source(
        root / "spec" / "currencies.yaml",
        root / "spec" / "currencies.source.yaml",
        tmp_path / "list-one.xml",
    ) == []
    assert main(["--verify-source", str(tmp_path / "list-one.xml")], root=root) == 0


def test_verify_source_rejects_a_different_publication(tmp_path: Path) -> None:
    root = _pinned(tmp_path, SYNTHETIC_XML)
    other = tmp_path / "other.xml"
    other.write_bytes(SYNTHETIC_XML.replace(b"<CcyNm>Zed</CcyNm>", b"<CcyNm>Zedd</CcyNm>"))
    findings = verify_source(
        root / "spec" / "currencies.yaml", root / "spec" / "currencies.source.yaml", other
    )
    assert any("does not match the pinned" in f for f in findings), findings
    assert main(["--verify-source", str(other)], root=root) == 1


def test_verify_source_catches_a_one_digit_slip_in_the_registry(tmp_path: Path) -> None:
    # The exact failure the source pin exists to catch: an exponent edited in the
    # registry that no vector covers. check_registry and --check both pass it.
    root = _pinned(tmp_path, SYNTHETIC_XML)
    registry = root / "spec" / "currencies.yaml"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "- code: ZZD\n  numeric: '001'\n  name: Zed\n  minor_units: 2",
            "- code: ZZD\n  numeric: '001'\n  name: Zed\n  minor_units: 3",
        ),
        encoding="utf-8",
    )
    assert check_currencies(registry) == []  # the shape is still valid
    assert main([], root=root) == 0  # and the table regenerates happily
    findings = verify_source(
        registry, root / "spec" / "currencies.source.yaml", tmp_path / "list-one.xml"
    )
    assert any("ZZD disagrees with List One" in f and "minor_units" in f for f in findings), findings


def test_verify_source_catches_an_na_row_turned_into_a_number(tmp_path: Path) -> None:
    root = _pinned(tmp_path, SYNTHETIC_XML)
    registry = root / "spec" / "currencies.yaml"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace("minor_units: 'N.A.'", "minor_units: 2"),
        encoding="utf-8",
    )
    findings = verify_source(
        registry, root / "spec" / "currencies.source.yaml", tmp_path / "list-one.xml"
    )
    assert any("QQQ disagrees with List One" in f for f in findings), findings


def test_verify_source_catches_a_dropped_and_an_invented_code(tmp_path: Path) -> None:
    root = _pinned(tmp_path, SYNTHETIC_XML)
    registry = root / "spec" / "currencies.yaml"
    text = registry.read_text(encoding="utf-8").replace(
        "- code: ZZD\n  numeric: '001'\n  name: Zed\n  minor_units: 2\n",
        "- code: ZZE\n  numeric: '009'\n  name: Zed\n  minor_units: 2\n",
    )
    registry.write_text(text, encoding="utf-8")
    findings = verify_source(
        registry, root / "spec" / "currencies.source.yaml", tmp_path / "list-one.xml"
    )
    assert any("ZZD is in List One but missing from the registry" in f for f in findings), findings
    assert any("ZZE is in the registry but not in List One" in f for f in findings), findings


def test_verify_source_reports_a_missing_xml_file(tmp_path: Path) -> None:
    root = _pinned(tmp_path, SYNTHETIC_XML)
    findings = verify_source(
        root / "spec" / "currencies.yaml",
        root / "spec" / "currencies.source.yaml",
        tmp_path / "absent.xml",
    )
    assert any("cannot read" in f for f in findings), findings


def test_transcribe_rewrites_the_registry_from_a_matching_file(tmp_path: Path) -> None:
    root = _pinned(tmp_path, SYNTHETIC_XML)
    registry = root / "spec" / "currencies.yaml"
    expected = registry.read_text(encoding="utf-8")
    registry.write_text("- code: AAA\n  numeric: '002'\n  name: Alpha\n  minor_units: 4\n", encoding="utf-8")
    assert main(["--transcribe", str(tmp_path / "list-one.xml")], root=root) == 0
    assert registry.read_text(encoding="utf-8") == expected


def test_transcribe_refuses_a_file_the_pin_does_not_cover(tmp_path: Path) -> None:
    root = _pinned(tmp_path, SYNTHETIC_XML)
    other = tmp_path / "other.xml"
    other.write_bytes(SYNTHETIC_XML.replace(b"<CcyNbr>001</CcyNbr>", b"<CcyNbr>004</CcyNbr>"))
    registry = root / "spec" / "currencies.yaml"
    before = registry.read_text(encoding="utf-8")
    assert main(["--transcribe", str(other)], root=root) == 1
    assert registry.read_text(encoding="utf-8") == before  # never writes on a hash mismatch


def test_mode_flags_need_a_path_and_do_not_combine_with_check(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert main(["--verify-source"], root=root) == 2
    assert main(["--transcribe"], root=root) == 2
    assert main(["--check", "--verify-source", "x.xml"], root=root) == 2

