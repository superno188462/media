"""分层合成：背景（UI）静止，角色独立运动。

为什么不用 ffmpeg 的 overlay 表达式：角色的位置来自"踩到 UI 就掉头"的
离散事件，用连续函数表达不了。所以位置在 Python 里算好，逐帧合成，
把 RGB 帧直接写进 ffmpeg 的 stdin（不落盘，避免上千张 PNG 的 IO）。

时长仍然是精确的：帧数 = round(总时长 × fps)，转场在时间轴上按
[边界 − d, 边界) 做交叉淡化，不改变总时长。
"""

from __future__ import annotations

import io
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import ffmpeg as ffmpeg_tool
from . import pet as pet_mod

DEFAULT_FPS = 30
DEFAULT_CRF = 20


@dataclass
class LayerResult:
    path: Path
    duration_ms: int
    frames: int
    fps: int
    has_audio: bool
    bytes: int


class CompositeError(RuntimeError):
    """分层合成失败。"""


def scene_at(t_ms: float, holds_ms: list[int]) -> tuple[int, float]:
    """返回 ``(场景下标, 该场景内的相对时间)``。"""
    accumulated = 0
    for index, hold in enumerate(holds_ms):
        if t_ms < accumulated + hold:
            return index, t_ms - accumulated
        accumulated += hold
    # 落在末尾（浮点误差）：归到最后一屏
    return len(holds_ms) - 1, float(holds_ms[-1])


def blend_weight(t_ms: float, holds_ms: list[int], transition_ms: int) -> tuple[int, int, float]:
    """返回 ``(当前屏, 下一屏, 下一屏权重)``。权重为 0 表示不混合。"""
    index, offset = scene_at(t_ms, holds_ms)
    if transition_ms <= 0 or index >= len(holds_ms) - 1:
        return index, index, 0.0

    hold = holds_ms[index]
    start = hold - transition_ms
    if offset < start:
        return index, index, 0.0

    weight = min(1.0, max(0.0, (offset - start) / transition_ms))
    return index, index + 1, weight


def _prepare_sprite(path: Path, height: int):
    from PIL import Image

    with Image.open(path) as opened:
        sprite = opened.convert("RGBA")
    scale = height / sprite.height
    width = max(1, round(sprite.width * scale))
    return sprite.resize((width, height), Image.LANCZOS)


def compose_layers(
    backgrounds: list[Path],
    holds_ms: list[int],
    out_path: Path,
    *,
    clips_by_scene: list | None = None,
    pet_frames: list[pet_mod.PetFrame] | None = None,
    sprite_height: int = 420,
    audio: Path | None = None,
    fps: int = DEFAULT_FPS,
    crf: int = DEFAULT_CRF,
    transition_ms: int = 300,
    size: tuple[int, int] = (1920, 1080),
) -> LayerResult:
    """把背景与角色合成 mp4。

    ``clips_by_scene`` 每项是 ``petclip`` 里的一种帧源（Flipbook/Static/Video），
    为 None 表示该屏不画角色。转场期间两屏的帧会交叉淡化。

    用帧源而不是图片，是为了让"动作"和"素材来源"解耦：
    翻页动画和将来视频生成的片段都走同一条路径。
    """
    from PIL import Image

    if not backgrounds:
        raise CompositeError("没有背景帧")
    if len(backgrounds) != len(holds_ms):
        raise CompositeError("背景数与时长数不一致")

    width, height = size
    total_ms = sum(holds_ms)
    if total_ms <= 0:
        raise CompositeError("总时长为 0")

    scene_images = []
    for path in backgrounds:
        if not path.is_file():
            raise CompositeError(f"背景不存在：{path}")
        with Image.open(path) as opened:
            scene_images.append(opened.convert("RGB").resize((width, height), Image.LANCZOS))

    prepared = list(clips_by_scene or [None] * len(backgrounds))
    if len(prepared) != len(backgrounds):
        raise CompositeError("帧源数量与背景数量不一致")

    frame_count = max(1, round(total_ms / 1000 * fps))
    if pet_frames is not None and len(pet_frames) < frame_count:
        raise CompositeError(
            f"角色轨迹只有 {len(pet_frames)} 帧，需要 {frame_count} 帧"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0",
    ]
    if audio is not None:
        if not audio.is_file():
            raise CompositeError(f"音轨不存在：{audio}")
        args += ["-i", str(audio)]
    args += [
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-tune", "stillimage",
        "-movflags", "+faststart",
    ]
    if audio is not None:
        args += ["-c:a", "aac", "-b:a", "128k"]
    args.append(str(out_path))

    binary = ffmpeg_tool.find()
    process = subprocess.Popen(
        [str(binary), "-hide_banner", "-nostdin", "-y", *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    try:
        assert process.stdin is not None
        for frame_index in range(frame_count):
            t_ms = frame_index * 1000.0 / fps
            current, upcoming, weight = blend_weight(t_ms, holds_ms, transition_ms)

            # 必须 copy：scene_images 是整段复用的缓存，直接 paste 会把
            # 上一帧的角色留在背景上，形成拖影。
            base = scene_images[current].copy()
            if weight > 0 and upcoming < len(scene_images):
                base = Image.blend(base, scene_images[upcoming], weight)

            if weight > 0 and upcoming < len(prepared):
                first, second = prepared[current], prepared[upcoming]
            else:
                first, second = prepared[current], None

            if pet_frames is not None and (first is not None or second is not None):
                pose = pet_frames[frame_index]
                # 帧源按全局时间取帧：动作连续，不会每屏重头播
                for clip, layer_weight in ((first, 1.0 - weight), (second, weight)):
                    if clip is None or layer_weight <= 0.001:
                        continue
                    layer = clip.frame_at(t_ms)
                    rotated = layer.rotate(
                        -pose.angle, resample=Image.BICUBIC, expand=True
                    )
                    if layer_weight < 0.999:
                        alpha = rotated.getchannel("A").point(
                            lambda value, w=layer_weight: int(value * w)
                        )
                        rotated.putalpha(alpha)
                    base.paste(rotated, (pose.x, pose.y), rotated)

            process.stdin.write(base.tobytes())

        process.stdin.close()
        stderr = process.stderr.read() if process.stderr else b""
        code = process.wait(timeout=600)
    finally:
        if process.poll() is None:
            process.kill()

    if code != 0 or not out_path.is_file():
        tail = stderr.decode("utf-8", "replace")[-800:] if stderr else ""
        raise CompositeError(f"ffmpeg 编码失败：{tail}")

    info = ffmpeg_tool.probe(out_path)
    return LayerResult(
        path=out_path,
        duration_ms=info.get("duration_ms") or total_ms,
        frames=frame_count,
        fps=fps,
        has_audio=bool(info.get("has_audio")),
        bytes=out_path.stat().st_size,
    )
