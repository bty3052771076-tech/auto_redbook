from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


CANVAS_SIZE = (1080, 1440)


def _draw_sheep(*, with_wool: bool) -> Image.Image:
    image = Image.new("RGB", CANVAS_SIZE, "#f6f2e9")
    draw = ImageDraw.Draw(image)
    # A restrained editorial illustration: the two states differ visually,
    # so the workflow can communicate whether a verified benefit was found.
    draw.rounded_rectangle((72, 72, 1008, 1368), radius=34, fill="#fffdf8", outline="#e8dfd2", width=4)
    draw.ellipse((196, 430, 884, 1110), fill="#c9d8c3", outline="#8ca38a", width=8)
    draw.ellipse((682, 410, 930, 735), fill="#3c4b55", outline="#27343c", width=8)
    draw.ellipse((744, 488, 790, 536), fill="#fffdf8")
    draw.ellipse((850, 488, 896, 536), fill="#fffdf8")
    draw.ellipse((760, 503, 778, 521), fill="#27343c")
    draw.ellipse((866, 503, 884, 521), fill="#27343c")
    draw.arc((770, 550, 870, 640), 10, 160, fill="#fffdf8", width=8)
    for x in (294, 468, 642, 774):
        draw.rounded_rectangle((x, 1000, x + 64, 1235), radius=22, fill="#3c4b55")
    if with_wool:
        for x, y, r in (
            (252, 560, 150),
            (400, 478, 164),
            (574, 470, 172),
            (738, 560, 150),
            (324, 716, 172),
            (508, 680, 190),
            (704, 716, 172),
            (420, 856, 180),
            (620, 860, 180),
        ):
            draw.ellipse((x - r, y - r, x + r, y + r), fill="#fffdf8", outline="#e5ddd0", width=6)
        draw.ellipse((110, 1130, 280, 1300), fill="#e6be65", outline="#b1883c", width=7)
        draw.ellipse((800, 1120, 970, 1290), fill="#e6be65", outline="#b1883c", width=7)
    else:
        draw.arc((260, 540, 810, 990), 180, 360, fill="#8ca38a", width=12)
        draw.rounded_rectangle((374, 1115, 706, 1245), radius=20, fill="#efe4d0", outline="#b9a58b", width=7)
        draw.line((410, 1178, 670, 1178), fill="#b9a58b", width=7)
        draw.line((540, 1115, 540, 1245), fill="#b9a58b", width=7)
    return image


def ensure_wool_assets(output_dir: str | Path = Path("assets") / "wool") -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "with_wool": directory / "有羊毛的羊.png",
        "without_wool": directory / "无羊毛的羊.png",
    }
    for key, path in paths.items():
        if not path.exists():
            _draw_sheep(with_wool=key == "with_wool").save(path, format="PNG", optimize=True)
    return paths
