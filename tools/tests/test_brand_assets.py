"""Tests for the hephkit brand assets in docs/site/public/brand/.

Standard library only: CI provides pytest, pyyaml and jsonschema for tools/tests
and nothing else, so the SVGs are read with ElementTree and the contrast is
plain arithmetic.
"""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BRAND = REPO_ROOT / "docs" / "site" / "public" / "brand"
SVG_NS = "{http://www.w3.org/2000/svg}"

MARKS = ("mark.svg", "favicon.svg", "avatar.svg")
ALL_SVGS = (*MARKS, "lockup.svg")

BRONZE = "#C2884A"
STRIKE = "M48 18 L55 41 L78 48 L55 55 L48 78 L41 55 L18 48 L41 41 Z"


def _root(name: str) -> ET.Element:
    return ET.parse(BRAND / name).getroot()


def _palette() -> dict:
    return json.loads((BRAND / "palette.json").read_text())


def _points(d: str) -> list[tuple[float, float]]:
    """Vertices of an M/L/Z-only path."""
    assert re.fullmatch(r"[MLZ\d\s.,-]+", d), f"unexpected path commands in {d!r}"
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", d)]
    return list(zip(nums[0::2], nums[1::2]))


def _strike(name: str) -> str:
    """The `d` of the strike path in an SVG: the one path that is not text."""
    paths = list(_root(name).iter(f"{SVG_NS}path"))
    assert len(paths) == 1, f"{name} should have exactly one strike path, found {len(paths)}"
    return paths[0].get("d", "")


def _luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_every_mark_parses_as_xml_and_declares_the_96_viewbox() -> None:
    for name in MARKS:
        assert _root(name).get("viewBox") == "0 0 96 96", name


def test_primary_mark_is_the_decided_plate_and_strike() -> None:
    root = _root("mark.svg")
    plates = [r for r in root.iter(f"{SVG_NS}rect") if r.get("rx")]
    assert len(plates) == 1
    plate = plates[0]
    assert {k: plate.get(k) for k in ("x", "y", "width", "height", "rx")} == {
        "x": "10", "y": "10", "width": "76", "height": "76", "rx": "18",
    }
    assert plate.get("fill") == BRONZE
    assert plate.get("mask") == "url(#heph-mark)"
    assert _strike("mark.svg") == STRIKE


def test_avatar_is_an_inverted_solid_plate_with_no_mask() -> None:
    root = _root("avatar.svg")
    assert not list(root.iter(f"{SVG_NS}mask")), "the avatar strike is painted, not masked"
    plate = next(r for r in root.iter(f"{SVG_NS}rect") if r.get("rx"))
    assert plate.get("fill") == BRONZE
    assert plate.get("mask") is None
    strike = next(root.iter(f"{SVG_NS}path"))
    assert strike.get("fill", "").upper() == _palette()["ink"].upper()
    assert strike.get("d") == STRIKE


def test_mask_ids_are_unique_across_every_svg() -> None:
    # avatar.svg has no mask and therefore no id; the rule holds vacuously for it.
    seen: dict[str, str] = {}
    for name in ALL_SVGS:
        for el in _root(name).iter():
            ident = el.get("id")
            if ident is None:
                continue
            assert ident not in {"a", "b", "m"}, f"{name}: {ident!r} is too generic to be safe inline"
            assert ident not in seen, f"id {ident!r} appears in both {seen[ident]} and {name}"
            seen[ident] = name
    assert {"heph-mark", "heph-favicon", "heph-lockup"} <= set(seen)


def test_favicon_is_its_own_drawing_not_a_scaled_mark() -> None:
    assert _strike("favicon.svg") != _strike("mark.svg")

    def waist(d: str) -> float:
        # distance from the centre of the nearest vertex to it: the strike's
        # inner (diagonal) points, which set how thick the cut is.
        return min(max(abs(x - 48), abs(y - 48)) for x, y in _points(d))

    fav, primary = _strike("favicon.svg"), _strike("mark.svg")
    assert waist(fav) > waist(primary), "the favicon cut must be fatter than the primary"
    # Same composition: eight vertices, symmetric about the centre, inside the plate.
    pts = _points(fav)
    assert len(pts) == len(_points(primary)) == 8
    assert {(96 - x, 96 - y) for x, y in pts} == set(pts)
    assert all(10 < x < 86 and 10 < y < 86 for x, y in pts)


def _fills(name: str) -> set[str]:
    return {el.get("fill", "").upper() for el in _root(name).iter() if el.get("fill")}


def test_light_background_assets_never_use_the_light_bronze() -> None:
    palette = _palette()
    swap = palette["light-background-swap"]
    assert swap["files"] == ["mark.svg", "lockup.svg"]
    assert swap["replace"][BRONZE] == palette["bronze-deep"]
    replace = {k.upper(): v.upper() for k, v in swap["replace"].items()}
    for name in swap["files"]:
        fills = _fills(name)
        assert BRONZE in fills, f"{name} should be the dark-background drawing"
        swapped = {replace.get(f, f) for f in fills}
        assert BRONZE not in swapped, f"{name} still paints the light bronze after the documented swap"
        assert palette["bronze-deep"].upper() in swapped
        # The swap is documented where a designer will find it, not only in JSON.
        assert "light background" in (BRAND / name).read_text().lower(), name
    # The other half of the swap: the lockup wordmark must leave paper, or it vanishes on a light page.
    paper, ink = palette["paper"].upper(), palette["ink"].upper()
    lockup_fills = _fills("lockup.svg")
    assert paper in lockup_fills, "lockup.svg should carry a paper wordmark before the swap"
    swapped = {replace.get(f, f) for f in lockup_fills}
    assert paper not in swapped, "the wordmark would stay paper on a light background"
    assert ink in swapped


def test_palette_contrast_meets_the_measured_floors() -> None:
    p = _palette()
    assert {"ink", "bronze", "bronze-deep", "paper"} <= set(p)
    assert _contrast(p["bronze-deep"], p["paper"]) >= 4.5
    assert _contrast(p["bronze"], p["ink"]) >= 3.0
    # Pins why bronze-deep exists: plain bronze is not enough on a light page.
    assert _contrast(p["bronze"], "#FFFFFF") < 4.5
    assert _contrast(p["bronze"], p["paper"]) < 4.5
    # The avatar's dark strike on its bronze plate.
    assert _contrast(p["ink"], p["bronze"]) >= 3.0


def test_lockup_is_text_in_a_system_stack_with_no_embedded_font() -> None:
    root = _root("lockup.svg")
    text = next(root.iter(f"{SVG_NS}text"))
    assert "".join(text.itertext()).strip() == "hephkit"
    assert text.get("font-weight") == "700"
    assert text.get("letter-spacing") == "-0.03em"
    assert "sans-serif" in text.get("font-family", "")
    raw = (BRAND / "lockup.svg").read_text()
    assert "@font-face" not in raw and "data:" not in raw and "<image" not in raw
