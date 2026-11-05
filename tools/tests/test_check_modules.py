"""Tests for tools/check_modules.py."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_modules import check_modules  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

SPEC = "# heph-spec\n\n## 1. Errors\n\n## 2. Idempotency\n\n## 7. Provenance record\n"


def make_tree(tmp_path: Path, entries: list[dict], dirs=(), files=()) -> Path:
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "heph-spec.md").write_text(SPEC, encoding="utf-8")
    (tmp_path / "spec" / "modules.yaml").write_text(yaml.safe_dump(entries), encoding="utf-8")
    for d in dirs:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    for f, text in files:
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def planned(name="later"):
    return {"name": name, "home": "python", "status": "planned", "spec_section": None, "phase": 2}


def shipped(name, home, **kw):
    base = {"name": name, "home": home, "status": "shipped", "maturity": "experimental", "spec_section": None}
    return {**base, **kw}


def test_registry_is_valid():
    assert check_modules(REPO_ROOT) == []


def test_every_on_disk_module_has_an_entry(tmp_path):
    root = make_tree(
        tmp_path,
        [planned()],
        files=[("compose/kafka.yaml", "# Kafka. maturity: experimental\n")],
    )
    assert any("kafka" in e for e in check_modules(root))


def test_python_package_directory_needs_an_entry(tmp_path):
    root = make_tree(
        tmp_path,
        [planned()],
        files=[("python/hephkit/src/hephkit/pkg/__init__.py", "")],
    )
    assert any("pkg" in e for e in check_modules(root))


def test_go_command_directory_needs_an_entry(tmp_path):
    root = make_tree(tmp_path, [planned()], dirs=["go/cmd/heph"])
    assert any("go/heph" in e for e in check_modules(root))


def test_scan_exclusions_are_not_required(tmp_path):
    root = make_tree(
        tmp_path,
        [planned()],
        dirs=["core/fuzz", "core/target", "docker/test", "python/hephkit/src/hephkit/__pycache__"],
        files=[
            ("python/hephkit/src/hephkit/conventions.py", ""),
            ("python/hephkit/src/hephkit/_core.pyi", ""),
        ],
    )
    assert check_modules(root) == []


def test_maturity_matches_compose_header(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("telemetry", "compose"), planned()],
        files=[("compose/telemetry.yaml", "# Something. maturity: beta\nservices: {}\n")],
    )
    errors = check_modules(root)
    assert any("telemetry" in e and "beta" in e for e in errors)


def test_matching_compose_header_is_valid(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("telemetry", "compose"), planned()],
        files=[("compose/telemetry.yaml", "# Something. maturity: experimental\n")],
    )
    assert check_modules(root) == []


def test_shipped_requires_maturity_planned_requires_phase(tmp_path):
    no_maturity = {"name": "aaa", "home": "python", "status": "shipped", "spec_section": None}
    planned_with_maturity = {**planned("bbb"), "maturity": "experimental"}
    planned_without_phase = {k: v for k, v in planned("ccc").items() if k != "phase"}
    errors = check_modules(
        make_tree(tmp_path, [no_maturity, planned_with_maturity, planned_without_phase])
    )
    assert any("aaa" in e and "maturity" in e for e in errors)
    assert any("bbb" in e and "maturity" in e for e in errors)
    assert any("ccc" in e and "phase" in e for e in errors)


def test_spec_section_resolves(tmp_path):
    entries = [planned(), shipped("x", "python", spec_section="9")]
    assert any("'9'" in e for e in check_modules(make_tree(tmp_path, entries)))


def test_ledger_has_both_sides(tmp_path):
    errors = check_modules(make_tree(tmp_path, [shipped("x", "python")]))
    assert any("no planned" in e for e in errors)
