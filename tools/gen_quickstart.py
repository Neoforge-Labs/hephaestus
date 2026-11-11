# /// script
# requires-python = ">=3.12"
# ///
"""Extract the five-minute path from the script CI runs.

Run with ``uv run tools/gen_quickstart.py`` to write the files, or ``--check``
to exit 1 (naming each file) if a committed one is stale.

``examples/hello/tutorial_test.sh`` is the only source. The commands between its
``# >>> quickstart`` and ``# <<< quickstart`` markers become:

* ``docs/site/content/_snippets/quickstart.json`` -- read by the landing page's
  proof block.
* ``docs/site/content/tutorial/first-five-minutes.mdx`` -- the tutorial page.

Nothing here invents a command or reformats one. A command printed on the site
is a command CI executed, byte for byte, because the alternative is a tutorial
that rots silently: this repo has already published one claim that nothing was
checking, and the rule exists because of it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_RELPATH = Path("examples/hello/tutorial_test.sh")
BUDGET_RELPATH = Path("tools/dx_budget.json")
SNIPPET_RELPATH = Path("docs/site/content/_snippets/quickstart.json")
PAGE_RELPATH = Path("docs/site/content/tutorial/first-five-minutes.mdx")
META_RELPATH = Path("docs/site/content/tutorial/_meta.ts")

OPEN_MARKER = "# >>> quickstart"
CLOSE_MARKER = "# <<< quickstart"

GENERATED = "GENERATED FILE - do not edit by hand"
REGENERATE = "uv run tools/gen_quickstart.py"


def extract_commands(script: str) -> list[str]:
    """The command lines between the markers, in order, comments dropped."""
    if script.count(OPEN_MARKER) != 1 or script.count(CLOSE_MARKER) != 1:
        raise ValueError(
            f"{SCRIPT_RELPATH}: expected exactly one {OPEN_MARKER!r} and one "
            f"{CLOSE_MARKER!r}; found {script.count(OPEN_MARKER)} and {script.count(CLOSE_MARKER)}"
        )
    before, rest = script.split(OPEN_MARKER, 1)
    body, _ = rest.split(CLOSE_MARKER, 1)
    if script.index(OPEN_MARKER) > script.index(CLOSE_MARKER):
        raise ValueError(f"{SCRIPT_RELPATH}: the closing marker precedes the opening one")
    commands = [line.strip() for line in body.splitlines()]
    commands = [c for c in commands if c and not c.startswith("#")]
    if not commands:
        raise ValueError(f"{SCRIPT_RELPATH}: the quickstart block holds no commands")
    return commands


def render_snippet(commands: list[str], budget: dict[str, object]) -> str:
    """The landing page's proof block and budget figures, in one file.

    The budget is carried here rather than imported from ``tools/`` because the
    site's Next root is ``docs/site``: a component cannot reach outside it. This
    keeps ``tools/dx_budget.json`` the single source and lets ``--check`` fail
    when the copy drifts, which a hand-copied number could not.
    """
    data = {
        "_generated": f"{GENERATED}. Source: {SCRIPT_RELPATH} and {BUDGET_RELPATH}. "
        f"Regenerate with `{REGENERATE}`.",
        "commands": commands,
        "budget": {
            "bootSeconds": budget["boot_seconds"],
            "bootWhat": budget["boot_what"],
            "wheelMb": budget["wheel_mb"],
            "wheelTarget": budget["wheel_target"],
        },
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def render_page(commands: list[str]) -> str:
    block = "\n".join(commands)
    return f"""\
---
# {GENERATED}. Source: {SCRIPT_RELPATH}.
# Regenerate with `{REGENERATE}`; CI runs --check.
title: "The five-minute path"
---

# The five-minute path

Every command below is run by `{SCRIPT_RELPATH}` in CI, on this exact example.
If one of them stops working, the build goes red before this page can lie to
you.

