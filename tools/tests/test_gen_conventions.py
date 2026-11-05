"""Tests for tools/gen_conventions.py."""

import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen_conventions import OUTPUT_RELPATH, main, render  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ATTRIBUTES = REPO_ROOT / "conventions" / "attributes.yaml"


def _root(tmp_path: Path) -> Path:
    (tmp_path / "conventions").mkdir()
    shutil.copy(ATTRIBUTES, tmp_path / "conventions" / "attributes.yaml")
    (tmp_path / OUTPUT_RELPATH).parent.mkdir(parents=True)
    return tmp_path


def _entries() -> list[dict[str, object]]:
    return yaml.safe_load(ATTRIBUTES.read_text(encoding="utf-8"))


def test_render_is_deterministic() -> None:
    assert render(_entries()) == render(_entries())


def test_generate_twice_gives_identical_bytes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert main([], root=root) == 0
    first = (root / OUTPUT_RELPATH).read_bytes()
    assert main([], root=root) == 0
    assert (root / OUTPUT_RELPATH).read_bytes() == first
    assert first


def test_output_has_header_constants_and_pii_set() -> None:
    text = render(_entries())
    assert "GENERATED" in text and "do not edit" in text.lower()
    assert 'TENANT_ID: Final = "tenant.id"' in text
    assert 'USER_ID: Final = "user.id"' in text
    assert 'IDEMPOTENCY_KEY: Final = "idempotency.key"' in text
    assert 'HEPH_ERROR_CODE: Final = "heph.error.code"' in text
    namespace: dict[str, object] = {}
    exec(text, namespace)  # noqa: S102 - generated, trusted
    assert namespace["PII_ATTRIBUTES"] == frozenset({"user.id"})
    assert namespace["ALL_ATTRIBUTES"] == tuple(str(e["name"]) for e in _entries())


def test_check_passes_when_current_and_exits_1_when_stale(tmp_path: Path, capsys: object) -> None:
    root = _root(tmp_path)
    assert main(["--check"], root=root) == 1  # missing
    assert main([], root=root) == 0
    assert main(["--check"], root=root) == 0
    out = root / OUTPUT_RELPATH
    before = out.read_bytes()
    out.write_text(out.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    stale = out.read_bytes()
    assert main(["--check"], root=root) == 1
    assert out.read_bytes() == stale != before  # --check never writes


def test_check_is_stale_after_registry_change(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert main([], root=root) == 0
    reg = root / "conventions" / "attributes.yaml"
    reg.write_text(reg.read_text(encoding="utf-8").replace("name: job.name\n  type: string\n  description: Name of the background job being executed.\n  pii: false", "name: job.name\n  type: string\n  description: Name of the background job being executed.\n  pii: true"), encoding="utf-8")
    assert main(["--check"], root=root) == 1


def test_invalid_registry_writes_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "conventions" / "attributes.yaml").write_text("- name: Bad Name\n  type: string\n  description: x\n  pii: false\n", encoding="utf-8")
    assert main([], root=root) == 1
    assert not (root / OUTPUT_RELPATH).exists()


def test_unknown_argument_is_usage_error(tmp_path: Path) -> None:
    assert main(["--nope"], root=_root(tmp_path)) == 2
