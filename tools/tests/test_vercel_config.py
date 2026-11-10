"""The Vercel config repeats pins that live in .prototools; keep them equal."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _prototools(name: str) -> str:
    m = re.search(rf'^{name}\s*=\s*"([^"]+)"', (ROOT / ".prototools").read_text(encoding="utf-8"), re.M)
    assert m, f"{name} not pinned in .prototools"
    return m.group(1)


def test_vercel_bun_pin_matches_prototools() -> None:
    cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    bun = _prototools("bun")
    for key in ("installCommand", "buildCommand"):
        assert f"bunx bun@{bun} " in cfg[key], f"{key} must run bun@{bun}"


def test_engines_node_matches_prototools_major() -> None:
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert pkg["engines"]["node"] == f"{_prototools('node').split('.')[0]}.x"


def test_vercel_config_serves_clean_urls_from_a_static_export() -> None:
    cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert cfg["cleanUrls"] is True  # documented default is false; /errors/<code> needs it
    assert cfg["framework"] is None
    assert cfg["outputDirectory"] == "docs/site/out"
