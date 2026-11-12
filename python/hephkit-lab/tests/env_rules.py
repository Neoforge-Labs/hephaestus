"""Spec 7.5's prohibition, as a check the record tests share.

Spec 7.5 says ``environment`` MUST NOT carry the hostname of the machine, the
name of the user who ran it, or any filesystem path, "under those or any other
member names", because a record is committed and published alongside the result
it describes.

**Nothing in the repository enforces that.** ``tools/check_registry.py``,
``check_modules.py`` and ``check_vectors.py`` read YAML and JSON, not records;
the record model deliberately holds no blacklist of member names, because 7.4
reserves four names and explicitly permits further ones, and a model that
refused every member name resembling a path would be inventing a rule the spec
does not state. So the MUST becomes checkable here, in the tests, and this
module is the one place that says what checking it means. It is imported by
``test_repro.py`` and by the ``lab.record`` runner in ``test_conformance.py``,
whose vectors name a fact to exclude rather than restating the scan.

Not a ``test_`` module, so pytest does not collect it.
"""

from __future__ import annotations

import getpass
import os
import re
import socket
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

#: Member names that would carry one of 7.5's three facts. Not a validation
#: rule -- a record is refused for none of these -- only the names a test
#: refuses to find, so that a later member added "subject to 7.5" cannot
#: reintroduce the fact under an obvious name.
FORBIDDEN_MEMBER_NAMES = frozenset(
    {
        "cwd",
        "dir",
        "directory",
        "file",
        "filename",
        "filepath",
        "home",
        "host",
        "hostname",
        "login",
        "node",
        "nodename",
        "path",
        "paths",
        "prefix",
        "repo",
        "root",
        "user",
        "username",
        "workdir",
        "workspace",
    }
)

#: Shorter than this, a name is too likely to appear inside an unrelated value
#: (a user called ``kn`` is a substring of half the version strings there are),
#: so the containment checks skip it and the member-name check carries the case.
_MIN_NAME = 3

#: At or above this length, a name is distinctive enough that finding it
#: anywhere inside a value is a violation. Below it, only a whole token counts:
#: a machine called ``mac`` must not make ``macOS-15.6-arm64`` a finding, and
#: that false positive would fail this check on somebody else's laptop rather
#: than on a record that carries anything it should not.
_MIN_SUBSTRING = 6


def _tokens(text: str) -> set[str]:
    """`text` split into lowercase alphanumeric runs."""
    return {run for run in re.split(r"[^0-9A-Za-z]+", text.lower()) if run}


def _carries(text: str, name: str) -> bool:
    if len(name) < _MIN_NAME:
        return False
    if name.lower() in _tokens(text):
        return True
    return len(name) >= _MIN_SUBSTRING and name.lower() in text.lower()


def _strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string in `value`, with the dotted path it sits at.

    Keys are yielded as well as values: 7.5 forbids the three facts "under
    those or any other member names", so a hostname used as a member name is as
    much a violation as one used as a value.
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            yield f"{here} (member name)", str(key)
            yield from _strings(item, here)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path or "<root>", value


def _member_names(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            yield here, str(key)
            yield from _member_names(item, here)


def hostname_findings(environment: Mapping[str, Any]) -> list[str]:
    """7.5: the hostname of the machine, under any member name."""
    full = socket.gethostname()
    candidates = {full, full.split(".")[0], socket.getfqdn()}
    return [
        f"{where} carries the hostname {name!r}: {text!r}"
        for where, text in _strings(environment)
        for name in candidates
        if _carries(text, name)
    ]


def username_findings(environment: Mapping[str, Any]) -> list[str]:
    """7.5: the name of the user who ran it, under any member name."""
    candidates = {getpass.getuser(), os.environ.get("USER", ""), os.environ.get("LOGNAME", "")}
    return [
        f"{where} carries the username {name!r}: {text!r}"
        for where, text in _strings(environment)
        for name in candidates
        if _carries(text, name)
    ]


def path_findings(environment: Mapping[str, Any]) -> list[str]:
    """7.5: any filesystem path, under any member name."""
    markers = {str(Path.home()), tempfile.gettempdir(), str(Path.cwd())}
    found = []
    for where, text in _strings(environment):
        if "/" in text or "\\" in text:
            found.append(f"{where} looks like a filesystem path: {text!r}")
            continue
        for marker in markers:
            if len(marker) >= _MIN_NAME and marker in text:  # noqa: SIM102
                found.append(f"{where} carries the path {marker!r}: {text!r}")
    return found


def member_name_findings(environment: Mapping[str, Any]) -> list[str]:
    """7.5 under "any other member names": a member named for a forbidden fact."""
    return [
        f"{where} is a member named {name!r}, which 7.5 forbids"
        for where, name in _member_names(environment)
        if name.lower() in FORBIDDEN_MEMBER_NAMES
    ]


#: The vector vocabulary of `expect.captured.environment_excludes`.
CHECKS = {
    "hostname": hostname_findings,
    "username": username_findings,
    "filesystem-path": path_findings,
}


def forbidden_facts(environment: Mapping[str, Any]) -> list[str]:
    """Every 7.5 violation in `environment`, each as a readable finding."""
    found: list[str] = []
    for check in CHECKS.values():
        found.extend(check(environment))
    found.extend(member_name_findings(environment))
    return found
