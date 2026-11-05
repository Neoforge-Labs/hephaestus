# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Generate the core's ISO 4217 exponent table, and keep it tied to the standard.

Three jobs, one derivation shared between them:

``uv run tools/gen_currencies.py``
    Write ``core/hephkit-core/src/money/currency_table.rs`` from
    ``spec/currencies.yaml``. ``--check`` exits 1 if the committed file differs,
    and never writes.

``uv run tools/gen_currencies.py --verify-source list-one.xml``
    Assert the local List One XML hashes to the ``sha256`` pinned in
    ``spec/currencies.source.yaml``, and that ``spec/currencies.yaml`` is exactly
    what that file derives to -- every code, its numeric code, its name and its
    minor-unit field, the ``N.A.`` rows included. This is what makes the
    transcription reproducible rather than asserted (CLAUDE.md rule 2). The XML
    is not vendored because SIX's terms do not clearly permit redistributing it;
    ``spec/currencies.source.yaml`` records that reasoning.

``uv run tools/gen_currencies.py --derivable list-one.xml``
    Say only whether the file parses as a List One publication at all, with no
    reference to the pin. The currency-source workflow needs this to tell a
    republication from a 200 carrying something that is not List One (a
    rate-limit page, a CDN interstitial): both differ from the pinned sha256,
    but only the first is news, and reporting the second as a republication
    advises an unnecessary re-pin.

``uv run tools/gen_currencies.py --transcribe list-one.xml``
    Rewrite ``spec/currencies.yaml`` from a List One XML whose hash matches the
    pin, so moving to a newer publication is a command rather than hand work.

A code reaches the Rust table if and only if its List One minor-unit field is
numeric (ADR 0017). Codes the standard publishes as ``N.A.`` stay out and are
rejected with ``HEPH-MONEY-422``; so is any code the standard has retired from
List One. No exponent here is ever derived by running a heph implementation.

Every output is a pure function of its input: entries are ordered by code and
there are no timestamps, so two runs give identical bytes.
"""

from __future__ import annotations

import hashlib
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

import yaml
from check_registry import check_currencies

OUTPUT_RELPATH = Path("core/hephkit-core/src/money/currency_table.rs")
REGISTRY_RELPATH = Path("spec/currencies.yaml")
SOURCE_RELPATH = Path("spec/currencies.source.yaml")

NO_EXPONENT = "N.A."
SOURCE_FIELDS = (
    "standard",
    "publisher",
    "url",
    "archive_url",
    "published",
    "retrieved",
    "amendment",
    "amendment_date",
    "sha256",
    "bytes",
)

# Our commentary on particular entries, carried into the registry so that
# --transcribe reproduces it instead of wiping it. Notes are about why the
# published number surprises a reader; they never restate or correct it.
ENTRY_NOTES = {
    "MGA": "the ariary divides into five iraimbilanja, but the standard publishes 2, not 1",
    "MRU": "the ouguiya divides into five khoums, but the standard publishes 2, not 1",
}

RUST_BANNER = """\
//! ISO 4217 minor-unit exponents generated from spec/currencies.yaml.
//!
//! GENERATED FILE - do not edit by hand. Regenerate with
//! `uv run tools/gen_currencies.py`; CI runs `--check`. Exponents live only in
//! `spec/currencies.yaml`, which transcribes ISO 4217 List One as published by
//! SIX Group. Editing a number here would make the core disagree with the
//! standard and with every other binding.
//!
//! A code appears below if and only if its List One minor-unit field is
//! numeric (ADR 0017), so the funds codes are in and the codes published as
//! `N.A.` are out. Lookup of a code that is absent is `HEPH-MONEY-422`.
//!
//! Entries are ordered by code, which `Currency::from_code` relies on to
//! binary search; `money::currency` tests that invariant.
//!
//! Derived from {standard},
//! published by {publisher}:
//!   url       {url}
//!   archive   {archive_url}
//!   published {published} (the XML root's Pblshd attribute)
//!   retrieved {retrieved}
//!   amendment {amendment} of {amendment_date}
//!   sha256    {sha256}
//! The published file is not vendored (its terms of use do not clearly permit
//! redistribution); `uv run tools/gen_currencies.py --verify-source <file>`
//! checks a local copy against that hash and re-derives the registry from it.
//! `url` is a rolling current-list file, so use `archive` once SIX has
//! republished and the live bytes have moved on.

