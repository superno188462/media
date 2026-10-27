"""分镜 JSON → mp4，输出一行 JSON。

用法::

    # 只看分镜有没有问题、会渲染几帧
    uv run --with playwright --no-project python scripts/render_video.py \
        --storyboard scenes.json --out video.mp4 --dry-run

    # 真正出片
    uv run --with playwright --no-project python scripts/render_video.py \
        --storyboard scenes.json --audio voice.mp3 --out video.mp4

    # 同时抽 5 张关键帧（审核卡片用，飞书卡片不能播视频）
    ... --keyframes 5

输出约定与其余脚本一致：成功 ``{"ok": true, "data": {...}}``。

**本脚本不发布任何内容。** 视频仍需走审核链路。
"""

from __future__ import annotations

import argparse
import json
import time
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

sys.path.insert(0, str(_HERE.parents[1] / "src"))

from content.video import (  # noqa: E402
    ComposeError,
    PlaywrightRenderer,
    RendererError,
    Storyboard,
    compose_motion,
    extract_keyframes,
    transition_boundaries,
    layout,
    voice,
)
from content.video import motion as motion_tool  # noqa: E402
from content.video import composite  # noqa: E402
from content.video import pet as pet_mod  # noqa: E402
from content.video import petconfig  # noqa: E402
from content.video import petstate  # noqa: E402

#: 渲染中间产物不放 .local：实测 ffmpeg 子进程写不进去。
DEFAULT_WORK_DIR = _HERE.parents[1] / ".runtime" / "video"


