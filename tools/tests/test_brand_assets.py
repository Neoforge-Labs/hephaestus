"""Tests for the hephkit brand assets in docs/site/public/brand/.

Standard library only: CI provides pytest, pyyaml and jsonschema for tools/tests
and nothing else, so the SVGs are read with ElementTree and the contrast is
plain arithmetic.
"""

import json
import re
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
import zlib
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


# --- generated rasters ------------------------------------------------------
# The generator declares its own dependency (Pillow) in a PEP 723 header, and CI's
# tools/tests line does not carry it. So the tests run it as a subprocess through
# `uv run` and read PNG sizes from the IHDR header, never importing Pillow.

GENERATOR = REPO_ROOT / "tools" / "gen_brand_raster.py"
RASTERS = ("apple-touch-icon.png", "og-card.png")
SVG_SOURCES = (*ALL_SVGS, "palette.json")


def _generate(root: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", str(GENERATOR), "--root", str(root), *flags],
        capture_output=True,
        text=True,
        check=False,
    )


def _scratch_root(tmp_path: Path) -> Path:
    """A repo-shaped tree holding only the generator's inputs."""
    brand = tmp_path / "docs" / "site" / "public" / "brand"
    brand.mkdir(parents=True)
    for name in SVG_SOURCES:
        shutil.copy(BRAND / name, brand / name)
    return tmp_path


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", data[16:24])


def test_raster_generator_is_deterministic_and_check_detects_staleness(tmp_path: Path) -> None:
    # Everything here compares output from the same machine. Byte equality with the
    # PNGs committed from another platform is deliberately not asserted: FreeType and
    # Pillow's resampling can differ across platforms, so that would be untrue.
    root = _scratch_root(tmp_path)
    out = root / "docs" / "site" / "public" / "brand"

    missing = _generate(root, "--check")
    assert missing.returncode == 1, "--check must fail while the PNGs do not exist"

    first_run = _generate(root)
    assert first_run.returncode == 0, first_run.stderr
    first = {name: (out / name).read_bytes() for name in RASTERS}
    assert all(first.values())

    for name in RASTERS:
        (out / name).unlink()
    assert _generate(root).returncode == 0
    assert {name: (out / name).read_bytes() for name in RASTERS} == first, "two runs differ"

    assert _generate(root, "--check").returncode == 0

    for name in RASTERS:
        stale = bytearray(first[name])
        stale[-20] ^= 0xFF
        (out / name).write_bytes(bytes(stale))
        result = _generate(root, "--check")
        assert result.returncode == 1, f"--check missed a corrupted {name}"
        assert name in result.stderr
        assert (out / name).read_bytes() == bytes(stale), "--check must not write"
        (out / name).write_bytes(first[name])


def test_raster_follows_an_svg_edit(tmp_path: Path) -> None:
    # The reason the generator exists: edit a source SVG and the PNG changes with it.
    root = _scratch_root(tmp_path)
    brand = root / "docs" / "site" / "public" / "brand"
    assert _generate(root).returncode == 0
    before = {name: (brand / name).read_bytes() for name in RASTERS}

    for svg, png in (("avatar.svg", "apple-touch-icon.png"), ("lockup.svg", "og-card.png")):
        source = (brand / svg).read_text()
        assert 'rx="18"' in source
        (brand / svg).write_text(source.replace('rx="18"', 'rx="30"').replace("#C2884A", "#336699"))
    assert _generate(root).returncode == 0
    for name in RASTERS:
        assert (brand / name).read_bytes() != before[name], f"{name} ignored an SVG edit"


def _first_pixel(path: Path) -> tuple[int, int, int]:
    """Top-left RGB of an 8-bit RGB PNG. The first scanline's filters all unfilter
    against an implicit zero row, so its first pixel is the raw bytes after the filter byte."""
    data, pos, idat = path.read_bytes(), 8, b""
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        if data[pos + 4 : pos + 8] == b"IDAT":
            idat += data[pos + 8 : pos + 8 + length]
        pos += 12 + length
    r, g, b = zlib.decompress(idat)[1:4]
    return r, g, b


def test_touch_icon_is_a_full_bleed_bronze_tile() -> None:
    # iOS applies its own corner mask, so the corner must be bronze, not an ink border.
    assert _first_pixel(BRAND / "apple-touch-icon.png") == (0xC2, 0x88, 0x4A)


def test_raster_sizes_are_exactly_what_the_platforms_require() -> None:
    # A wrong og-card ratio is cropped by every social preview, silently.
    assert _png_size(BRAND / "apple-touch-icon.png") == (180, 180)
    assert _png_size(BRAND / "og-card.png") == (1200, 630)
