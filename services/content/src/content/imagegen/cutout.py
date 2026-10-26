"""把纯色背景的立绘抠成透明 PNG。

为什么需要：生图模型给的是带背景的方图，直接放进视频像贴了张照片。
鲸鱼娘那类立绘都是去背的剪影，这里用洪泛填充从四角吃掉背景色。

只对**纯色/近纯色背景**有效。背景复杂时应改用专门的分割模型，
不要把这里当成通用抠图。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

#: 默认容差：RGB 各通道允许的偏差。
DEFAULT_TOLERANCE = 26


def remove_background(
    source: Path,
    target: Path,
    *,
    tolerance: int = DEFAULT_TOLERANCE,
) -> Path:
    """从四角洪泛填充背景并转成透明。返回输出路径。"""
    with Image.open(source) as opened:
        image = opened.convert("RGB")

    width, height = image.size
    # 用一个不会被画面用到的标记色
    marker = (255, 0, 255)
    masked = image.copy()

    # 四角都试一次：背景可能不是完全均匀
    for corner in (
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
    ):
        try:
            ImageDraw.floodfill(masked, corner, marker, thresh=tolerance)
        except ValueError:
            # 坐标越界等异常不必中断整个流程
            continue

    # 用标记色生成 alpha
    rgba = image.convert("RGBA")
    pixels = masked.load()
    alpha = rgba.load()
    for y in range(height):
        for x in range(width):
            if pixels[x, y] == marker:
                r, g, b, _ = alpha[x, y]
                alpha[x, y] = (r, g, b, 0)

    target.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(target, "PNG")
    return target


def trim_transparent(source: Path, target: Path, *, padding: int = 8) -> Path:
    """按非透明区域裁掉多余边距，让立绘贴边更紧凑。"""
    with Image.open(source) as opened:
        image = opened.convert("RGBA")

    bbox = image.getbbox()
    if bbox is None:
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, "PNG")
        return target

    left, top, right, bottom = bbox
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(image.width, right + padding)
    bottom = min(image.height, bottom + padding)

    target.parent.mkdir(parents=True, exist_ok=True)
    image.crop((left, top, right, bottom)).save(target, "PNG")
    return target
