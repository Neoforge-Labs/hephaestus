# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==11.3.0"]
# ///
"""Generate the brand rasters in docs/site/public/brand/ from the brand SVGs.

Run with ``uv run tools/gen_brand_raster.py`` to write the files, or with
``--check`` to exit 1 if a committed PNG differs from what the SVGs would
generate. Pillow is declared inline (PEP 723) and pinned exactly: the PNG bytes
are a function of the Pillow version, so a floor would let two machines disagree.

    apple-touch-icon.png  180x180, avatar.svg's plate full-bleed (no margin, no rounding)
    og-card.png           1200x630, lockup.svg centred on ink

There are no timestamps and no metadata, and the wordmark uses only the font bundled
inside Pillow (``ImageFont.load_default``), never a system font. The output is a
function of the SVGs, palette.json and the Pillow build on the running machine:
two runs on one machine give identical bytes, but FreeType and resampling can differ
across platforms. ``--check`` therefore compares against bytes rendered by this
machine's Pillow; it is a local gate and can legitimately disagree across platforms.
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
    ink = json.loads((brand / "palette.json").read_text(encoding="utf-8"))["ink"]
    return {"apple-touch-icon.png": touch_icon(brand), "og-card.png": og_card(brand, ink)}


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check = "--check" in args
    args = [a for a in args if a != "--check"]
    if args[:1] == ["--root"] and len(args) >= 2:
        root = Path(args[1])
        args = args[2:]
    if args:
        print(f"usage: gen_brand_raster.py [--check] [--root DIR] (unknown: {' '.join(args)})", file=sys.stderr)
        return 2
    root = root or Path(__file__).resolve().parents[1]
    brand = root / BRAND_RELPATH
    files = render(brand)

    if check:
        stale = [n for n, data in files.items() if not (brand / n).is_file() or (brand / n).read_bytes() != data]
        for name in stale:
            print(f"{BRAND_RELPATH / name} is stale or missing; run: uv run tools/gen_brand_raster.py", file=sys.stderr)
        return 1 if stale else 0
    for name, data in files.items():
        (brand / name).write_bytes(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
