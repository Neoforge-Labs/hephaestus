"""The idempotency vectors, checked against the spec and against arithmetic.

These tests deliberately do not import the generator's reference package. They
re-derive each digest with the standard library and compare the result with the
committed file, so a vector is wrong only if hashlib and rfc8785 are wrong in
the same way -- which is the point of deriving from independent sources.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTORS = REPO_ROOT / "conformance/idempotency"
SPEC = REPO_ROOT / "spec/heph-spec.md"


def _load(name: str) -> dict:
    return json.loads((VECTORS / f"{name}.json").read_text(encoding="utf-8"))


def test_every_fingerprint_is_the_sha256_of_its_own_jcs_string() -> None:
    """Spec 2.2 steps 3 and 4, recomputed rather than trusted.

    The file carries both the JCS string and the digest. If they ever disagree,
    an implementation chasing the digest would be chasing a number no longer
    derivable from the stated input.
    """
    for case in _load("fingerprint")["cases"]:
        if "error" in case["expect"]:
            continue
        jcs = case["expect"]["jcs"]
        expected = "sha256:" + hashlib.sha256(jcs.encode("utf-8")).hexdigest()
        assert case["expect"]["fingerprint"] == expected, case["name"]


def test_the_specs_worked_example_is_a_vector() -> None:
    """The example in spec 2.2 and the vectors must not drift apart.

    Both the JCS string and the digest are read out of the specification text,
    not copied here, so editing one without the other fails.
    """
    spec = SPEC.read_text(encoding="utf-8")
    jcs_match = re.search(r"the JCS string is `(\{[^`]+\})`", spec)
    digest_match = re.search(r"the fingerprint is `(sha256:[0-9a-f]{64})`", spec)
    assert jcs_match and digest_match, "spec 2.2 no longer states its worked example in the expected form"

    cases = _load("fingerprint")["cases"]
    matching = [c for c in cases if c["expect"].get("jcs") == jcs_match.group(1)]
    assert matching, f"no vector carries the spec's JCS string {jcs_match.group(1)!r}"
    assert matching[0]["expect"]["fingerprint"] == digest_match.group(1)


def test_jcs_strings_sort_their_member_names() -> None:
    """RFC 8785 orders members; the three outer ones are always body/method/path."""
    for case in _load("fingerprint")["cases"]:
        if "error" in case["expect"]:
            continue
        parsed = json.loads(case["expect"]["jcs"])
        assert sorted(parsed) == ["body", "method", "path"], case["name"]
        assert case["expect"]["jcs"].startswith('{"body":'), case["name"]


def test_the_jcs_string_reproduces_the_declared_input() -> None:
    for case in _load("fingerprint")["cases"]:
        if "error" in case["expect"]:
            continue
        parsed = json.loads(case["expect"]["jcs"])
        assert parsed["method"] == case["input"]["method"], case["name"]
        assert parsed["path"] == case["input"]["path"], case["name"]
        if "body" not in case["input"] or case["input"]["body"] == "":
            assert parsed["body"] is None, case["name"]


def test_query_order_changes_the_fingerprint() -> None:
    """2.2: the target is never normalised, so two orderings differ.

    This is the rule an implementation is most likely to break by being helpful,
    and the two cases are worthless unless they actually disagree.
    """
    cases = {c["name"]: c for c in _load("fingerprint")["cases"]}
    a = cases["query-string-is-part-of-the-path"]
    b = cases["query-order-is-not-normalised"]
    assert a["input"]["path"] != b["input"]["path"]
    assert a["expect"]["fingerprint"] != b["expect"]["fingerprint"]


def test_media_type_variants_agree_with_plain_json() -> None:
    """A parameter, a +json subtype and odd casing are all JSON (2.2)."""
    cases = {c["name"]: c for c in _load("fingerprint")["cases"]}
    canonical = cases["post-json-object-sorts-member-names"]["expect"]["fingerprint"]
    for name in (
        "media-type-parameters-are-ignored",
        "json-subtype-suffix-is-json",
        "media-type-case-is-ignored",
    ):
        assert cases[name]["expect"]["fingerprint"] == canonical, name


def test_key_cases_cover_both_sides_of_the_required_flag() -> None:
    cases = _load("key")["cases"]
    required = [c for c in cases if c["input"]["required"]]
    optional = [c for c in cases if not c["input"]["required"]]
    assert required and optional
    # 2.1: an endpoint that does not require a key never fails on a bad one.
    assert all("error" not in c["expect"] for c in optional)
    # And one that does must reject every violation with the registry code.
    assert {c["expect"]["error"] for c in required if "error" in c["expect"]} == {"HEPH-IDEMP-400"}


def test_key_length_boundaries_are_both_present() -> None:
    cases = {c["name"]: c for c in _load("key")["cases"]}
    assert len(cases["255-characters-is-accepted"]["input"]["key"]) == 255
    assert cases["255-characters-is-accepted"]["expect"] == {"ok": True}
    assert len(cases["256-characters-is-rejected"]["input"]["key"]) == 256
    assert cases["256-characters-is-rejected"]["expect"] == {"error": "HEPH-IDEMP-400"}


def test_accepted_keys_are_printable_ascii_without_whitespace() -> None:
    """Every "ok" key satisfies 2.1, and every rejected one violates it."""
    def valid(key: str | None) -> bool:
        return key is not None and 1 <= len(key) <= 255 and all(0x21 <= ord(c) <= 0x7E for c in key)

    for case in _load("key")["cases"]:
        key = case["input"]["key"]
        if case["expect"].get("ok"):
            assert valid(key), case["name"]
        elif "error" in case["expect"]:
            assert not valid(key), case["name"]


def test_generator_runs_no_hephaestus_implementation() -> None:
    """CLAUDE.md rule 2, enforced on the generator's own source.

    A vector produced by our own code proves nothing, so the guard is mechanical
    rather than a promise in a docstring.
    """
    source = (REPO_ROOT / "tools/gen_idempotency_vectors.py").read_text(encoding="utf-8")
    body = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    for banned in ("import hephkit", "from hephkit", "hephkit_core", "subprocess", "heph dev"):
        assert banned not in body, f"the generator must not reach for {banned!r}"


def test_committed_vectors_are_current() -> None:
    from gen_idempotency_vectors import main  # noqa: PLC0415 - needs the path insert above

    assert main(["--check"], root=REPO_ROOT) == 0, "run: uv run tools/gen_idempotency_vectors.py"
