# -*- coding: utf-8 -*-
"""生成符合 TikTok Shop 要求的测试商品图（白底、1200x1200、JPG）。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DESKTOP = Path(r"C:\Users\Administrator\Desktop")
SIZE = 1200
WHITE = (255, 255, 255)


def _font(size: int):
    for name in ("arial.ttf", "msyh.ttc", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_image(path: Path, *, title: str, color: tuple[int, int, int], subtitle: str = "") -> None:
    img = Image.new("RGB", (SIZE, SIZE), WHITE)
    draw = ImageDraw.Draw(img)
    margin = 120
    draw.rounded_rectangle(
        (margin, margin, SIZE - margin, SIZE - margin),
        radius=40,
        fill=color,
        outline=(220, 220, 220),
        width=4,
    )
    draw.rounded_rectangle(
        (margin + 80, margin + 80, SIZE - margin - 80, SIZE - margin - 80),
        radius=24,
        fill=(min(color[0] + 30, 255), min(color[1] + 30, 255), min(color[2] + 30, 255)),
    )
    font = _font(52)
    subfont = _font(34)
    draw.text((SIZE // 2, SIZE // 2 - 20), title, fill=(40, 40, 40), font=font, anchor="mm")
    if subtitle:
        draw.text((SIZE // 2, SIZE // 2 + 40), subtitle, fill=(80, 80, 80), font=subfont, anchor="mm")
    img.save(path, format="JPEG", quality=92, optimize=True)
    print(f"已生成: {path}  ({path.stat().st_size // 1024} KB)")


def main() -> None:
    make_image(
        DESKTOP / "tiktok_main.jpg",
        title="Sofa Cover",
        color=(120, 90, 70),
        subtitle="Main Image",
    )
    make_image(
        DESKTOP / "tiktok_sub1.jpg",
        title="Black 70x70",
        color=(45, 45, 48),
        subtitle="Sub Image 1",
    )
    make_image(
        DESKTOP / "tiktok_sub2.jpg",
        title="Black 90x90",
        color=(55, 55, 58),
        subtitle="Sub Image 2",
    )
    make_image(
        DESKTOP / "tiktok_sub3.jpg",
        title="Grey 70x70",
        color=(130, 130, 135),
        subtitle="Sub Image 3",
    )
    print("\nExcel 填写示例:")
    print(r"主图路径*  C:\Users\Administrator\Desktop\tiktok_main.jpg")
    print(r"副图路径   C:\Users\Administrator\Desktop\tiktok_sub1.jpg;C:\Users\Administrator\Desktop\tiktok_sub2.jpg;C:\Users\Administrator\Desktop\tiktok_sub3.jpg")


if __name__ == "__main__":
    main()
