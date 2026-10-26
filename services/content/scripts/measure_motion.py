"""测量成片的画面运动量，输出一行 JSON。

用途：CHANGE-003 的问题「每屏一样、画面不动」是可以用数字量化的。
本脚本把「有没有动」变成可回归的指标，而不是只靠肉眼看。

方法：按固定帧率抽帧，算相邻帧的平均灰度差。

- **非转场区间**的差异反映运镜幅度；长期接近 0 说明是纯静帧
- **转场点**的差异明显更高，可用于确认淡入淡出真的生效

用法::

    uv run --with pillow --no-project python scripts/measure_motion.py \\
        --video .runtime/test01.mp4

参考值（1920×1080 / 30fps / 运镜 4% / 转场 0.3s）：

    静帧基线   非转场中位数 0.00，几乎静止占比 98.7%
    运镜版本   非转场中位数 2.63，几乎静止占比 13.7%
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1] / "src"))

from content import ffmpeg as ffmpeg_tool  # noqa: E402

#: 抽帧帧率。5fps 足够看运动，又不至于太慢。
SAMPLE_FPS = 5

#: 判定为转场的差异阈值。运镜通常 < 20，转场 > 25。
TRANSITION_THRESHOLD = 25.0

#: 低于这个差异认为「画面几乎静止」。
STATIC_THRESHOLD = 1.0


def fail(code: str, message: str, hint: str = "") -> int:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if hint:
        payload["error"]["hint"] = hint
    print(json.dumps(payload, ensure_ascii=False))
    return 1


def mean_abs_diff(a: Path, b: Path) -> float:
    from PIL import Image, ImageChops

    left = Image.open(a).convert("L")
    right = Image.open(b).convert("L")
    histogram = ImageChops.difference(left, right).histogram()
    total = sum(histogram)
    if not total:
        return 0.0
    return sum(value * count for value, count in enumerate(histogram)) / total


def measure(video: Path, fps: int = SAMPLE_FPS) -> dict:
    with tempfile.TemporaryDirectory(dir=str(video.parent)) as tmp:
        work = Path(tmp)
        result = ffmpeg_tool.run(
            ["-i", str(video), "-vf", f"fps={fps}", "-q:v", "4", str(work / "f%05d.jpg")],
            timeout=900,
        )
        if result.returncode != 0:
            raise RuntimeError(f"抽帧失败：{(result.stderr or '')[-400:]}")

        frames = sorted(work.glob("f*.jpg"))
        if len(frames) < 2:
            raise RuntimeError("抽到的帧太少，无法测量")

        diffs = [
            mean_abs_diff(frames[i], frames[i + 1]) for i in range(len(frames) - 1)
        ]

    transitions = [i * (1 / fps) for i, d in enumerate(diffs) if d >= TRANSITION_THRESHOLD]
    quiet = [d for d in diffs if d < TRANSITION_THRESHOLD]
    static_ratio = (
        sum(1 for d in quiet if d < STATIC_THRESHOLD) / len(quiet) * 100 if quiet else 0.0
    )

    return {
        "frames_sampled": len(frames),
        "intervals": len(diffs),
        "transitions_detected": len(transitions),
        "transition_times_s": [round(t, 2) for t in transitions],
        "motion_median": round(statistics.median(quiet), 3) if quiet else 0.0,
        "motion_min": round(min(quiet), 3) if quiet else 0.0,
        "motion_max": round(max(quiet), 3) if quiet else 0.0,
        "static_ratio_pct": round(static_ratio, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--fps", type=int, default=SAMPLE_FPS)
    args = parser.parse_args()

    video = Path(args.video)
    if not video.is_file():
        return fail("INVALID_ARGS", f"视频不存在：{video}")

    try:
        data = measure(video, args.fps)
    except (RuntimeError, OSError) as exc:
        return fail("MEASURE_FAILED", str(exc))

    # 判读：静止占比高说明运镜没生效或分镜全是静帧
    verdict = "画面在动" if data["static_ratio_pct"] < 40 else "画面基本静止"
    print(json.dumps({"ok": True, "data": {**data, "verdict": verdict}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
