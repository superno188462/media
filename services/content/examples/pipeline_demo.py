"""端到端演练：选题 → 文案 → 配图 → 组稿 → 校验。

这不是发布脚本——它只走到「待人工审核」为止。
发布必须由人工批准后单独执行（见 publish/bilibili.py）。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from content.imagegen.base import ImageRequest
from content.imagegen.volcengine import VolcengineImageGenerator
from content.model import ContentItem
from content.render import render_post
from content.validate import validate

NEGATIVE = (
    "text, letters, words, typography, caption, handwriting, slogan, "
    "watermark, signature, ui elements, decorative icons, doodle, "
    "cyberpunk, neon glow, sci-fi, server room, mechanical, robotic, "
    "futuristic headset, glowing keyboard, photorealistic, 3d render, "
    "dark gritty lighting, extra limbs, deformed"
)

POSITIVE = (
    "anime character illustration, cute sloth mascot, soft fluffy brown fur, "
    "round black-rimmed glasses, half-lidded relaxed sleepy eyes, subtle gentle smile, "
    "holding a white coffee mug with both paws, warm cozy atmosphere, "
    "clean cel-shading, flat colors with soft gradient shading, warm natural lighting, "
    "plain simple pastel beige background, upper body portrait, centered composition, "
    "high quality anime art, masterpiece, best quality"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="D:/github/robot/.local/content/demo", type=Path)
    parser.add_argument("--no-generate", action="store_true", help="跳过生图，用占位图")
    args = parser.parse_args()

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. 配图
    if args.no_generate:
        from PIL import Image

        placeholder = out_dir / "placeholder.png"
        Image.new("RGB", (1024, 1024), (240, 230, 215)).save(placeholder)
        image_paths = [placeholder]
        model = "placeholder"
    else:
        gen = VolcengineImageGenerator()
        result = gen.generate(
            ImageRequest(prompt=POSITIVE, negative_prompt=NEGATIVE, size="1K"),
            out_dir=out_dir,
        )
        image_paths = result.paths
        model = result.model

    # 2. 文案
    body = (
        "这条是自动化创作流水线跑出来的第一张成稿：\n"
        "选题由人给，文案和配图由模型出，最后拼成一张可发布的图。\n"
        "模型不能自己按下发布键，这一步要人工确认。\n"
        "本文配图由 AI 生成，人工审核后发布。"
    )

    # 3. 组稿
    post_path = render_post(
        title="内卷树懒 · 第一条图文",
        body=body,
        images=image_paths,
        out_path=out_dir / "post.jpg",
    )

    # 4. 校验
    item = ContentItem(
        id="demo-001",
        topic_id="demo",
        title="内卷树懒 · 第一条图文",
        body=body,
        images=[str(p) for p in image_paths],
        source_urls=[f"volcengine:{model}"],
        ai_declaration="本文配图由 AI 生成，人工审核后发布。",
        status="pending_review",
    )

    print(f"配图模型 : {model}")
    print(f"成稿路径 : {post_path}")
    print(f"内容状态 : {item.status}")
    print("校验结果 :")
    violations = validate(item)
    if violations:
        for v in violations:
            print(f"  {v}")
    else:
        print("  通过（待人工审核）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
