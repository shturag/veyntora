"""Turn the frames from apps/web/scripts/record-walkthroughs.mjs into GIFs.

    uv run --with pillow scripts/walkthrough-gifs.py <frames-dir> docs/walkthroughs

Each frame gets its caption in a strip below the page, so the caption never hides the page.
"""

import contextlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

WIDTH = 1040
STRIP = 46
INK = (17, 17, 39)
ACCENT = (91, 61, 245)
ROOT = Path(__file__).resolve().parent.parent


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Inter, as in the app; a common system font if node_modules is not installed."""
    inter = "node_modules/.pnpm/@fontsource-variable+inter@*/**/inter-latin-standard-normal.woff2"
    found = sorted(ROOT.glob(inter))
    for path in [*map(str, found), "/System/Library/Fonts/HelveticaNeue.ttc", "DejaVuSans.ttf"]:
        try:
            f = ImageFont.truetype(path, size)
        except OSError:
            continue
        with contextlib.suppress(OSError, ValueError):
            f.set_variation_by_name("SemiBold")
        return f
    return ImageFont.load_default(size)


FONT = font(17)
BRAND = font(15)


def framed(page: Image.Image, caption: str) -> Image.Image:
    page = page.resize((WIDTH, round(page.height * WIDTH / page.width)), Image.Resampling.LANCZOS)
    img = Image.new("RGB", (WIDTH, page.height + STRIP), INK)
    img.paste(page, (0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, page.height, WIDTH, page.height + 3), fill=ACCENT)
    mid = page.height + 3 + (STRIP - 3) / 2
    draw.text((18, mid), "Veyntora", font=BRAND, fill=(176, 166, 255), anchor="lm")
    if caption:
        draw.text((116, mid), caption, font=FONT, fill=(255, 255, 255), anchor="lm")
    return img


def palette(images: list[Image.Image]) -> Image.Image:
    """One palette for the whole GIF, so unchanged pixels stay unchanged and frames stay small."""
    step = max(1, len(images) // 16)
    sample = images[::step]
    sheet = Image.new("RGB", (WIDTH, sum(i.height for i in sample)))
    y = 0
    for i in sample:
        sheet.paste(i, (0, y))
        y += i.height
    return sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def frames(folder: Path):
    """The frames with captions on one palette; repeats are merged into one longer frame."""
    rgb: list[tuple[Image.Image, int]] = []
    for f in json.loads((folder / "frames.json").read_text()):
        img = framed(Image.open(folder / f["file"]).convert("RGB"), f.get("caption", ""))
        if rgb and ImageChops.difference(img, rgb[-1][0]).getbbox() is None:
            rgb[-1] = (rgb[-1][0], rgb[-1][1] + f["ms"])
        else:
            rgb.append((img, f["ms"]))
    pal = palette([i for i, _ in rgb])
    return [(i.quantize(palette=pal, dither=Image.Dither.NONE), ms) for i, ms in rgb]


def main() -> None:
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    dest.mkdir(parents=True, exist_ok=True)
    for folder in sorted(p for p in src.iterdir() if (p / "frames.json").exists()):
        imgs = frames(folder)
        # Linger on the last frame before the loop starts again.
        imgs[-1] = (imgs[-1][0], imgs[-1][1] + 1500)
        target = dest / f"{folder.name}.gif"
        imgs[0][0].save(
            target,
            save_all=True,
            append_images=[i for i, _ in imgs[1:]],
            duration=[ms for _, ms in imgs],
            loop=0,
            optimize=True,
            disposal=1,
        )
        print(f"{target}: {len(imgs)} frames, {target.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
