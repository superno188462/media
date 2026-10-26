"""生成配图，输出一行 JSON。

用法::

    # 用角色预设出图（推荐：形象稳定，不用每次自己拼 prompt）
    uv run --with pillow --no-project python scripts/gen_image.py \
        --preset cozy --out-dir D:/github/robot/.local/content/posts

    # 完全自定义 prompt
    uv run --with pillow --no-project python scripts/gen_image.py \
        --prompt "anime sloth, ..." --size 1K

    # 只看会调用什么，不真调
    ... --dry-run

输出约定与 bili-cli 一致：

    成功 {"ok": true, "data": {...}}
    失败 {"ok": false, "error": {"code", "message", "hint"}}

凭据：``VOLC_API_KEY``，可从环境变量或 ``.local/dsh/.credentials.yaml`` 读取。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

sys.path.insert(0, str(_HERE.parents[1] / "src"))

from content.imagegen.base import ImageGenerationError, ImageRequest  # noqa: E402
from content.imagegen.volcengine import VolcengineImageGenerator  # noqa: E402

CRED_FILE = PROJECT_ROOT / ".local" / "dsh" / ".credentials.yaml"

#: 角色设定固定在这里，避免每次现编 prompt 导致形象漂移。
#: 详见 src/content/imagegen/prompts/neijuan_sloth.md
NEGATIVE = (
    "text, letters, words, typography, caption, handwriting, slogan, "
    "watermark, signature, ui elements, decorative icons, doodle, "
    "cyberpunk, neon glow, sci-fi, server room, mechanical, robotic, "
    "futuristic headset, glowing keyboard, photorealistic, 3d render, "
    "dark gritty lighting, extra limbs, deformed"
)

BASE = (
    "anime character illustration, cute sloth mascot, soft fluffy brown fur, "
    "round black-rimmed glasses, half-lidded relaxed sleepy eyes, subtle gentle smile, "
    "{pose}, clean cel-shading, flat colors with soft gradient shading, "
    "soft natural lighting, plain simple pastel beige background, "
    "high quality anime art, masterpiece, best quality"
)

PRESETS = {
    "head": "extreme close-up face portrait, looking at viewer",
    "bust": "holding both cheeks with paws, cozy relaxed posture, upper body portrait",
    "cozy": "holding a white coffee mug with both paws, warm cozy atmosphere, upper body portrait",
}


def load_api_key() -> str:
    key = os.environ.get("VOLC_API_KEY", "")
    if key:
        return key
    if CRED_FILE.exists():
        match = re.search(
            r"^\s*VOLC_API_KEY:\s*(\S+)\s*$",
            CRED_FILE.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            return match.group(1)
    return ""


def fail(code: str, message: str, hint: str = "") -> int:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if hint:
        payload["error"]["hint"] = hint
    print(json.dumps(payload, ensure_ascii=False))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=sorted(PRESETS), help="角色预设")
    parser.add_argument("--prompt", help="自定义正向提示词（与 --preset 二选一）")
    parser.add_argument("--negative", default=NEGATIVE)
    parser.add_argument("--size", default="1K", help="1K / 2K 或 宽x高")
    parser.add_argument("--out-dir", default=str(PROJECT_ROOT / ".local" / "content" / "posts"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.preset and not args.prompt:
        return fail("INVALID_ARGS", "需要 --preset 或 --prompt 之一")

    if args.preset:
        prompt = BASE.format(pose=PRESETS[args.preset])
    else:
        prompt = args.prompt

    out_dir = Path(args.out_dir)
    request = ImageRequest(prompt=prompt, negative_prompt=args.negative, size=args.size)

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "data": {
                "dry_run": True,
                "preset": args.preset,
                "size": args.size,
                "out_dir": str(out_dir),
                "prompt": prompt,
                "negative_prompt": args.negative,
            },
        }, ensure_ascii=False, indent=2))
        return 0

    api_key = load_api_key()
    if not api_key:
        return fail(
            "NO_CREDENTIAL",
            "缺少 VOLC_API_KEY",
            "写进 .local/dsh/.credentials.yaml 或设为环境变量",
        )

    try:
        generator = VolcengineImageGenerator(api_key=api_key)
        result = generator.generate(request, out_dir)
    except ImageGenerationError as exc:
        return fail("IMAGE_FAILED", str(exc), "检查配额、模型名或网络")
    except Exception as exc:  # noqa: BLE001
        return fail("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")

    print(json.dumps({
        "ok": True,
        "data": {
            "paths": [str(p) for p in result.paths],
            "model": result.model,
            "usage": result.usage,
            "out_dir": str(out_dir),
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
