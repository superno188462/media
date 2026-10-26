"""图文成稿渲染。

用 Pillow 把正文和配图排成一张可发布的图。B 站的图文动态对图片
尺寸有上限，所以这里默认长边不超过 1680px。

字体用 Windows 自带的微软雅黑，不引入字体文件依赖。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

#: 长边上限。B 站图文动态图片的经验值，实机发布时再核一次。
MAX_EDGE = 1680

#: 配图之间的间距。
GAP = 24

#: 留白。
PAD = 48

BACKGROUND = (250, 246, 240)
TEXT_COLOR = (45, 42, 38)
TITLE_COLOR = (28, 26, 24)
RULE_COLOR = (214, 205, 192)

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)


@dataclass
class RenderOptions:
    width: int = 1080
    title_size: int = 46
    body_size: int = 30
    line_spacing: int = 14


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc")
        if bold
        else _FONT_CANDIDATES
    )
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """按像素宽度折行，中文逐字、英文按空格。"""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            trial = current + char
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = char
        if current:
            lines.append(current)
    return lines


def _fit(images: list[Path], max_width: int, max_height: int) -> list[Image.Image]:
    """把配图等比缩放到不超过给定框内。"""
    fitted: list[Image.Image] = []
    for path in images:
        with Image.open(path) as im:
            img = im.convert("RGB")
            ratio = min(max_width / img.width, max_height / img.height, 1.0)
            new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
            fitted.append(img.resize(new_size, Image.LANCZOS))
    return fitted


def render_post(
    title: str,
    body: str,
    images: list[Path],
    out_path: Path,
    options: RenderOptions | None = None,
) -> Path:
    """渲染一条图文成稿，返回输出路径。"""
    opts = options or RenderOptions()
    width = opts.width
    inner = width - PAD * 2

    title_font = _load_font(opts.title_size, bold=True)
    body_font = _load_font(opts.body_size)

    # 先用一张临时画布量文字高度。
    probe = Image.new("RGB", (width, 10), BACKGROUND)
    pdraw = ImageDraw.Draw(probe)
    title_lines = _wrap(pdraw, title, title_font, inner)
    body_lines = _wrap(pdraw, body, body_font, inner)

    line_h_title = opts.title_size + opts.line_spacing
    line_h_body = opts.body_size + opts.line_spacing
    text_height = len(title_lines) * line_h_title + len(body_lines) * line_h_body

    fitted = _fit(images, inner, 900)

    image_height = sum(img.height for img in fitted) + GAP * max(0, len(fitted) - 1)
    height = PAD * 2 + text_height + (GAP + image_height if fitted else 0)

    canvas = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    y = PAD
    for line in title_lines:
        draw.text((PAD, y), line, font=title_font, fill=TITLE_COLOR)
        y += line_h_title

    if title_lines and body_lines:
        y += 6
        draw.rectangle([PAD, y, PAD + 56, y + 4], fill=RULE_COLOR)
        y += 20

    for line in body_lines:
        draw.text((PAD, y), line, font=body_font, fill=TEXT_COLOR)
        y += line_h_body

    if fitted:
        y += GAP
        for img in fitted:
            x = (width - img.width) // 2
            canvas.paste(img, (x, y))
            y += img.height + GAP

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=92)
    return out_path
