"""No `hephkit.lab` module may spell an error code as an executable literal.

Error codes live only in `spec/errors.yaml` (CLAUDE.md). `tools/gen_errors.py`
generates them into `hephkit.errors._codes`, `hephkit.errors` re-exports them,
and every `hephkit.lab` module imports them from there. Nothing in `tools/`
enforces that: `gen_errors.py --check` compares the generated file against the
registry and `check_registry.py` validates the YAML, but neither reads module
source, so a hand-written `"HEPH-LAB-422"` would pass every gate in the
repository.

This is the check that closes it, and it covers whichever `lab.*` modules exist
rather than one of them, so the five modules after `lab.config` inherit it
without doing anything.

It walks the AST rather than the text on purpose. Comments do not reach the AST
at all, and docstrings are skipped explicitly, because the rule is about
*executable* literals: a module docstring that explains why an absent config
file is `HEPH-LAB-424` is documentation doing its job, not a second home for a
code. A regex over the file text could not tell the two apart.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "hephkit" / "lab"

#: Any registry code starts with this, so one substring catches every area.
PREFIX = "HEPH-"

#: Nodes that may open with a docstring.
_HOLDERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _docstrings(tree: ast.AST) -> set[int]:
    """The identity of every string constant that is a docstring."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _HOLDERS):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def code_literals(source: str) -> list[str]:
    """Every string constant naming a registry code, docstrings excluded."""
    tree = ast.parse(source)
    skip = _docstrings(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and PREFIX in node.value
        and id(node) not in skip
    ]


def modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_the_scan_has_modules_to_scan() -> None:
    """An empty glob would make the check below pass by covering nothing."""
    assert modules(), f"no python modules found under {PACKAGE}"


def test_no_lab_module_spells_an_error_code() -> None:
    offenders = {
        path.relative_to(PACKAGE).as_posix(): found
        for path in modules()
        if (found := code_literals(path.read_text(encoding="utf-8")))
    }
    assert not offenders, (
        f"error codes spelled in module source: {offenders}. Import them from "
        "hephkit.errors (generated from spec/errors.yaml) instead."
    )


def test_the_scan_catches_a_hand_spelled_literal() -> None:
    """The check biting, demonstrated rather than assumed."""
    assert code_literals('CODE = "HEPH-LAB-422"\n') == ["HEPH-LAB-422"]
    # A wrong literal too, which an identity assertion against the generated
    # constant can never see: it only ever confirms a correct binding.
    assert code_literals('raise ConfigError("x", code="HEPH-LAB-499")\n') == [
        "HEPH-LAB-499"
    ]
    assert code_literals('CODES = ["HEPH-VAL-422", "HEPH-WH-401"]\n') == [
        "HEPH-VAL-422",
        "HEPH-WH-401",
    ]


def test_the_scan_ignores_a_code_named_in_a_docstring_or_a_comment() -> None:
    """Documentation may name a code; only executable literals may not."""
    source = (
        '"""An absent config file is HEPH-LAB-424, not HEPH-LAB-422."""\n'
        "# HEPH-LAB-412 is the integrity gate.\n"
        "from hephkit.errors import LAB_422\n"
        "\n"
        "\n"
        "def f() -> str:\n"
        '    """Raises HEPH-LAB-422."""\n'
        "    return LAB_422\n"
    )
    assert code_literals(source) == []


def test_the_scan_reads_the_real_module_source_it_claims_to() -> None:
    """The real tree is what is scanned, and `config.py` is in it."""
    names = {p.name for p in modules()}
    assert "config.py" in names, names
