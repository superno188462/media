"""把标题、正文、配图排成一张可发布的成稿，输出一行 JSON。

用法::

    uv run --with pillow --no-project python scripts/render_post.py \
        --title "内卷树懒 · 第一条图文" \
        --body-file body.txt \
        --image pic.jpg \
        --out D:/github/robot/.local/content/posts/post.jpg

输出约定与 bili-cli 一致：

    成功 {"ok": true, "data": {"path", "width", "height", "images"}}
    失败 {"ok": false, "error": {"code", "message", "hint"}}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

sys.path.insert(0, str(_HERE.parents[1] / "src"))

from PIL import Image  # noqa: E402

from content.render import MAX_EDGE, RenderOptions, render_post  # noqa: E402


def fail(code: str, message: str, hint: str = "") -> int:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if hint:
        payload["error"]["hint"] = hint
    print(json.dumps(payload, ensure_ascii=False))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True, help="正文文件（UTF-8）")
    parser.add_argument("--image", action="append", default=[], help="配图，可重复，顺序即发布顺序")
    parser.add_argument("--out", required=True, help="输出图片路径")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--max-edge", type=int, default=MAX_EDGE)
    args = parser.parse_args()

    body_path = Path(args.body_file)
    if not body_path.exists():
        return fail("INVALID_ARGS", f"正文文件不存在：{body_path}")

    body = body_path.read_text(encoding="utf-8").strip()
    if not body:
        return fail("INVALID_ARGS", "正文为空", "契约要求正文至少 1 个字符")

    images = [Path(p) for p in args.image]
    for path in images:
        if not path.exists():
            return fail("ASSET_MISSING", f"配图不存在：{path}")

    try:
        out = render_post(
            title=args.title,
            body=body,
            images=images,
            out_path=Path(args.out),
            options=RenderOptions(width=args.width),
        )
    except Exception as exc:  # noqa: BLE001
        return fail("RENDER_FAILED", f"{type(exc).__name__}: {exc}")

    with Image.open(out) as rendered:
        width, height = rendered.size

    if max(width, height) > args.max_edge:
        return fail(
            "TOO_LARGE",
            f"成稿 {width}x{height} 超过长边上限 {args.max_edge}",
            "缩小 --width 或减少配图",
        )

    print(json.dumps({
        "ok": True,
        "data": {
            "path": str(out),
            "width": width,
            "height": height,
            "images": [str(p) for p in images],
            "body_chars": len(body),
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
