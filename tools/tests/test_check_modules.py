"""Tests for tools/check_modules.py."""

import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_modules import LABELLED_HOMES, check_modules  # noqa: E402

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
        files=[("compose/kafka.yaml", "# Kafka. maturity: experimental\nservices: {}\n")],
    )
    assert any("kafka" in e for e in check_modules(root))


def test_python_package_directory_needs_an_entry(tmp_path):
    root = make_tree(
        tmp_path,
        [planned()],
        files=[("python/hephkit/src/hephkit/pkg/__init__.py", "")],
    )
    assert any("pkg" in e for e in check_modules(root))


@pytest.mark.parametrize(
    ("directory", "name"),
    [
        ("core/newcrate", "newcrate"),
        ("go/internal/newpkg", "newpkg"),
        ("docker/newimg", "newimg"),
    ],
)
def test_scanned_directory_needs_an_entry(tmp_path, directory, name):
    root = make_tree(tmp_path, [planned()], dirs=[directory])
    assert any(name in e for e in check_modules(root))


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
        files=[("compose/telemetry.yaml", "# Something. maturity: experimental\nservices: {}\n")],
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


def test_yml_compose_fragment_needs_an_entry(tmp_path):
    root = make_tree(
        tmp_path,
        [planned()],
        files=[("compose/foo.yml", "# Foo. maturity: experimental\nservices: {}\n")],
    )
    assert any("foo" in e for e in check_modules(root))


def test_yml_compose_header_must_match_entry(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("foo", "compose"), planned()],
        files=[("compose/foo.yml", "# Foo. maturity: beta\nservices: {}\n")],
    )
    assert any("foo" in e and "beta" in e for e in check_modules(root))


def test_moon_project_config_is_not_a_fragment(tmp_path):
    root = make_tree(tmp_path, [planned()], files=[("compose/moon.yml", "language: unknown\ntasks: {}\n")])
    assert check_modules(root) == []


def test_unrecognised_compose_file_is_reported_not_skipped(tmp_path):
    root = make_tree(tmp_path, [planned()], files=[("compose/tooling.yml", "language: unknown\n")])
    errors = check_modules(root)
    assert any("tooling.yml" in e and "services" in e for e in errors), errors


def test_fragment_missing_services_is_reported(tmp_path):
    root = make_tree(
        tmp_path, [shipped("foo", "compose"), planned()], files=[("compose/foo.yaml", "# Foo. maturity: experimental\n")]
    )
    assert any("foo.yaml" in e and "services" in e for e in check_modules(root))


def test_undecodable_compose_fragment_is_an_error_not_a_traceback(tmp_path):
    root = make_tree(tmp_path, [shipped("foo", "compose"), planned()])
    (root / "compose").mkdir()
    (root / "compose" / "foo.yaml").write_bytes(b"# \xff\xfe maturity: experimental\n")
    errors = check_modules(root)
    assert any("foo" in e and "cannot read" in e for e in errors), errors


def test_header_read_failure_returns_an_error_string(tmp_path):
    from check_modules import _compose_header_maturity

    bad = tmp_path / "foo.yaml"
    bad.write_bytes(b"\xff\xfe")
    header, err = _compose_header_maturity(bad)
    assert header is None and err and "foo" in err


# --- in-source maturity labels (rust, python, go) ---------------------------------------------

# (home, name) -> (path, text template with {m}) for a minimal labelled module.
LABELLED = {
    ("rust", "foo"): ("core/foo/src/lib.rs", "//! Foo crate. Maturity: {m}.\n\npub fn f() {{}}\n"),
    ("python", "foo"): ("python/hephkit/src/hephkit/foo.py", '"""Foo module. Maturity: {m}."""\n\nX = 1\n'),
    ("python", "pkg"): ("python/hephkit/src/hephkit/pkg/__init__.py", '"""Pkg. Maturity: {m}."""\n'),
    ("go", "foo"): ("go/internal/foo/foo.go", "// Package foo does things. Maturity: {m}.\npackage foo\n"),
    ("go", "cmd1"): ("go/cmd/cmd1/main.go", "// Command cmd1 runs.\n// Maturity: {m}.\npackage main\n"),
}
LABEL_IDS = [f"{h}-{n}" for h, n in LABELLED]


def labelled_tree(tmp_path, home, name, label_level, registry_level="experimental"):
    path, template = LABELLED[(home, name)]
    text = template.format(m=label_level)
    return make_tree(
        tmp_path,
        [shipped(name, home, maturity=registry_level), planned()],
        files=[(path, text)],
    )


@pytest.mark.parametrize(("home", "name"), list(LABELLED), ids=LABEL_IDS)
def test_matching_source_label_is_valid(tmp_path, home, name):
    assert check_modules(labelled_tree(tmp_path, home, name, "experimental")) == []