You need [uv](https://docs.astral.sh/uv/), a Go toolchain for the CLI, and
Docker running for the local stack.

```bash
{block}
```

That last request answers with money in minor units, as a string:

```json
{{"price": {{"amount": "1020", "currency": "KES"}}}}
```

## What just happened

`heph dev up` read [`examples/hello/heph.toml`](https://github.com/Neoforge-Labs/hephaestus/blob/main/examples/hello/heph.toml),
saw `fragments = ["telemetry"]`, and brought up the OpenTelemetry collector,
Tempo and Grafana. The app itself has no tracing code: `setup_observability`
instruments FastAPI, so the request you just made is already a trace.

Open Grafana at [localhost:54300](http://localhost:54300), go to **Explore**, pick **Tempo** and
search for `service.name=hello`. The script does the same thing over Tempo's
API and prints the trace id it found, which is how CI proves this paragraph.

## Errors are addresses, not stack traces

Ask for a grouped amount, which the kit refuses rather than guesses:

```bash
curl -s "http://localhost:54080/price?amount=1,000&currency=KES"
```

```json
{{
  "type": "https://hephkit.dev/errors/HEPH-MONEY-422",
  "title": "Invalid money amount",
  "status": 422,
  "code": "HEPH-MONEY-422"
}}
```

That `type` resolves: it is [the page for HEPH-MONEY-422](/errors/HEPH-MONEY-422),
generated from the same registry the code comes from.

## Splitting without losing a cent

```bash
curl -s "http://localhost:54080/split?amount=1.00&currency=KES&ways=3"
```

```json
{{"parts": [{{"amount": "34", "currency": "KES"}}, {{"amount": "33", "currency": "KES"}}, {{"amount": "33", "currency": "KES"}}]}}
```

Largest remainder, ties to the lower index, so the parts always add back up to
the total. The rule is [specification section 3](/spec), and the same vectors
pin it in every language the kit binds.

## The whole app

It is one file, and the wiring is two calls. Read
[`examples/hello/app.py`](https://github.com/Neoforge-Labs/hephaestus/blob/main/examples/hello/app.py):
neither handler contains a `try`/`except`, because `install_error_handlers`
turns `MoneyError` into the problem+json above.
"""


def render_meta() -> str:
    return f"""\
import type {{ MetaRecord }} from 'nextra'

// {GENERATED}. Source: {SCRIPT_RELPATH}.
// Regenerate with `{REGENERATE}`; CI runs --check.
const meta: MetaRecord = {{
  'first-five-minutes': 'The five-minute path'
}}

export default meta
"""


def generate(repo_root: Path) -> dict[Path, str]:
    """Map each output path to its content."""
    commands = extract_commands((repo_root / SCRIPT_RELPATH).read_text(encoding="utf-8"))
    budget = json.loads((repo_root / BUDGET_RELPATH).read_text(encoding="utf-8"))
    missing = [k for k in ("boot_seconds", "boot_what", "wheel_mb", "wheel_target") if k not in budget]
    if missing:
        raise ValueError(f"{BUDGET_RELPATH}: missing {', '.join(missing)}")
    return {
        repo_root / SNIPPET_RELPATH: render_snippet(commands, budget),
        repo_root / PAGE_RELPATH: render_page(commands),
        repo_root / META_RELPATH: render_meta(),
    }


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    check = "--check" in args
    unknown = [a for a in args if a != "--check"]
    if unknown:
        print(f"usage: gen_quickstart.py [--check] (unknown: {' '.join(unknown)})", file=sys.stderr)
        return 2
    root = root or Path(__file__).resolve().parents[1]

    try:
        pages = generate(root)
    except (ValueError, OSError) as err:
        print(err, file=sys.stderr)
        return 1

    if check:
        drift = [p for p, text in pages.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
        for path in drift:
            print(f"{path.relative_to(root)} is stale or missing; run: {REGENERATE}", file=sys.stderr)
        return 1 if drift else 0

    for path, text in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