def fail(code: str, message: str, hint: str = "") -> int:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if hint:
        payload["error"]["hint"] = hint
    print(json.dumps(payload, ensure_ascii=False))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", required=True, help="分镜 JSON")
    parser.add_argument("--out", required=True, help="输出 mp4")
    parser.add_argument("--audio", default=None, help="已有音轨；与 --tts 二选一")
    parser.add_argument("--tts", action="store_true",
                        help="按镜头合成配音，并用实际语音时长决定每场时长")
    parser.add_argument("--speaker", default=None, help="TTS 音色（短名或完整 ID）")
    parser.add_argument("--speed", type=float, default=None, help="TTS 语速")
    parser.add_argument("--gap-ms", type=int, default=450, help="每句后的留白")
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR))
    parser.add_argument("--keyframes", type=int, default=0, help="抽几张关键帧")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--transition-ms", type=int, default=motion_tool.DEFAULT_TRANSITION_MS,
                        help="转场时长；0 表示无转场（硬切）")
    parser.add_argument("--pet", action="store_true",
                        help="角色独立运动：UI 静止，角色随机游走，压到 UI 会被拖走")
    parser.add_argument("--pet-config", default=None,
                        help="宠物配置文件（隐含 --pet）；见 examples/pet_config.json")
    parser.add_argument("--seed", type=int, default=None,
                        help="覆盖配置里的种子；0 表示按当前时间随机")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    storyboard_path = Path(args.storyboard)
    if not storyboard_path.exists():
        return fail("INVALID_ARGS", f"分镜文件不存在：{storyboard_path}")

    try:
        storyboard = Storyboard.load(storyboard_path)
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        return fail("INVALID_ARGS", f"分镜解析失败：{exc}")

    problems = storyboard.validate()
    if problems:
        return fail("STORYBOARD_INVALID", "；".join(problems), "修正分镜后重试")

    summary = {
        "scenes": len(storyboard.scenes),
        "total_ms": storyboard.total_ms,
        "width": storyboard.width,
        "height": storyboard.height,
        "assets": storyboard.assets,
        "out": str(Path(args.out)),
        "audio": args.audio,
        "tts": args.tts,
    }

    if args.dry_run:
        print(json.dumps({"ok": True, "data": {"dry_run": True, **summary}},
                         ensure_ascii=False, indent=2))
        return 0

    work_dir = Path(args.work_dir)
    frames_dir = work_dir / "frames"

    # --- 配音：按镜头合成，并用真实时长决定每场多长 ---
    audio_path: Path | None = Path(args.audio) if args.audio else None
    holds = storyboard.holds()
    voices_info: list[dict] = []

    if args.tts:
        try:
            voices = voice.plan(
                storyboard,
                work_dir / "voice",
                speaker=voice.tts_tool.resolve_speaker(args.speaker or voice.tts_tool.DEFAULT_SPEAKER),
                speed=args.speed,
                gap_ms=args.gap_ms,
            )
            holds = [v.hold_ms for v in voices]
            # 把配音推出的时长写回分镜，供后续 card_reveal 展开按时长均分。
            # 必须先配音后展开：否则同一句话会被拆成多段重复合成。
            for scene, hold in zip(storyboard.scenes, holds):
                scene.hold_ms = hold
            audio_path = voice.build_track(
                voices, work_dir / "voice" / "track.mp3",
                gap_ms=args.gap_ms, work_dir=work_dir / "voice",
            )
            voices_info = [
                {
                    "index": v.index, "text": v.text, "audio_ms": v.audio_ms,
                    "hold_ms": v.hold_ms, "audio": str(v.audio) if v.audio else None,
                }
                for v in voices
            ]
        except voice.tts_tool.TtsError as exc:
            return fail("TTS_FAILED", str(exc), "检查 VOLC_API_KEY 与音色名")

    if any(s.hold_ms <= 0 for s in storyboard.scenes):
        return fail(
            "STORYBOARD_INVALID",
            "有镜头时长为 0 且没有配音可推算",
            "给这些镜头写 hold_ms，或开启 --tts",
        )

    # 卡片逐条出现：一屏拆多屏，总时长不变
    storyboard = layout.expand_card_reveal(storyboard)
    notes = layout.audit(storyboard)

    holds = [s.hold_ms for s in storyboard.scenes]
    motions = [layout.resolve_motion(s) for s in storyboard.scenes]

    # 转场：所有屏都写 none 时退化为硬切
    transition_ms = args.transition_ms
    if storyboard.scenes and all(layout.resolve_transition(s) == "none" for s in storyboard.scenes):
        transition_ms = 0

    pet_info: dict | None = None

    pet_enabled = args.pet or bool(args.pet_config)
    if pet_enabled:
        try:
            config = (
                petconfig.PetConfig.load(Path(args.pet_config))
                if args.pet_config else petconfig.PetConfig()
            )
        except petconfig.ConfigError as exc:
            return fail("PET_CONFIG_INVALID", str(exc))

        # 分层：背景不含角色，角色单独合成
        try:
            with PlaywrightRenderer() as renderer:
                backgrounds = renderer.render_all(storyboard, frames_dir, hide_character=True)
        except RendererError as exc:
            return fail("RENDER_FAILED", str(exc))

        width, height = storyboard.width, storyboard.height
        stage = pet_mod.Rect(0, 0, width, height)
        seed = args.seed if args.seed is not None else config.seed
        if not seed:
            seed = int(time.time()) % 1_000_000

        planner = pet_mod.PetPlanner(
            seed=seed, fps=args.fps, stage=stage,
            pet_size=(config.size, config.size),
            wander=config.wander_rect(width, height),
            protected=config.protected_rects(),
            trigger_ratio=config.trigger_ratio,
            mischief_chance=config.mischief_chance,
        )
        slots = planner.frames(sum(holds))
        pet_info = planner.summary(slots)

        # 动作素材按名字加载；缺素材的动作在 action_specs() 里已被剔除
        try:
            specs = config.action_specs()
        except (petconfig.ConfigError, petstate.ActionError) as exc:
            return fail("PET_CONFIG_INVALID", str(exc))

        # 帧源要覆盖配置里的**所有**动作：walk / grab 不在权重表里，
        # 但分别是"换位置"和"被拎起来"时用的，漏了就拿不到素材。
        action_clips: dict = {}
        for name in config.clips:
            try:
                action_clips[name] = config.build_clip(name)
            except Exception as exc:  # noqa: BLE001
                return fail("PET_CLIP_FAILED", f"{name}: {type(exc).__name__}: {exc}")

        # 被拖走时用 grab 动作；没有素材就退回 idle
        grab = config.grab_action
        if grab not in action_clips:
            grab = "idle"

        plan = petstate.plan_actions(
            sum(holds), fps=args.fps, specs=specs,
            drag_flags=[f.dragging for f in slots],
            move_flags=[f.moving for f in slots],
            seed=seed,
            available=set(action_clips),
        )
        # 拖拽优先于走路：被拎起来时不该显示走路
        actions = [
            grab if f.dragging else a
            for a, f in zip(plan.actions, slots)
        ]

        pet_info.update({
            "source": config.source,
            "actions": plan.summary()["actions"],
            "segments": plan.summary()["segments"],
            "clip_fps": config.clip_fps,
            "size": config.size,
            "frames_available": {k: getattr(v, "frame_count", 1) for k, v in action_clips.items()},
            "hand": bool(config.hand),
        })

        try:
            result = composite.compose_layers(
                backgrounds, holds, Path(args.out),
                pet_frames=slots, actions=actions, action_clips=action_clips,
                hand=Path(config.hand) if config.hand else None,
                sprite_height=config.size,
                audio=audio_path, fps=args.fps, transition_ms=transition_ms,
                size=(width, height),
            )
        except composite.CompositeError as exc:
            return fail("COMPOSE_FAILED", str(exc))
    else:
        try:
            with PlaywrightRenderer() as renderer:
                frames = renderer.render_all(storyboard, frames_dir)
        except RendererError as exc:
            return fail("RENDER_FAILED", str(exc))
        except Exception as exc:  # noqa: BLE001
            return fail("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")

        try:
            result = compose_motion(
                frames, holds, Path(args.out), motions,
                audio=audio_path, fps=args.fps, transition_ms=transition_ms,
                size=(storyboard.width, storyboard.height),
            )
        except (ComposeError, motion_tool.MotionError) as exc:
            return fail("COMPOSE_FAILED", str(exc))

    keyframes: list[str] = []
    if args.keyframes > 0:
        try:
            avoid = transition_boundaries(holds, transition_ms)
            keyframes = [
                str(p) for p in extract_keyframes(
                    result.path, args.keyframes, work_dir / "keyframes", avoid_ms=avoid)
            ]
        except ComposeError as exc:
            return fail("KEYFRAME_FAILED", str(exc))

    print(json.dumps({
        "ok": True,
        "data": {
            **summary,
            "path": str(result.path),
            "bytes": result.bytes,
            "duration_ms": result.duration_ms,
            "frames": result.frames,
            "fps": result.fps,
            "has_audio": result.has_audio,
            "holds": holds,
            "motions": motions,
            "layouts": [s.layout for s in storyboard.scenes],
            "transition_ms": transition_ms,
            "design_notes": notes,
            "pet": pet_info,
            "voices": voices_info,
            "keyframes": keyframes,
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
