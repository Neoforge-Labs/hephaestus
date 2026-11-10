# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==11.3.0"]
# ///
"""Generate the brand rasters in docs/site/public/brand/ from the brand SVGs.

Run with ``uv run tools/gen_brand_raster.py`` to write the PNGs and the provenance
manifest ``tools/brand-provenance.txt``. Pillow is declared inline (PEP 723) and pinned
exactly: the PNG bytes are a function of the Pillow version, so a floor would let two
machines disagree.

``--check`` is the enforced gate, and it is platform-independent: it hashes the five
sources (the four SVGs and palette.json) and the two PNGs and compares them with the
sha256 values recorded in the manifest. An SVG edited without regenerating fails the
source side; a hand-edited PNG fails the output side. It renders nothing and writes
nothing. This is the same shape as ``spec/currencies.source.yaml`` and
``gen_currencies.py --verify-source``: a derived artifact that cannot be reproduced
byte-for-byte everywhere is pinned by hash. ``tools/tests`` runs it against the
committed tree.

``--check-render`` is a local convenience only: it re-renders and compares against the
PNGs byte for byte. FreeType and resampling differ across platforms, so it can
legitimately fail off the machine that generated the PNGs. Nothing in CI uses it.

    apple-touch-icon.png  180x180, avatar.svg's plate full-bleed (no margin, no rounding)
    og-card.png           1200x630, lockup.svg centred on ink

There are no timestamps and no metadata, and the wordmark uses only the font bundled
inside Pillow (``ImageFont.load_default``), never a system font. The output is a
function of the SVGs, palette.json and the Pillow build on the running machine:
two runs on one machine give identical bytes, but FreeType and resampling can differ
across platforms, which is why provenance is pinned by hash rather than by re-rendering.
The wordmark is Regular only, so the SVG's weight 700 is approximated with a thin
stroke in the same colour.

Parsing is deliberately minimal and says so: no SVG renderer is installed (cairo
is a native library), so this reads exactly the shapes the brand files use and
fails loudly on anything else. Those are a ``<rect>`` (x, y, width, height, rx),
a ``<path>`` of straight ``M``/``L``/``Z`` segments, one ``<mask>`` that punches a
path out of the plate, and one ``<text>`` (x, y, font-size, letter-spacing, fill).
Geometry is never repeated here, so editing an SVG changes the PNGs on the next
run. The knockout is painted in the ground colour, which is what a mask over a flat
background looks like.

Limits, none of which bites the four current files: multiple ``M`` subpaths are
merged into one polygon; the viewBox's min-x and min-y are discarded; ``transform``,
``opacity``, ``font-weight`` and ``text-anchor`` are ignored (bold comes from
``BOLD_STROKE_EM``, not from ``font-weight``); mask fills are assumed to be black
on a white rect, not checked; and the wordmark is drawn one character at a time, so
it has no kerning.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

BRAND_RELPATH = Path("docs/site/public/brand")
OUTPUTS = ("apple-touch-icon.png", "og-card.png")
SOURCES = ("mark.svg", "favicon.svg", "avatar.svg", "lockup.svg", "palette.json")
MANIFEST_RELPATH = Path("tools/brand-provenance.txt")
MANIFEST_HEADER = """\
# Provenance of the brand rasters in docs/site/public/brand/ (apple-touch-icon.png and
# og-card.png). Written by tools/gen_brand_raster.py; never edit by hand.
#
# WHY THIS IS A HASH FILE AND NOT A RE-RENDER. The PNGs are drawn from the SVGs with
# Pillow, and text rasterisation (FreeType, resampling) is not reproducible across
# platforms: the same SVGs give different bytes on macOS and on Linux. A check that
# re-rendered and compared bytes would fail for whoever is not on the machine that
# generated the files, and regenerating there would flip the bytes back for the next
# person. So, as spec/currencies.source.yaml does for the SIX list, provenance is pinned
# by sha256 instead:
#
#   source  sha256 of an input the PNGs are derived from
#   output  sha256 of a committed PNG
#
#   uv run tools/gen_brand_raster.py --check
#
# fails if a source no longer hashes to what is recorded (an SVG was edited and the
# rasters were not regenerated) or if a PNG no longer hashes to what is recorded (a PNG
# was edited by hand). After editing an SVG, run `uv run tools/gen_brand_raster.py`
# and commit the PNGs together with this file.
"""

TOUCH_SIZE = (180, 180)
CARD_SIZE = (1200, 630)
CARD_LOCKUP_WIDTH = 0.62  # visible lockup as a fraction of the card width
SUPERSAMPLE = 4  # draw large, then downscale with LANCZOS, for smooth edges
BOLD_STROKE_EM = 0.028  # approximates weight 700 from Aileron Regular

SVG_NS = "{http://www.w3.org/2000/svg}"
Point = tuple[float, float]


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float
    rx: float
    fill: str
    knockout: tuple[Point, ...] | None  # vertices punched out via mask, if any


@dataclass(frozen=True)
class Polygon:
    points: tuple[Point, ...]
    fill: str


@dataclass(frozen=True)
class Text:
    x: float
    y: float
    content: str
    size: float
    spacing_em: float
    fill: str


@dataclass(frozen=True)
class Drawing:
    width: float
    height: float
    shapes: tuple[Rect | Polygon | Text, ...]


def _path_points(d: str) -> tuple[Point, ...]:
    """Vertices of an M/L/Z-only path; anything else is an error, not a guess."""
    if not re.fullmatch(r"[MLZ\d\s.,-]+", d):
        raise ValueError(f"only straight M/L/Z paths are supported, got {d!r}")
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", d)]
    return tuple(zip(nums[0::2], nums[1::2], strict=True))


def _knockout(root: ET.Element, ref: str) -> tuple[Point, ...]:
    match = re.fullmatch(r"url\(#([^)]+)\)", ref)
    mask = next((m for m in root.iter(f"{SVG_NS}mask") if match and m.get("id") == match[1]), None)
    path = mask.find(f"{SVG_NS}path") if mask is not None else None
    if path is None:
        raise ValueError(f"mask {ref!r} has no path to punch out")
    return _path_points(path.attrib["d"])


def parse_svg(path: Path) -> Drawing:
    """The drawable shapes of one brand SVG, in document order."""
    root = ET.parse(path).getroot()
    _, _, width, height = (float(v) for v in root.attrib["viewBox"].split())
    shapes: list[Rect | Polygon | Text] = []
    for el in root:
        tag = el.tag.removeprefix(SVG_NS)
        if tag in ("title", "defs"):
            continue
        if tag == "rect":
            mask = el.get("mask")
            shapes.append(
                Rect(
                    *(float(el.attrib[k]) for k in ("x", "y", "width", "height")),
                    float(el.get("rx", 0)),
                    el.attrib["fill"],
                    _knockout(root, mask) if mask else None,
                )
            )
        elif tag == "path":
            shapes.append(Polygon(_path_points(el.attrib["d"]), el.attrib["fill"]))
        elif tag == "text":
            spacing = el.get("letter-spacing", "0em")
            if not spacing.endswith("em"):
                raise ValueError(f"letter-spacing must be in em, got {spacing!r}")
            shapes.append(
                Text(
                    float(el.attrib["x"]),
                    float(el.attrib["y"]),
                    "".join(el.itertext()),
                    float(el.attrib["font-size"]),
                    float(spacing.removesuffix("em")),
                    el.attrib["fill"],
                )
            )
        else:
            raise ValueError(f"unsupported element <{tag}> in {path.name}")
    return Drawing(width, height, tuple(shapes))


def _scaled(points: tuple[Point, ...], scale: float) -> list[Point]:
    return [(x * scale, y * scale) for x, y in points]


def draw(drawing: Drawing, scale: float, ground: str) -> Image.Image:
    """Paint a drawing at ``scale`` pixels per SVG unit onto a ``ground`` coloured canvas."""
    image = Image.new("RGB", (round(drawing.width * scale), round(drawing.height * scale)), ground)
    canvas = ImageDraw.Draw(image)
    for shape in drawing.shapes:
        if isinstance(shape, Rect):
            box = (
                shape.x * scale,
                shape.y * scale,
                (shape.x + shape.width) * scale - 1,
                (shape.y + shape.height) * scale - 1,
            )
            canvas.rounded_rectangle(box, radius=shape.rx * scale, fill=shape.fill)
            if shape.knockout:
                canvas.polygon(_scaled(shape.knockout, scale), fill=ground)
        elif isinstance(shape, Polygon):
            canvas.polygon(_scaled(shape.points, scale), fill=shape.fill)
        else:
            font = ImageFont.load_default(size=shape.size * scale)
            stroke = round(shape.size * scale * BOLD_STROKE_EM)
            pen = shape.x * scale
            for char in shape.content:
                canvas.text(
                    (pen, shape.y * scale),
                    char,
                    font=font,
                    fill=shape.fill,
                    anchor="ls",
                    stroke_width=stroke,
                    stroke_fill=shape.fill,
                )
                pen += font.getlength(char) + shape.spacing_em * shape.size * scale
    return image


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")  # no pnginfo, no timestamp: bytes depend only on pixels
    return buffer.getvalue()


def touch_icon(brand: Path) -> bytes:
    """avatar.svg's plate as a full-bleed square: opaque, no margin, no rounded corners.

    iOS applies its own corner mask, so the SVG's margin and ``rx`` would show up as a
    second, ink-coloured frame. The parsed plate rect sets the crop and the fill.
    """
    avatar = parse_svg(brand / "avatar.svg")
    plate = next((s for s in avatar.shapes if isinstance(s, Rect)), None)
    if plate is None:
        raise ValueError("avatar.svg has no plate <rect>")
    if plate.width != plate.height:
        raise ValueError(f"avatar.svg's plate must be square, got {plate.width} x {plate.height}")
    size = TOUCH_SIZE[0] * SUPERSAMPLE
    scale = size / plate.width
    image = Image.new("RGB", (size, size), plate.fill)
    canvas = ImageDraw.Draw(image)
    for shape in avatar.shapes:
        if isinstance(shape, Polygon):
            points = [((x - plate.x) * scale, (y - plate.y) * scale) for x, y in shape.points]
            canvas.polygon(points, fill=shape.fill)
    return _png(image.resize(TOUCH_SIZE, Image.Resampling.LANCZOS))


def og_card(brand: Path, ink: str) -> bytes:
    """The lockup, with its visible content (not its viewBox) centred on an ink card."""
    lockup = parse_svg(brand / "lockup.svg")
    scale = 12  # draw the lockup big enough that scaling it down never upsamples
    art = draw(lockup, scale, ink)
    bounds = ImageChops.difference(art, Image.new("RGB", art.size, ink)).getbbox()
    if bounds is None:
        raise ValueError("lockup.svg drew nothing")
    art = art.crop(bounds)  # the viewBox keeps slack for wider fonts; centre what is seen

    card_w, card_h = (v * SUPERSAMPLE for v in CARD_SIZE)
    target_w = round(card_w * CARD_LOCKUP_WIDTH)
    art = art.resize((target_w, round(art.height * target_w / art.width)), Image.Resampling.LANCZOS)
    card = Image.new("RGB", (card_w, card_h), ink)
    card.paste(art, ((card_w - art.width) // 2, (card_h - art.height) // 2))
    return _png(card.resize(CARD_SIZE, Image.Resampling.LANCZOS))


def render(brand: Path) -> dict[str, bytes]:
    """Every generated file's bytes, keyed by file name."""
    ink = json.loads((brand / "palette.json").read_text(encoding="utf-8"))["colors"]["ink"]
    return {"apple-touch-icon.png": touch_icon(brand), "og-card.png": og_card(brand, ink)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_text(brand: Path) -> str:
    """The manifest as written: header, then one ``kind sha256 name`` line per file."""
    lines = [f"source {_sha256(brand / n)} {n}" for n in SOURCES]
    lines += [f"output {_sha256(brand / n)} {n}" for n in OUTPUTS]
    return MANIFEST_HEADER + "\n".join(lines) + "\n"


def read_manifest(path: Path) -> dict[tuple[str, str], str]:
    """``(kind, name) -> sha256`` from the manifest; comments and blank lines are skipped."""
    entries: dict[tuple[str, str], str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind, digest, name = line.split()
        entries[(kind, name)] = digest
    return entries


def verify(brand: Path, manifest: Path) -> list[str]:
    """Problems found comparing the tree with the manifest; empty means it is in step."""
    if not manifest.is_file():
        return [f"{manifest.name} is missing; run: uv run tools/gen_brand_raster.py"]
    recorded = read_manifest(manifest)
    problems: list[str] = []
    for kind, names, hint in (
        ("source", SOURCES, "edited since the PNGs were generated; run: uv run tools/gen_brand_raster.py"),
        ("output", OUTPUTS, "does not match the recorded hash (edited by hand, or stale); run: uv run tools/gen_brand_raster.py"),
    ):
        for name in names:
            path = brand / name
            if not path.is_file():
                problems.append(f"{BRAND_RELPATH / name} is missing; run: uv run tools/gen_brand_raster.py")
            elif recorded.get((kind, name)) != _sha256(path):
                problems.append(f"{BRAND_RELPATH / name} {hint}")
    return problems


USAGE = "usage: gen_brand_raster.py [--check | --check-render] [--root DIR]"


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--root"] and len(args) >= 2:
        root = Path(args[1])
        args = args[2:]
    mode = args[0] if args and args[0] in ("--check", "--check-render") else None
    if mode:
        args = args[1:]
    if args[:1] == ["--root"] and len(args) >= 2:
        root = Path(args[1])
        args = args[2:]
    if args:
        print(f"{USAGE} (unknown: {' '.join(args)})", file=sys.stderr)
        return 2
    root = root or Path(__file__).resolve().parents[1]
    brand = root / BRAND_RELPATH
    manifest = root / MANIFEST_RELPATH

    if mode == "--check":
        problems = verify(brand, manifest)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0

    files = render(brand)
    if mode == "--check-render":
        stale = [n for n, data in files.items() if not (brand / n).is_file() or (brand / n).read_bytes() != data]
        for name in stale:
            print(f"{BRAND_RELPATH / name} differs from this machine's render; run: uv run tools/gen_brand_raster.py", file=sys.stderr)
        return 1 if stale else 0
    for name, data in files.items():
        (brand / name).write_bytes(data)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(manifest_text(brand), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