@pytest.mark.parametrize(("home", "name"), list(LABELLED), ids=LABEL_IDS)
def test_source_label_that_disagrees_is_a_mismatch(tmp_path, home, name):
    errors = check_modules(labelled_tree(tmp_path, home, name, "beta"))
    path = LABELLED[(home, name)][0]
    assert any(
        name in e and Path(path).name in e and "'beta'" in e and "'experimental'" in e and "mismatch" in e
        for e in errors
    ), errors
    assert not any("no Maturity label" in e for e in errors), errors


@pytest.mark.parametrize(("home", "name"), list(LABELLED), ids=LABEL_IDS)
def test_unlabelled_source_is_reported_as_missing(tmp_path, home, name):
    path, template = LABELLED[(home, name)]
    unlabelled = template.format(m="experimental").replace(" Maturity: experimental.", "")
    root = make_tree(tmp_path, [shipped(name, home), planned()], files=[(path, unlabelled)])
    errors = check_modules(root)
    assert any(name in e and "no Maturity label" in e and Path(path).name in e for e in errors), errors
    assert not any("mismatch" in e for e in errors), errors


@pytest.mark.parametrize(
    ("home", "name", "path", "text"),
    [
        ("python", "foo", "python/hephkit/src/hephkit/foo.py", '# Maturity: experimental\n"""Foo."""\n'),
        ("python", "foo", "python/hephkit/src/hephkit/foo.py", '"""Foo."""\n# Maturity: experimental\n'),
        ("rust", "foo", "core/foo/src/lib.rs", "// Maturity: experimental\n//! Foo.\n"),
        ("rust", "foo", "core/foo/src/lib.rs", "//! Foo.\n\nfn f() {}\n// Maturity: experimental\n"),
        ("go", "foo", "go/internal/foo/foo.go", "// Maturity: experimental.\n\n// Package foo does things.\npackage foo\n"),
        ("go", "foo", "go/internal/foo/foo.go", "// Package foo.\npackage foo\n\n// Maturity: experimental.\nfunc F() {}\n"),
    ],
    ids=["py-hash-above", "py-comment-below", "rs-plain-comment", "rs-after-code", "go-detached", "go-on-func"],
)
def test_label_outside_the_doc_comment_does_not_count(tmp_path, home, name, path, text):
    root = make_tree(tmp_path, [shipped(name, home), planned()], files=[(path, text)])
    assert any(name in e and "no Maturity label" in e for e in check_modules(root)), check_modules(root)


def test_go_label_may_sit_in_any_non_test_file_of_the_package(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("foo", "go"), planned()],
        files=[
            ("go/internal/foo/a.go", "package foo\n"),
            ("go/internal/foo/b.go", "// Package foo does things. Maturity: experimental.\npackage foo\n"),
        ],
    )
    assert check_modules(root) == []


def test_go_test_file_label_does_not_count(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("foo", "go"), planned()],
        files=[
            ("go/internal/foo/a.go", "package foo\n"),
            ("go/internal/foo/a_test.go", "// Package foo. Maturity: experimental.\npackage foo\n"),
        ],
    )
    assert any("foo" in e and "no Maturity label" in e for e in check_modules(root))


def test_go_conflicting_labels_in_one_package_are_reported(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("foo", "go"), planned()],
        files=[
            ("go/internal/foo/a.go", "// Package foo. Maturity: experimental.\npackage foo\n"),
            ("go/internal/foo/b.go", "// Package foo. Maturity: stable.\npackage foo\n"),
        ],
    )
    assert any("foo" in e and "b.go" in e and "mismatch" in e for e in check_modules(root))


def test_wrong_case_label_is_a_mismatch(tmp_path):
    root = labelled_tree(tmp_path, "rust", "foo", "Experimental")
    assert any("foo" in e and "mismatch" in e for e in check_modules(root))


def test_shipped_row_with_no_source_on_disk_is_reported(tmp_path):
    root = make_tree(tmp_path, [shipped("ghost", "python"), planned()])
    assert any("ghost" in e and "no source" in e for e in check_modules(root))


def test_python_syntax_error_is_an_error_not_a_traceback(tmp_path):
    root = make_tree(
        tmp_path, [shipped("foo", "python"), planned()], files=[("python/hephkit/src/hephkit/foo.py", "def (:\n")]
    )
    assert any("foo" in e and "cannot parse" in e for e in check_modules(root))


def test_docker_rows_are_not_label_checked(tmp_path):
    # Docker images have no doc-comment convention (undecided), so they are deliberately unchecked.
    root = make_tree(tmp_path, [shipped("img", "docker"), planned()], dirs=["docker/img"])
    assert check_modules(root) == []


def test_ts_and_planned_rows_are_not_label_checked(tmp_path):
    root = make_tree(tmp_path, [planned("later"), shipped("pkgs", "ts")])
    assert not any("pkgs" in e and "Maturity" in e for e in check_modules(root))


