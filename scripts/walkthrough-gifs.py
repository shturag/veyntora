"""Turn the frames from apps/web/scripts/record-walkthroughs.mjs into GIFs.

    uv run --with pillow scripts/walkthrough-gifs.py <frames-dir> docs/walkthroughs

Each frame gets its caption in a strip below the page, so the caption never hides the page.
Besides one GIF per walkthrough, tour.gif plays them all in order, each after a title card.
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


# The tour: chapters in this order, with their titles.
TOUR = {
    "chat": "The chat for employees",
    "admin-console": "The admin console",
    "01-simple-chatbot": "A simple chatbot",
    "02-rag-chatbot": "A chatbot that answers from documents",
    "03-tools-chatbot": "A chatbot with tools",
    "04-automations": "Automations",
    "05-data-sources": "Data sources",
    "06-providers": "Providers & keys",
    "07-tools-mcp": "Tools (MCP)",
    "08-channels-api": "Channels & API",
    "09-conversations": "Conversations",
    "10-knowledge-health": "Knowledge health",
    "11-evaluation": "Evaluation",
    "12-monitoring": "Monitoring",
    "13-integrations": "Integrations",
    "14-infrastructure": "Infrastructure",
    "15-usage-budgets": "Usage & budgets",
    "16-users-groups": "Users & groups",
    "17-governance": "Governance",
    "18-audit-log": "Audit log",
}
TITLE = font(40)


def title_card(size: tuple[int, int], number: int, total: int, title: str) -> Image.Image:
    img = Image.new("RGB", size, INK)
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.text(
        (w / 2, h / 2 - 46), f"{number} / {total}", font=FONT, fill=(176, 166, 255), anchor="mm"
    )
    draw.text((w / 2, h / 2), title, font=TITLE, fill=(255, 255, 255), anchor="mm")
    draw.rectangle((w / 2 - 40, h / 2 + 34, w / 2 + 40, h / 2 + 37), fill=ACCENT)
    draw.text(
        (w / 2, h - 30), "Veyntora walkthrough", font=BRAND, fill=(176, 166, 255), anchor="mm"
    )
    return img


def tour(src: Path, dest: Path) -> None:
    """Every walkthrough in one GIF, on one palette, each after a title card."""
    chapters = [
        (name, title) for name, title in TOUR.items() if (src / name / "frames.json").exists()
    ]
    if not chapters:
        return
    # A palette from a few frames of every chapter (all frames at once would not fit in memory).
    sample: list[Image.Image] = []
    for name, _ in chapters:
        index = json.loads((src / name / "frames.json").read_text())
        for f in index[:: max(1, len(index) // 3)][:3]:
            sample.append(framed(Image.open(src / name / f["file"]).convert("RGB"), f["caption"]))
    pal = palette(sample)
    size = sample[0].size
    out: list[tuple[Image.Image, int]] = []
    for n, (name, title) in enumerate(chapters, 1):
        card = title_card(size, n, len(chapters), title)
        out.append((card.quantize(palette=pal, dither=Image.Dither.NONE), 1800))
        last: Image.Image | None = None
        for f in json.loads((src / name / "frames.json").read_text()):
            img = framed(Image.open(src / name / f["file"]).convert("RGB"), f.get("caption", ""))
            if last is not None and ImageChops.difference(img, last).getbbox() is None:
                out[-1] = (out[-1][0], out[-1][1] + f["ms"])
                continue
            last = img
            out.append((img.quantize(palette=pal, dither=Image.Dither.NONE), f["ms"]))
    target = dest / "tour.gif"
    out[0][0].save(
        target,
        save_all=True,
        append_images=[i for i, _ in out[1:]],
        duration=[ms for _, ms in out],
        loop=0,
        optimize=True,
        disposal=1,
    )
    minutes = sum(ms for _, ms in out) / 60000
    print(
        f"{target}: {len(chapters)} chapters, {len(out)} frames, {minutes:.1f} min,",
        f"{target.stat().st_size / 1e6:.1f} MB",
    )


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
    tour(src, dest)


if __name__ == "__main__":
    main()
