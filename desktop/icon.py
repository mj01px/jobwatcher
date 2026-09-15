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


def write_ico(path: Path = ICO_PATH) -> Path:
    draw_mark(256).save(path, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    return path


if __name__ == "__main__":
    print(write_ico())