# Acceptance bar: removing the label from any one real module fails by name.
_REAL_ROWS = [
    (e["home"], e["name"])
    for e in yaml.safe_load((REPO_ROOT / "spec" / "modules.yaml").read_text(encoding="utf-8"))
    if e.get("status") == "shipped" and e.get("home") in LABELLED_HOMES
]
assert _REAL_ROWS, "no shipped rows parsed from spec/modules.yaml; the label tests would cover nothing"
_LABEL_RE = re.compile(r"[ \t]*Maturity:\s*[a-z]+\.?")


@pytest.mark.parametrize(("home", "name"), _REAL_ROWS, ids=[f"{h}-{n}" for h, n in _REAL_ROWS])
def test_removing_the_label_from_a_real_module_fails_the_check(tmp_path, home, name):
    ignore = shutil.ignore_patterns("target", ".venv", "__pycache__", "node_modules", "*.so", "*.dylib")
    for d in ("spec", "core", "go", "docker", "compose"):
        shutil.copytree(REPO_ROOT / d, tmp_path / d, ignore=ignore)
    shutil.copytree(
        REPO_ROOT / "python" / "hephkit" / "src",
        tmp_path / "python" / "hephkit" / "src",
        ignore=ignore,
    )
    assert check_modules(tmp_path) == []  # the copy starts valid

    if home == "python":
        base = tmp_path / "python" / "hephkit" / "src" / "hephkit"
        files = [base / f"{name}.py", base / name / "__init__.py"]
    elif home == "rust":
        files = sorted((tmp_path / "core" / name / "src").rglob("*.rs"))
    else:
        files = sorted(
            [*(tmp_path / "go" / "internal" / name).glob("*.go"), *(tmp_path / "go" / "cmd" / name).glob("*.go")]
        )
    stripped = 0
    for f in files:
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            new = _LABEL_RE.sub("", text)
            if new != text:
                f.write_text(new, encoding="utf-8")
                stripped += 1
    assert stripped, f"no label found to strip for {home}/{name}"
    errors = check_modules(tmp_path)
    assert any(name in e and "no Maturity label" in e for e in errors), errors


# --- dotted names resolve in the second python tree (hephkit-lab) ------------------------------

LAB_SRC = "python/hephkit-lab/src/hephkit/lab"


def test_dotted_python_name_resolves_in_lab_tree(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("lab.config", "python"), planned()],
        files=[(f"{LAB_SRC}/config.py", '"""Config. Maturity: experimental."""\n')],
    )
    assert check_modules(root) == []


def test_dotted_python_package_resolves_via_init(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("lab.record", "python"), planned()],
        files=[(f"{LAB_SRC}/record/__init__.py", '"""Record. Maturity: experimental."""\n')],
    )
    assert check_modules(root) == []


def test_dotted_name_missing_maturity_label_is_an_error(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("lab.config", "python"), planned()],
        files=[(f"{LAB_SRC}/config.py", '"""Config."""\n')],
    )
    assert any("lab.config" in e and "no Maturity label" in e for e in check_modules(root))


def test_dotted_name_label_mismatch_is_an_error(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("lab.config", "python"), planned()],
        files=[(f"{LAB_SRC}/config.py", '"""Config. Maturity: beta."""\n')],
    )
    assert any("lab.config" in e and "mismatch" in e for e in check_modules(root))


def test_dotted_name_does_not_resolve_in_the_core_tree(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("lab.config", "python"), planned()],
        files=[("python/hephkit/src/hephkit/lab/config.py", '"""Config. Maturity: experimental."""\n')],
    )
    assert any("lab.config" in e and "no source" in e for e in check_modules(root))


def test_undotted_name_does_not_resolve_in_the_lab_tree(tmp_path):
    root = make_tree(
        tmp_path,
        [shipped("config", "python"), planned()],
        files=[(f"{LAB_SRC}/config.py", '"""Config. Maturity: experimental."""\n')],
    )
    assert any("config" in e and "no source" in e for e in check_modules(root))


def test_module_on_disk_without_a_row_is_still_caught_in_lab_tree(tmp_path):
    root = make_tree(tmp_path, [planned()], files=[(f"{LAB_SRC}/orphan.py", "")])
    assert any("python/lab.orphan" in e and "no shipped entry" in e for e in check_modules(root))


def test_lab_package_directory_without_a_row_is_caught(tmp_path):
    root = make_tree(tmp_path, [planned()], files=[(f"{LAB_SRC}/pkg/__init__.py", "")])
    assert any("python/lab.pkg" in e for e in check_modules(root))


def test_lab_tree_private_files_are_not_required(tmp_path):
    root = make_tree(
        tmp_path,
        [planned()],
        dirs=[f"{LAB_SRC}/__pycache__"],
        files=[(f"{LAB_SRC}/__init__.py", ""), (f"{LAB_SRC}/_internal.py", "")],
    )
    assert check_modules(root) == []
