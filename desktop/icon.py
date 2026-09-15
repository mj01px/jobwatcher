"""Job Watcher mark drawn with Pillow, shared by the tray icon and the .ico file.

Mirrors frontend/src/assets/job-watcher-mark.svg (64x64 grid of flat blocks).

    backend\\.venv\\Scripts\\python.exe desktop\\icon.py   # writes desktop\\job-watcher.ico
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ICO_PATH = Path(__file__).resolve().parent / "job-watcher.ico"

# (x, y, width, height, color) on the SVG 64 unit grid.
_BLOCKS = (
    (0, 0, 64, 64, "#111633"),
    (8, 9, 36, 10, "#f2f0f7"),
    (48, 9, 8, 10, "#ffc52f"),
    (8, 27, 27, 10, "#8f96c2"),
    (39, 27, 17, 10, "#28c8c2"),
    (8, 45, 41, 10, "#6d4bc3"),
    (53, 45, 3, 10, "#2366d1"),
)


def draw_mark(size: int = 256) -> Image.Image:
    """Render the mark as a square RGBA image of ``size`` pixels."""
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)
    scale = size / 64
    for x, y, width, height, color in _BLOCKS:
        draw.rectangle(
            (
                round(x * scale),
                round(y * scale),
                round((x + width) * scale) - 1,
                round((y + height) * scale) - 1,
            ),
            fill=color,
        )
    return image


def draw_macos_icon(size: int = 1024) -> Image.Image:
    """Render the mark on a macOS-style rounded tile with margins.

    macOS app icons are rounded squares inset from the canvas edges; the
    full-bleed :func:`draw_mark` looks oversized and boxy next to them in
    Launchpad and the Dock, so the ``.icns`` uses this variant instead. The
    corners are transparent and there is a margin around the tile.
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    margin = round(size * 0.10)
    content = size - 2 * margin
    radius = round(content * 0.2237)  # Apple's continuous-corner squircle ratio.

    # The mark (block 0 is the full brand-coloured background) drawn at tile size.
    tile = draw_mark(content)

    # Round the corners by keeping only what falls inside a rounded rectangle.
    mask = Image.new("L", (content, content), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, content - 1, content - 1), radius=radius, fill=255)

    image.paste(tile, (margin, margin), mask)
    return image


def draw_menu_bar_icon(size: int = 64) -> Image.Image:
    """Render the mark for the macOS menu bar: padded and rounded, not full-bleed.

    pystray scales the image to the menu-bar height, so a full-bleed square
    (:func:`draw_mark`) becomes a heavy block edge to edge. Transparent padding
    around a rounded tile makes the icon read at the same visual weight as the
    native menu-bar items.
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    margin = round(size * 0.16)
    content = size - 2 * margin
    radius = round(content * 0.2237)

    tile = draw_mark(content)
    mask = Image.new("L", (content, content), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, content - 1, content - 1), radius=radius, fill=255)

    image.paste(tile, (margin, margin), mask)
    return image


def write_ico(path: Path = ICO_PATH) -> Path:
    draw_mark(256).save(path, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    return path


if __name__ == "__main__":
    print(write_ico())