/// Every ISO 4217 code with a defined minor-unit exponent, ordered by code.
"""

REGISTRY_HEADER = """\
# ISO 4217 currency registry. Source of truth for every minor-unit exponent the
# heph core accepts (spec 3.3), and the only input to the generated table in
# core/hephkit-core/src/money/currency_table.rs.
#
# Source: {standard},
#         as published by {publisher}.
#   URL:       {url}
#   Archive:   {archive_url}
#   Published: {published} (the XML root's Pblshd attribute)
#   Retrieved: {retrieved}
#   Amendment: {amendment}, dated {amendment_date}, is the latest amendment SIX
#              publishes (181 does not exist). This list incorporates it:
#              Bulgaria reads EUR, and BGN has moved to the historical list.
#   sha256:    {sha256}  ({bytes} bytes)
#
# NOT hand-written. This file is transcribed from the XML above by
# `uv run tools/gen_currencies.py --transcribe <file>`, and
# `--verify-source <file>` asserts both that the file hashes to the sha256 above
# and that every entry below is exactly what it derives to. Update it by
# re-transcribing a newer List One in full, never by editing one code's
# exponent: a single hand-edited number is a claim about the standard that
# nothing checks. spec/currencies.source.yaml records why the XML itself is not
# committed beside this file.
#
# Transcription: one entry per distinct alphabetic code in <CcyTbl>, ordered by
# code. List One carries one <CcyNtry> per country, so a shared code such as EUR
# or XOF appears many times; every duplicate row is required to carry identical
# Ccy, CcyNbr, CcyMnrUnts and CcyNm, so collapsing them loses nothing. Country
# rows carrying no <Ccy> at all (Antarctica, the State of Palestine, South
# Georgia and the South Sandwich Islands) have no entry here.
#
# `minor_units` is CcyMnrUnts verbatim: an integer, or the string 'N.A.' where
# the standard defines no exponent. Which of these the core accepts is decided
# by tools/gen_currencies.py, not here: a code is accepted if and only if its
# minor_units is numeric (ADR 0017).
"""


def load_source(path: Path) -> dict[str, Any]:
    """Read and validate spec/currencies.source.yaml."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: top level must be a mapping")
    missing = [f for f in SOURCE_FIELDS if data.get(f) in (None, "")]
    if missing:
        raise ValueError(f"{path.name}: missing {', '.join(missing)}")
    digest = str(data["sha256"])
    if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
        raise ValueError(f"{path.name}: sha256 must be 64 lowercase hex characters")
    if not isinstance(data["bytes"], int) or isinstance(data["bytes"], bool) or data["bytes"] <= 0:
        raise ValueError(f"{path.name}: bytes must be a positive integer")
    return data


def derive_from_xml(xml: bytes) -> list[dict[str, Any]]:
    """The registry entries ISO 4217 List One XML derives to, ordered by code.

    One entry per distinct alphabetic code. Duplicate rows for a code MUST agree
    on every field; a disagreement is an error rather than a silent pick, since
    picking would quietly decide which of two exponents the core believes.
    """
    root = ElementTree.fromstring(xml)
    table = root.find("CcyTbl")
    if table is None:
        raise ValueError("no <CcyTbl> element: this is not an ISO 4217 List One file")
    rows: dict[str, dict[str, Any]] = {}
    for entry in table:
        raw_code = entry.findtext("Ccy")
        if raw_code is None:  # a country row with no currency of its own
            continue
        code = raw_code.strip()
        units = (entry.findtext("CcyMnrUnts") or "").strip()
        record: dict[str, Any] = {
            "code": code,
            "numeric": (entry.findtext("CcyNbr") or "").strip(),
            "name": (entry.findtext("CcyNm") or "").strip(),
            "minor_units": int(units) if units.isdigit() else units,
        }
        if code in rows and rows[code] != record:
            raise ValueError(f"{code}: List One rows disagree: {rows[code]} vs {record}")
        rows[code] = record
    if not rows:
        raise ValueError("<CcyTbl> holds no currency entries")
    return [rows[code] for code in sorted(rows)]


