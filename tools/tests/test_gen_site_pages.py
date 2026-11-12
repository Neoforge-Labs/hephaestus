"""Tests for tools/gen_site_pages.py."""

import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen_site_pages import (  # noqa: E402
    CONTENT,
    PRIVATE_NAMES,
    _ADR_LINK,
    generate,
    main,
    rewrite_adr_links,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN = REPO_ROOT / "docs/superpowers/specs/2026-11-04-hephaestus-design.md"

# What `rewrite_adr_links` turns an `_ADR_LINK` match into. Kept here rather
# than in the generator: it exists only so a test can find both sides of the
# rewrite. `_ADR_LINK` is imported from the generator, private name and all,
# on purpose -- defining a second copy here would stop the test tracking which
# link prefixes the generator actually accepts, which is the whole point.
_SITE_LINK = re.compile(r"\]\(/adrs/(\d{4}-[a-z0-9-]+)(#[^)\s]*)?\)")


def _page(pages: dict[Path, str], rel: str) -> str:
    return pages[REPO_ROOT / CONTENT / rel]


def _body(text: str) -> str:
    """Everything after the front matter block."""
    assert text.startswith("---\n")
    return text.split("\n---\n", 1)[1].removeprefix("\n")


def _root(tmp_path: Path) -> Path:
    for rel in ("conventions", "spec", "docs/adr", "docs/superpowers/specs"):
        shutil.copytree(REPO_ROOT / rel, tmp_path / rel)
    return tmp_path


def test_conventions_page_lists_every_attribute() -> None:
    attrs = yaml.safe_load((REPO_ROOT / "conventions/attributes.yaml").read_text(encoding="utf-8"))
    text = _page(generate(REPO_ROOT), "reference/conventions.mdx")
    for attr in attrs:
        assert attr["name"] in text
    row = next(line for line in text.splitlines() if "user.id" in line and line.startswith("|"))
    assert "PII" in row
    other = next(line for line in text.splitlines() if "tenant.id" in line and line.startswith("|"))
    assert "PII" not in other


def test_modules_page_splits_shipped_and_planned() -> None:
    mods = yaml.safe_load((REPO_ROOT / "spec/modules.yaml").read_text(encoding="utf-8"))
    text = _page(generate(REPO_ROOT), "reference/modules.mdx")
    shipped_part, planned_part = text.split("## Planned")
    assert "## Shipped" in shipped_part
    assert "| Maturity |" in shipped_part and "| Phase |" in planned_part
    for m in mods:
        own, other = (shipped_part, planned_part) if m["status"] == "shipped" else (planned_part, shipped_part)
        cell = f"\n| `{m['name']}` |"  # first column; a module can share its name with a home
        assert cell in own, m["name"]
        assert cell not in other, m["name"]
    assert "experimental" in shipped_part


def test_modules_page_says_planned_list_is_not_exhaustive() -> None:
    text = _page(generate(REPO_ROOT), "reference/modules.mdx")
    note = text.split("## Planned", 1)[1].split("| Module", 1)[0]
    assert "not exhaustive" in note
    assert "(/roadmap)" in note


def test_adr_pages_match_sources() -> None:
    pages = generate(REPO_ROOT)
    sources = sorted(
        p for p in (REPO_ROOT / "docs/adr").glob("[0-9][0-9][0-9][0-9]-*.md") if not p.name.startswith("0000-")
    )
    assert len(sources) >= 17
    adr_dir = REPO_ROOT / CONTENT / "adrs"
    adr_pages = {p: t for p, t in pages.items() if p.parent == adr_dir and p.suffix == ".md" and p.name != "index.md"}
    assert {p.name for p in adr_pages} == {s.name for s in sources}  # both directions
    for src in sources:
        original = src.read_text(encoding="utf-8")
        rewritten = rewrite_adr_links(original)
        assert _body(adr_pages[adr_dir / src.name]) == rewritten
        # Two properties, because either alone leaves a hole.
        #
        # Masking every link on both sides says "nothing but link targets
        # changed" without pinning a link style: `_ADR_LINK` accepts `./`,
        # `../adr/`, `docs/adr/` and `/docs/adr/` prefixes as well as the bare
        # form, so an ADR written `](../adr/0015-maturity-levels.md)` is legal
        # and reversing the rewrite could not reconstruct it. But masking hides
        # the targets, so a rewrite that sent 0015 to the wrong slug would pass.
        #
        # Comparing the captured (slug, anchor) pairs in order closes that: it
        # checks each link points where its source said, and says nothing about
        # the prefix the source used. A source already containing a literal
        # `](/adrs/...)` link -- none does today -- would be matched by
        # `_SITE_LINK` on the rewritten side and not by `_ADR_LINK` on the
        # source side, so the pair lists would differ in length and the pair
        # comparison would fail loudly rather than mask it.
        #
        # ADR 0021 is the first in the corpus to link to another ADR; before it
        # this read `rewrite_adr_links(original) == original`, on the premise
        # that the rewrite never fires, which that link falsified.
        assert [m.groups() for m in _ADR_LINK.finditer(original)] == [
            m.groups() for m in _SITE_LINK.finditer(rewritten)
        ], f"{src.name}: a cross-ADR link was rewritten to a different target"
        assert _ADR_LINK.sub("]<LINK>", original) == _SITE_LINK.sub("]<LINK>", rewritten)
    order = re.findall(r'"(\d{4}-[^"]+)":', _page(pages, "adrs/_meta.ts"))
    assert order == [s.stem for s in sources]


def _index_targets(text: str) -> list[str]:
    return re.findall(r"\]\(/adrs/([^)]+)\)", text)


def test_adr_index_links_equal_adr_sources() -> None:
    """The /adrs list and docs/adr/ name the same ADRs, in both directions."""
    sources = [
        p.stem
        for p in sorted((REPO_ROOT / "docs/adr").glob("[0-9][0-9][0-9][0-9]-*.md"))
        if not p.name.startswith("0000-")
    ]
    committed = (REPO_ROOT / CONTENT / "adrs/index.md").read_text(encoding="utf-8")
    assert _index_targets(committed) == sources
    assert committed.startswith("---\n# GENERATED") and "docs/adr/*.md" in committed
    for slug in sources:
        assert (REPO_ROOT / CONTENT / "adrs" / f"{slug}.md").is_file()  # no dead link


def test_check_fails_when_a_new_adr_has_no_index_entry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    assert main([], root) == 0
    new = root / "docs/adr/0099-new-decision.md"
    new.write_text("# 0099. New\n\n## Status\n\nAccepted.\n", encoding="utf-8")
    # Give the ADR its page but leave the committed index as it was: only the index is stale.
    pages = generate(root)
    page = root / CONTENT / "adrs/0099-new-decision.md"
    page.write_text(pages[page], encoding="utf-8")
    meta = root / CONTENT / "adrs/_meta.ts"
    meta.write_text(pages[meta], encoding="utf-8")
    assert main(["--check"], root) == 1
    assert "adrs/index.md" in capsys.readouterr().err


def test_check_fails_when_the_index_lists_an_adr_that_does_not_exist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    assert main([], root) == 0
    index = root / CONTENT / "adrs/index.md"
    index.write_text(index.read_text(encoding="utf-8") + "- [0099. Ghost](/adrs/0099-ghost)\n", encoding="utf-8")
    assert main(["--check"], root) == 1
    assert "adrs/index.md" in capsys.readouterr().err


def test_adr_pages_keep_private_names_verbatim() -> None:
    pages = generate(REPO_ROOT)
    joined = "\n".join(t for p, t in pages.items() if "adrs" in p.parts)
    assert any(name in joined for name in PRIVATE_NAMES)  # ADR text is copied verbatim (ruling R4)


def test_adr_cross_references_resolve_to_site_paths() -> None:
    src = (
        "See [ADR 15](0015-maturity-levels.md), [again](./0015-maturity-levels.md#why),\n"
        "[repo](docs/adr/0014-adopt-or-build.md), [up](../adr/0003-name-hephaestus-hephkit.md),\n"
        "[ext](https://example.com/0015-maturity-levels.md), [other](../README.md) and\n"
        "`0015-maturity-levels.md` in code.\n"
    )
    out = rewrite_adr_links(src)
    assert "(/adrs/0015-maturity-levels)" in out
    assert "(/adrs/0015-maturity-levels#why)" in out
    assert "(/adrs/0014-adopt-or-build)" in out
    assert "(/adrs/0003-name-hephaestus-hephkit)" in out
    assert "(https://example.com/0015-maturity-levels.md)" in out
    assert "(../README.md)" in out
    assert "`0015-maturity-levels.md`" in out
    # the rewritten targets are pages the generator really emits
    pages = generate(REPO_ROOT)
    for slug in ("0015-maturity-levels", "0014-adopt-or-build", "0003-name-hephaestus-hephkit"):
        assert REPO_ROOT / CONTENT / "adrs" / f"{slug}.md" in pages


def _spec_version(root: Path) -> str:
    m = re.search(r"^- \*\*Version:\*\* (\S+)$", (root / "spec/heph-spec.md").read_text("utf-8"), re.M)
    assert m
    return m.group(1)


def _spec_note(pages: dict[Path, str], root: Path = REPO_ROOT) -> str:
    """The generated note: everything between the front matter and the synced body."""
    spec = (root / "spec/heph-spec.md").read_text(encoding="utf-8")
    body = _body(pages[root / CONTENT / "spec/index.md"])
    assert body.endswith(spec)  # the body is byte-identical to its source
    note = body.removesuffix(spec)
    assert note.endswith("\n\n")
    return note


def test_spec_page_is_the_spec_body() -> None:
    spec = (REPO_ROOT / "spec/heph-spec.md").read_text(encoding="utf-8")
    pages = generate(REPO_ROOT)
    note = _spec_note(pages)
    assert note.strip()  # the note exists, so this is not trivially the bare body
    assert _body(_page(pages, "spec/index.md")) == note + spec


def test_spec_page_note_names_the_spec_version_and_says_the_two_are_independent() -> None:
    note = _spec_note(generate(REPO_ROOT))
    assert _spec_version(REPO_ROOT) in note
    # the spec version is the only version-like token, and appears once: no package number
    assert _version_tokens(note) == [_spec_version(REPO_ROOT)]
    assert note.count(_spec_version(REPO_ROOT)) == 1
    assert "independent" in note


def _version_tokens(text: str) -> list[str]:
    return re.findall(r"(?<![\w.])v?\d+(?:\.\d+)+", text)


@pytest.mark.parametrize("extra", ["v0.1.0", "0.1.0", "0.1", "v1.2", "the 3.4.5 release"])
def test_version_guard_catches_any_added_version_form(extra: str) -> None:
    note = _spec_note(generate(REPO_ROOT))
    assert _version_tokens(note + f" Package {extra}.") != [_spec_version(REPO_ROOT)]


def test_version_guard_catches_a_package_version_equal_to_the_spec_version() -> None:
    note = _spec_note(generate(REPO_ROOT)) + f" Package {_spec_version(REPO_ROOT)}."
    assert _version_tokens(note) != [_spec_version(REPO_ROOT)]


def test_spec_page_note_follows_the_spec_version(tmp_path: Path) -> None:
    root = _root(tmp_path)
    path = root / "spec/heph-spec.md"
    old = _spec_version(root)
    path.write_text(path.read_text("utf-8").replace(f"**Version:** {old}", "**Version:** 7.8.9", 1), encoding="utf-8")
    note = _spec_note(generate(root), root)
    assert "7.8.9" in note


def test_spec_page_rejects_a_spec_with_no_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    path = root / "spec/heph-spec.md"
    path.write_text(re.sub(r"^- \*\*Version:\*\*.*\n", "", path.read_text("utf-8"), flags=re.M), encoding="utf-8")
    assert main([], root) == 1
    err = capsys.readouterr().err
    assert "spec/heph-spec.md" in err and "Traceback" not in err


def test_check_detects_hand_edit_of_the_spec_note(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    assert main([], root) == 0
    target = root / CONTENT / "spec/index.md"
    note = _spec_note(generate(root), root)
    target.write_text(target.read_text("utf-8").replace(note, note.replace("independent", "the same"), 1), encoding="utf-8")
    assert main(["--check"], root) == 1
    assert "spec/index.md" in capsys.readouterr().err


def test_roadmap_derives_from_the_design() -> None:
    design = DESIGN.read_text(encoding="utf-8")
    rollout = design.split("\n## Rollout\n", 1)[1].split("\n## ", 1)[0]
    steps = re.findall(r"^\d+\. \*\*(.+?)\.\*\*", rollout, re.M)
    assert len(steps) == 7  # the on-demand item is not a phase
    text = _page(generate(REPO_ROOT), "roadmap.mdx")
    positions = []
    for step in steps:
        label = step.split(":", 1)[1].strip()
        if any(name in label for name in PRIVATE_NAMES):
            label = "Product core"  # the roadmap's capability name for the first-product phase
        assert label.lower() in text.lower(), label
        positions.append(text.lower().index(label.lower()))
    assert positions == sorted(positions)
    for name in PRIVATE_NAMES:
        assert name not in text, name  # the roadmap names phases by capability


def test_generated_notice_leads_every_output() -> None:
    for path, text in generate(REPO_ROOT).items():
        if path.suffix in {".md", ".mdx"}:
            assert text.startswith("---\n# GENERATED FILE"), path
            assert "do not edit" in text.split("\n---\n", 1)[0].lower(), path
        else:
            assert "GENERATED FILE" in text, path


def test_output_is_deterministic() -> None:
    assert generate(REPO_ROOT) == generate(REPO_ROOT)


def test_committed_pages_are_current() -> None:
    assert main(["--check"], REPO_ROOT) == 0


def test_check_detects_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    assert main([], root) == 0
    assert main(["--check"], root) == 0
    (root / "docs/adr/0099-new-decision.md").write_text("# 0099. New\n\n## Status\n\nAccepted.\n", encoding="utf-8")
    assert main(["--check"], root) == 1
    assert "0099-new-decision" in capsys.readouterr().err


@pytest.mark.parametrize(
    "rel",
    [
        "reference/conventions.mdx",
        "reference/modules.mdx",
        "reference/_meta.ts",
        "spec/index.md",
        "roadmap.mdx",
        "adrs/0015-maturity-levels.md",
        "adrs/_meta.ts",
        "adrs/index.md",
    ],
)
def test_check_detects_hand_edit_of_each_output_kind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rel: str
) -> None:
    root = _root(tmp_path)
    assert main([], root) == 0
    target = root / CONTENT / rel
    target.write_text(target.read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8")
    assert main(["--check"], root) == 1
    assert rel in capsys.readouterr().err


def test_check_detects_orphan_adr_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    assert main([], root) == 0
    (root / "docs/adr/0017-full-iso-4217-currency-table.md").unlink()
    assert main(["--check"], root) == 1
    assert "0017-full-iso-4217-currency-table" in capsys.readouterr().err


def _design_edit(root: Path, old: str, new: str) -> None:
    design = root / "docs/superpowers/specs/2026-11-04-hephaestus-design.md"
    text = design.read_text(encoding="utf-8")
    assert old in text, old
    design.write_text(text.replace(old, new, 1), encoding="utf-8")


def _item8(root: Path) -> str:
    design = (root / "docs/superpowers/specs/2026-11-04-hephaestus-design.md").read_text(encoding="utf-8")
    return next(line for line in design.splitlines() if line.startswith("8. **On demand"))


def test_check_does_not_remove_or_pass_hand_written_pages(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    assert main([], root) == 0
    notes = root / CONTENT / "reference/notes.mdx"
    notes.write_text("# My notes\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["--check"], root) == 1
    assert "reference/notes.mdx" in capsys.readouterr().err
    assert notes.read_text(encoding="utf-8") == "# My notes\n"


def test_write_keeps_and_reports_hand_written_pages(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    assert main([], root) == 0
    notes = root / CONTENT / "reference/notes.mdx"
    notes.write_text("# My notes\n", encoding="utf-8")
    capsys.readouterr()
    main([], root)
    assert notes.read_text(encoding="utf-8") == "# My notes\n"  # a generator never deletes a human's file
    assert "reference/notes.mdx" in capsys.readouterr().err


def test_write_still_removes_generated_orphans(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert main([], root) == 0
    adr = root / "docs/adr/0017-full-iso-4217-currency-table.md"
    page = root / CONTENT / "adrs" / adr.name
    assert page.is_file()
    adr.unlink()
    assert main([], root) == 0
    assert not page.exists()  # carries the generated marker, so it is ours to remove


def test_roadmap_requires_exactly_eight_items_the_last_on_demand(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ninth = "9. **Weeks 14: Something else.** Not in the design.\n"
    root = _root(tmp_path / "nine")
    _design_edit(root, _item8(root) + "\n", _item8(root) + "\n" + ninth)
    assert main([], root) == 1
    assert "eight" in capsys.readouterr().err

    root = _root(tmp_path / "six")
    _design_edit(root, [line for line in _item8(root).splitlines()][0] + "\n", "")
    seventh = next(
        line
        for line in (root / "docs/superpowers/specs/2026-11-04-hephaestus-design.md").read_text("utf-8").splitlines()
        if line.startswith("7. **")
    )
    _design_edit(root, seventh + "\n", "")
    assert main([], root) == 1
    assert "eight" in capsys.readouterr().err

    root = _root(tmp_path / "renumbered")  # eight items, but the last is a phase, not the backlog
    _design_edit(root, "**On demand, entering as experimental:**", "**Week 14: One more phase.**")
    assert main([], root) == 1
    assert "On demand" in capsys.readouterr().err


def test_roadmap_fails_when_a_step_names_a_private_product(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    _design_edit(root, "**Weeks 3–4: Collie core (product).**", "**Weeks 3–4: Domus core.**")
    assert main([], root) == 1
    assert "Domus" in capsys.readouterr().err
    assert not (root / CONTENT / "roadmap.mdx").exists()  # nothing half-written


def test_roadmap_fails_when_a_capability_override_goes_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    _design_edit(root, "**Weeks 3–4: Collie core (product).**", "**Weeks 3–4: Core build.**")
    assert main([], root) == 1  # no private name any more, but the override no longer matches anything
    assert "Collie core (product)" in capsys.readouterr().err


def _modules_root(tmp_path: Path, change) -> Path:
    root = _root(tmp_path)
    path = root / "spec/modules.yaml"
    mods = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(next(m for m in mods if m["status"] == "shipped"))
    path.write_text(yaml.safe_dump(mods), encoding="utf-8")
    return root


def test_modules_page_rejects_an_unknown_maturity(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _modules_root(tmp_path, lambda m: m.update(maturity="alpha"))
    name = next(m["name"] for m in yaml.safe_load((root / "spec/modules.yaml").read_text("utf-8")) if m.get("maturity") == "alpha")
    assert main([], root) == 1
    err = capsys.readouterr().err
    assert name in err and "alpha" in err and "Traceback" not in err


def test_modules_page_rejects_a_missing_maturity(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _modules_root(tmp_path, lambda m: m.pop("maturity"))
    name = next(m["name"] for m in yaml.safe_load((root / "spec/modules.yaml").read_text("utf-8")) if m["status"] == "shipped" and "maturity" not in m)
    assert main([], root) == 1
    err = capsys.readouterr().err
    assert name in err and "maturity" in err and "Traceback" not in err
