"""豆包 Seedance 视频生成 CLI，输出一行 JSON。

用法::

    # 只看会请求什么，不真调
    uv run python scripts/gen_video.py --prompt "..." --duration 4 --dry-run

    # 首帧图生视频（本地 PNG 直接传，不需要图床）
    uv run python scripts/gen_video.py \\
        --prompt "the sloth breathes and blinks, subtle idle animation" \\
        --first-frame assets/pet/idle/00.png \\
        --duration 4 --ratio 1:1 --out .runtime/clips/idle.mp4

    # 只建任务不等待
    ... --no-wait

    # 查询已有任务
    uv run python scripts/gen_video.py --task-id cgt-xxxx --out out.mp4

计费按秒，``--duration`` 直接决定花费；默认取最小值 4 秒。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

sys.path.insert(0, str(_HERE.parents[1] / "src"))

from content.video import seedance  # noqa: E402


def fail(code: str, message: str, hint: str = "") -> int:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if hint:
        payload["error"]["hint"] = hint
    print(json.dumps(payload, ensure_ascii=False))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", help="提示词")
    parser.add_argument("--first-frame", default=None, help="首帧图片（本地路径）")
    parser.add_argument("--reference-image", action="append", default=[],
                        help="参考图，可重复")
    parser.add_argument("--model", default=seedance.DEFAULT_MODEL,
                        help=f"模型 ID；短名见 {sorted(seedance.MODELS)}")
    parser.add_argument("--duration", type=int, default=4, help="时长（秒），按秒计费")
    parser.add_argument("--ratio", default="16:9", choices=sorted(seedance.RATIOS))
    parser.add_argument("--resolution", default=None, choices=sorted(seedance.RESOLUTIONS))
    parser.add_argument("--audio", action="store_true", help="生成音频（默认关闭）")
    parser.add_argument("--out", help="输出 mp4 路径")
    parser.add_argument("--task-id", help="查询已有任务，不新建")
    parser.add_argument("--no-wait", action="store_true", help="只建任务，不等待")
    parser.add_argument("--timeout", type=int, default=900, help="等待上限（秒）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.task_id and not args.prompt:
        return fail("INVALID_ARGS", "需要 --prompt 或 --task-id")

    model = seedance.MODELS.get(args.model, args.model)

    first_frame = Path(args.first_frame) if args.first_frame else None
    if first_frame is not None and not first_frame.is_file():
        return fail("INVALID_ARGS", f"首帧不存在：{first_frame}")

    references = []
    for item in args.reference_image:
        path = Path(item)
        if not path.is_file():
            return fail("INVALID_ARGS", f"参考图不存在：{path}")
        references.append(path)

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "data": {
                "dry_run": True,
                "url": seedance.BASE_URL + seedance.CREATE_PATH,
                "model": model,
                "duration_s": args.duration,
                "ratio": args.ratio,
                "resolution": args.resolution,
                "generate_audio": args.audio,
                "first_frame": str(first_frame) if first_frame else None,
                "reference_images": [str(p) for p in references],
                "note": "本地图会转成 data URI 传输，不需要公网图床",
            },
        }, ensure_ascii=False, indent=2))
        return 0

    # --- 查询模式 ---
    if args.task_id:
        try:
            task = seedance.query_task(args.task_id)
            if not task.done and not args.no_wait:
                task = seedance.wait_task(
                    args.task_id, timeout_s=args.timeout,
                    on_progress=lambda t: print(f"[状态] {t.status}", file=sys.stderr),
                )
        except seedance.SeedanceError as exc:
            return fail("QUERY_FAILED", str(exc))
        return _finish(task, args, model)

    # --- 创建模式 ---
    try:
        task = seedance.create_task(
            args.prompt,
            model=model,
            duration=args.duration,
            ratio=args.ratio,
            resolution=args.resolution,
            generate_audio=args.audio,
            first_frame=first_frame,
            reference_images=references,
        )
    except seedance.SeedanceError as exc:
        return fail("CREATE_FAILED", str(exc))

    print(f"[任务] {task.task_id} 状态={task.status}", file=sys.stderr)

    if args.no_wait:
        print(json.dumps({
            "ok": True,
            "data": {
                "task_id": task.task_id,
                "status": task.status,
                "model": model,
                "duration_s": args.duration,
                "queried_with": f"--task-id {task.task_id}",
            },
        }, ensure_ascii=False, indent=2))
        return 0

    started = time.time()
    try:
        task = seedance.wait_task(
            task.task_id, timeout_s=args.timeout,
            on_progress=lambda t: print(f"[状态] {t.status}", file=sys.stderr),
        )
    except seedance.SeedanceError as exc:
        return fail("GENERATION_FAILED", str(exc), f"任务 {task.task_id} 可用 --task-id 复查")

    elapsed = round(time.time() - started, 1)
    return _finish(task, args, model, elapsed)


def _finish(task, args, model: str, elapsed: float | None = None) -> int:
    data = {
        "task_id": task.task_id,
        "status": task.status,
        "model": model,
    }
    if elapsed is not None:
        data["elapsed_s"] = elapsed

    if not task.ok:
        print(json.dumps({"ok": False, "data": data,
                          "error": {"code": "NOT_SUCCEEDED", "message": f"状态 {task.status}"}},
                         ensure_ascii=False, indent=2))
        return 1

    data["video_url"] = task.video_url

    if args.out:
        try:
            target = seedance.download(task.video_url, Path(args.out))
        except seedance.SeedanceError as exc:
            return fail("DOWNLOAD_FAILED", str(exc))
        data["path"] = str(target)
        data["bytes"] = target.stat().st_size

    print(json.dumps({"ok": True, "data": data}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
