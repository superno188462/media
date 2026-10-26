"""把生图产出的原始帧加工成可播放的宠物动作帧。

输入约定：``--raw`` 目录下每个子目录是一帧（如 ``f0/seedream_0.jpg``），
子目录名按自然序排序后作为播放顺序。

处理三步：

1. **抠图**：纯色背景洪泛填充 → 透明通道
2. **裁剪**：按非透明区域裁掉多余边
3. **归一化**：统一缩放到目标高度 → 居中到同宽画布 → 尺寸完全一致

第 3 步是必须的：抠图按内容裁剪，每帧尺寸都不同；不归一化的话
播放时角色会上下跳。

用法::

    uv run --with pillow --no-project python scripts/build_pet_frames.py \\
        --raw .runtime/pet_raw/eat --out assets/pet/eat --height 900
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1] / "src"))

from content.imagegen.cutout import remove_background, trim_transparent  # noqa: E402

DEFAULT_HEIGHT = 900
#: 抠图容差。背景是纯色米黄，26–32 比较稳。
DEFAULT_TOLERANCE = 30

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def fail(code: str, message: str, hint: str = "") -> int:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if hint:
        payload["error"]["hint"] = hint
    print(json.dumps(payload, ensure_ascii=False))
    return 1


def _natural_key(path: Path) -> list:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", path.name)]


def _first_image(directory: Path) -> Path | None:
    for candidate in sorted(directory.iterdir(), key=_natural_key):
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_SUFFIXES:
            return candidate
    return None


def build(raw: Path, out: Path, *, height: int, tolerance: int) -> list[Path]:
    from PIL import Image

    if not raw.is_dir():
        raise FileNotFoundError(f"原始帧目录不存在：{raw}")

    frame_dirs = [p for p in sorted(raw.iterdir(), key=_natural_key) if p.is_dir()]
    if not frame_dirs:
        raise ValueError(f"目录下没有帧子目录：{raw}")

    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.png"):
        stale.unlink()

    # 先全部抠图 + 裁剪
    cut: list = []
    for frame_dir in frame_dirs:
        source = _first_image(frame_dir)
        if source is None:
            raise ValueError(f"帧目录里没有图片：{frame_dir}")
        intermediate = out.parent / f".{out.name}_raw.png"
        remove_background(source, intermediate, tolerance=tolerance)
        cut.append(trim_transparent(intermediate, intermediate))

    # 统一缩放到目标高度，量出最宽
    scaled = []
    for path in cut:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
        width = max(1, round(image.width * height / image.height))
        scaled.append(image.resize((width, height), Image.LANCZOS))

    canvas_w = max(image.width for image in scaled)
    written: list[Path] = []
    for index, image in enumerate(scaled):
        canvas = Image.new("RGBA", (canvas_w, height), (0, 0, 0, 0))
        # 水平居中；垂直方向已经同高，顶对齐即可
        canvas.paste(image, ((canvas_w - image.width) // 2, 0), image)
        target = out / f"{index:02d}.png"
        canvas.save(target, "PNG")
        written.append(target)

    for path in cut:
        path.unlink(missing_ok=True)

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, help="生图产出的原始帧目录")
    parser.add_argument("--out", required=True, help="输出到 assets/pet/<动作名>/")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--tolerance", type=int, default=DEFAULT_TOLERANCE)
    args = parser.parse_args()

    try:
        written = build(
            Path(args.raw), Path(args.out),
            height=args.height, tolerance=args.tolerance,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        return fail("BUILD_FAILED", str(exc))

    from PIL import Image

    size = Image.open(written[0]).size if written else (0, 0)
    print(json.dumps({
        "ok": True,
        "data": {
            "action": Path(args.out).name,
            "frames": len(written),
            "canvas": list(size),
            "dir": str(Path(args.out)),
            "files": [p.name for p in written],
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