def render_registry(entries: list[dict[str, Any]], source: dict[str, Any]) -> str:
    """The text of ``spec/currencies.yaml`` for derived entries."""
    lines = [REGISTRY_HEADER.format(**{k: source[k] for k in SOURCE_FIELDS})]
    for entry in entries:
        code = str(entry["code"])
        units = entry["minor_units"]
        units_yaml = units if isinstance(units, int) else f"'{units}'"
        note = ENTRY_NOTES.get(code)
        lines.append(f"- code: {code}\n")
        lines.append(f"  numeric: '{entry['numeric']}'\n")
        lines.append(f"  name: {entry['name']}\n")
        if note:
            lines.append(f"  # {note}\n")
        lines.append(f"  minor_units: {units_yaml}\n")
    return "".join(lines)


def render(entries: list[dict[str, Any]], source: dict[str, Any]) -> str:
    """The text of ``currency_table.rs`` for validated registry entries."""
    accepted = sorted(
        (str(e["code"]), int(e["minor_units"]))
        for e in entries
        if isinstance(e["minor_units"], int) and not isinstance(e["minor_units"], bool)
    )
    lines = [RUST_BANNER.format(**{k: source[k] for k in SOURCE_FIELDS})]
    lines.append(f"pub(super) const TABLE: [([u8; 3], u8); {len(accepted)}] = [\n")
    for code, exponent in accepted:
        lines.append(f'    (*b"{code}", {exponent}),\n')
    lines.append("];\n")
    return "".join(lines)


def _comparable(entries: list[dict[str, Any]]) -> dict[str, tuple[Any, ...]]:
    return {str(e["code"]): (str(e["numeric"]), str(e["name"]), e["minor_units"]) for e in entries}


