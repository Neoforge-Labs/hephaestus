"""Tests for tools/gen_errors.py."""

import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen_errors import OUTPUT_RELPATH, main, render  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ERRORS = REPO_ROOT / "spec" / "errors.yaml"


def _root(tmp_path: Path) -> Path:
    (tmp_path / "spec").mkdir()
    shutil.copy(ERRORS, tmp_path / "spec" / "errors.yaml")
    (tmp_path / OUTPUT_RELPATH).parent.mkdir(parents=True)
    return tmp_path


def _entries() -> list[dict[str, object]]:
    return yaml.safe_load(ERRORS.read_text(encoding="utf-8"))


def test_render_is_deterministic() -> None:
    assert render(_entries()) == render(_entries())


def test_generate_twice_gives_identical_bytes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert main([], root=root) == 0
    first = (root / OUTPUT_RELPATH).read_bytes()
    assert main([], root=root) == 0
    assert (root / OUTPUT_RELPATH).read_bytes() == first
    assert first  # not vacuous


def test_output_has_header_constants_and_registry() -> None:
    text = render(_entries())
    assert "GENERATED" in text and "do not edit" in text.lower()
    assert 'IDEMP_409: Final = "HEPH-IDEMP-409"' in text
    assert 'MONEY_422: Final = "HEPH-MONEY-422"' in text
    assert "REGISTRY: dict[str, tuple[int, str]]" in text
    assert '"HEPH-IDEMP-409": (409, "Original request still in flight")' in text
    assert "DETAIL_HINTS: dict[str, str]" in text
    assert '"HEPH-IDEMP-409": "A request with this key is still being processed. Retry after it completes."' in text
    compile(text, "_codes.py", "exec")


def test_registry_covers_every_code() -> None:
    namespace: dict[str, object] = {}
    exec(render(_entries()), namespace)  # noqa: S102 - generated, trusted
    registry = namespace["REGISTRY"]
    assert isinstance(registry, dict)
    assert set(registry) == {e["code"] for e in _entries()}


def test_check_passes_on_fresh_file_and_fails_on_stale(tmp_path: Path) -> None:
    root = _root(tmp_path)
    out = root / OUTPUT_RELPATH
    assert main([], root=root) == 0
    assert main(["--check"], root=root) == 0  # fresh

    out.write_text(out.read_text(encoding="utf-8") + "# hand edit\n", encoding="utf-8")
    assert main(["--check"], root=root) == 1  # edited
    assert out.read_text(encoding="utf-8").endswith("# hand edit\n")  # --check never writes

    out.unlink()
    assert main(["--check"], root=root) == 1  # missing


def test_check_fails_when_registry_changes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert main([], root=root) == 0
    path = root / "spec" / "errors.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("Validation failed", "Validation broke"))
    assert main(["--check"], root=root) == 1


def test_invalid_registry_is_refused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "spec" / "errors.yaml").write_text("- code: nope\n  status: 200\n", encoding="utf-8")
    assert main([], root=root) == 1
    assert not (root / OUTPUT_RELPATH).exists()


def test_committed_file_is_fresh() -> None:
    assert main(["--check"], root=REPO_ROOT) == 0
