"""The tutorial page and the proof block come from the script CI runs."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen_quickstart import (  # noqa: E402
    BUDGET_RELPATH,
    CLOSE_MARKER,
    OPEN_MARKER,
    SCRIPT_RELPATH,
    extract_commands,
    generate,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / SCRIPT_RELPATH


def test_commands_come_from_the_script() -> None:
    """The extracted commands are the script's own lines, not a copy of them."""
    text = SCRIPT.read_text(encoding="utf-8")
    body = text.split(OPEN_MARKER, 1)[1].split(CLOSE_MARKER, 1)[0]
    expected = [line.strip() for line in body.splitlines() if line.strip() and not line.strip().startswith("#")]
    assert extract_commands(text) == expected
    assert expected, "the quickstart block is empty"


def test_every_extracted_command_appears_in_the_published_page() -> None:
    pages = generate(REPO_ROOT)
    page = next(text for path, text in pages.items() if path.suffix == ".mdx")
    for command in extract_commands(SCRIPT.read_text(encoding="utf-8")):
        assert command in page, f"the page does not print {command!r}"


def test_marker_missing_is_an_error() -> None:
    with pytest.raises(ValueError, match="expected exactly one"):
        extract_commands("#!/usr/bin/env bash\necho hi\n")


def test_duplicate_markers_are_an_error() -> None:
    doubled = f"{OPEN_MARKER}\na\n{CLOSE_MARKER}\n{OPEN_MARKER}\nb\n{CLOSE_MARKER}\n"
    with pytest.raises(ValueError, match="expected exactly one"):
        extract_commands(doubled)


def test_empty_block_is_an_error() -> None:
    with pytest.raises(ValueError, match="holds no commands"):
        extract_commands(f"{OPEN_MARKER}\n# only a comment\n{CLOSE_MARKER}\n")


def test_check_detects_drift(tmp_path: Path) -> None:
    """--check fails, and writes nothing, when a published file is stale."""
    root = tmp_path
    (root / SCRIPT_RELPATH).parent.mkdir(parents=True)
    (root / SCRIPT_RELPATH).write_text(f"{OPEN_MARKER}\nuv add hephkit\n{CLOSE_MARKER}\n", encoding="utf-8")
    # The snippet carries the budget too, so a fixture root needs both sources.
    (root / BUDGET_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    (root / BUDGET_RELPATH).write_text(
        json.dumps({"boot_seconds": 60, "boot_what": "x", "wheel_mb": 5, "wheel_target": "y"}),
        encoding="utf-8",
    )
    assert main(["--check"], root=root) == 1  # nothing generated yet
    assert main([], root=root) == 0
    assert main(["--check"], root=root) == 0

    # Change the script; the committed page is now stale.
    (root / SCRIPT_RELPATH).write_text(
        f"{OPEN_MARKER}\nuv add hephkit\nheph dev up\n{CLOSE_MARKER}\n", encoding="utf-8"
    )
    assert main(["--check"], root=root) == 1


def test_output_is_deterministic(tmp_path: Path) -> None:
    first = generate(REPO_ROOT)
    second = generate(REPO_ROOT)
    assert first == second


def test_committed_output_is_current() -> None:
    assert main(["--check"], root=REPO_ROOT) == 0, "run: uv run tools/gen_quickstart.py"


def test_the_script_runs_the_commands_it_publishes() -> None:
    """The block is executed, not merely listed.

    The value of this file is that CI runs what the docs print. A block that had
    drifted into a decorative comment would still generate a page, and the page
    would still look verified, so the loop that executes it is asserted here.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'done <<<"$QUICKSTART"' in text, "the published commands are not executed by a loop"
    assert 'eval "$cmd"' in text, "the loop does not run the commands"


def test_only_the_server_line_is_treated_specially() -> None:
    """Exactly one published command diverges, and it is the documented one."""
    commands = extract_commands(SCRIPT.read_text(encoding="utf-8"))
    backgrounded = [c for c in commands if "fastapi dev" in c]
    assert len(backgrounded) == 1, "expected exactly one long-running server command"
    text = SCRIPT.read_text(encoding="utf-8")
    # The runner's one special case matches that command and nothing else.
    assert "*'fastapi dev'*)" in text
    assert text.count("server_pid=$!") == 1


def test_the_shell_script_parses() -> None:
    """A tutorial that cannot be parsed cannot have been run."""
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_published_install_command_names_the_extras_the_app_imports() -> None:
    """The app imports HephSettings, which lives behind the `settings` extra.

    An earlier draft of the plan published `hephkit[fastapi,observability]`.
    That resolves and even imports `hephkit.observability`, but
    `from hephkit.settings import HephSettings` then fails with
    ModuleNotFoundError: pydantic_settings -- so the tutorial's very first run
    would have died on an import. Keep every extra the example actually uses.
    """
    commands = extract_commands(SCRIPT.read_text(encoding="utf-8"))
    install = next(c for c in commands if c.startswith("uv add"))
    app = (REPO_ROOT / "examples/hello/app.py").read_text(encoding="utf-8")
    for extra, module in (("fastapi", "hephkit.errors.fastapi"), ("observability", "hephkit.observability"), ("settings", "hephkit.settings")):
        if module in app:
            assert extra in install, f"app.py imports {module} but the install command omits [{extra}]"