def verify_source(registry: Path, source_path: Path, xml_path: Path) -> list[str]:
    """Return error strings if the registry is not what ``xml_path`` derives to.

    Checks the file's sha256 against the pin first: comparing against some other
    publication would prove nothing about the one the registry claims.
    """
    try:
        source = load_source(source_path)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        return [f"cannot read {source_path.name}: {exc}"]
    try:
        xml = xml_path.read_bytes()
    except OSError as exc:
        return [f"cannot read {xml_path}: {exc}"]

    found: list[str] = []
    digest = hashlib.sha256(xml).hexdigest()
    if digest != source["sha256"]:
        return [
            f"{xml_path}: sha256 {digest} does not match the pinned "
            f"{source['sha256']} from {source_path.name}. This is a different "
            f"publication. To re-check the committed registry, fetch the pinned "
            f"bytes: {source['url']} while it is still current, otherwise the "
            f"immutable capture {source['archive_url']} (gzip-encoded, so use "
            f"curl --compressed). To adopt a newer publication instead, update "
            f"the pin in {source_path.name} and re-run with --transcribe.",
        ]
    if len(xml) != source["bytes"]:
        found.append(f"{xml_path}: {len(xml)} bytes, pinned as {source['bytes']}")

    try:
        derived = derive_from_xml(xml)
    except (ElementTree.ParseError, ValueError) as exc:
        return found + [f"{xml_path}: cannot derive entries: {exc}"]
    try:
        committed = yaml.safe_load(registry.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return found + [f"cannot read {registry.name}: {exc}"]
    if not isinstance(committed, list):
        return found + [f"{registry.name}: top level must be a list of entries"]

    want, have = _comparable(derived), _comparable(committed)
    for code in sorted(set(want) - set(have)):
        found.append(f"{registry.name}: {code} is in List One but missing from the registry")
    for code in sorted(set(have) - set(want)):
        found.append(f"{registry.name}: {code} is in the registry but not in List One")
    for code in sorted(set(want) & set(have)):
        if want[code] != have[code]:
            fields = ("numeric", "name", "minor_units")
            differ = [f"{f}: registry {h!r}, List One {w!r}" for f, w, h in zip(fields, want[code], have[code]) if w != h]
            found.append(f"{registry.name}: {code} disagrees with List One -- {'; '.join(differ)}")
    order = [str(e["code"]) for e in committed]
    if order != sorted(order):
        found.append(f"{registry.name}: entries are not in code order")
    return found


def derivable(xml_path: Path) -> list[str]:
    """Return error strings if ``xml_path`` is not a List One publication.

    Deliberately says nothing about the pin: this answers "is this the
    standard's document at all?", which is the question that separates a
    publisher who has moved on from a location that answered 200 with an error
    page. ``verify_source`` returns on the sha256 mismatch before it ever
    parses, so it cannot tell those apart.
    """
    try:
        xml = xml_path.read_bytes()
    except OSError as exc:
        return [f"cannot read {xml_path}: {exc}"]
    try:
        # Raises on an empty <CcyTbl> too, so "parsed but empty" needs no
        # separate branch here.
        entries = derive_from_xml(xml)
    except (ElementTree.ParseError, ValueError) as exc:
        return [f"{xml_path}: cannot derive entries: {exc}"]
    print(f"{xml_path} derives {len(entries)} entries")
    return []


def _usage(message: str) -> int:
    print(
        "usage: gen_currencies.py [--check | --verify-source FILE | "
        f"--derivable FILE | --transcribe FILE] ({message})",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = root or Path(__file__).resolve().parents[1]
    registry = root / REGISTRY_RELPATH
    source_path = root / SOURCE_RELPATH
    output = root / OUTPUT_RELPATH

    mode, xml_arg = None, None
    rest = list(args)
    for flag in ("--verify-source", "--derivable", "--transcribe"):
        if flag in rest:
            index = rest.index(flag)
            if index + 1 >= len(rest):
                return _usage(f"{flag} needs a path to a List One XML file")
            mode, xml_arg = flag, rest[index + 1]
            del rest[index : index + 2]
    check = "--check" in rest
    rest = [a for a in rest if a != "--check"]
    if rest:
        return _usage(f"unknown: {' '.join(rest)}")
    if mode and check:
        return _usage("--check cannot be combined with --verify-source, --derivable or --transcribe")

    if mode == "--derivable":
        assert xml_arg is not None
        problems = derivable(Path(xml_arg))
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0

    if mode == "--verify-source":
        assert xml_arg is not None
        problems = verify_source(registry, source_path, Path(xml_arg))
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            return 1
        print(f"{REGISTRY_RELPATH} is exactly what {xml_arg} derives to, and that file matches the pinned sha256")
        return 0

    try:
        source = load_source(source_path)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        print(f"cannot read {SOURCE_RELPATH}: {exc}", file=sys.stderr)
        return 1

    if mode == "--transcribe":
        assert xml_arg is not None
        xml_path = Path(xml_arg)
        try:
            xml = xml_path.read_bytes()
        except OSError as exc:
            print(f"cannot read {xml_path}: {exc}", file=sys.stderr)
            return 1
        digest = hashlib.sha256(xml).hexdigest()
        if digest != source["sha256"]:
            print(
                f"{xml_path}: sha256 {digest} does not match the pinned {source['sha256']}; "
                f"update spec/currencies.source.yaml first, so the registry never claims a "
                f"publication it did not come from",
                file=sys.stderr,
            )
            return 1
        try:
            entries = derive_from_xml(xml)
        except (ElementTree.ParseError, ValueError) as exc:
            print(f"{xml_path}: cannot derive entries: {exc}", file=sys.stderr)
            return 1
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(render_registry(entries, source), encoding="utf-8", newline="\n")
        print(f"{REGISTRY_RELPATH}: {len(entries)} codes transcribed from {xml_path}")
        return 0

    problems = check_currencies(registry)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    entries = yaml.safe_load(registry.read_text(encoding="utf-8"))
    text = render(entries, source)

    if check:
        current = output.read_text(encoding="utf-8") if output.is_file() else None
        if current != text:
            print(f"{OUTPUT_RELPATH} is stale or missing; run: uv run tools/gen_currencies.py", file=sys.stderr)
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
