"""把静帧序列 + 音轨合成 mp4。

用 ffmpeg 的 concat 分离器：每张图配一个 ``duration``，
比给每张图单独跑一次 ``-loop 1 -t`` 快得多，也更省内存。

帧率固定 30，编码 H.264 + yuv420p（B站接受度高）。
因为画面基本是静帧，``-tune stillimage`` 能让码率更省。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import ffmpeg as ffmpeg_tool

DEFAULT_FPS = 30
DEFAULT_CRF = 20


@dataclass
class ComposeResult:
    path: Path
    duration_ms: int
    frames: int
    fps: int
    has_audio: bool
    bytes: int


class ComposeError(RuntimeError):
    """合成失败。"""


def _write_concat(frames: list[Path], holds_ms: list[int], target: Path,
                  fps: int = DEFAULT_FPS) -> None:
    """写 concat 清单：每帧一行 ``file`` + 一行 ``duration``。

    **末尾必须再补一次最后一帧，时长给单帧（1/fps）。**
    concat 分离器会丢掉最后一个 ``duration``：只写一遍时，
    5 场共 26.9 秒的片子只有 23.0 秒画面，音轨却仍是 26.9 秒，
    最后几秒没有画面。补一帧后实测精确得到 26.9 秒 / 807 帧。

    只有**补的那一帧**才给单帧时长；若给完整时长，会多出一整段。
    """
    if len(frames) != len(holds_ms):
        raise ComposeError("帧数与时长数不一致")
    lines: list[str] = []
    for frame, hold in zip(frames, holds_ms):
        lines.append(f"file '{frame.as_posix()}'")
        lines.append(f"duration {hold / 1000:.3f}")
    # 补一帧，吃掉被丢弃的最后一段 duration
    lines.append(f"file '{frames[-1].as_posix()}'")
    lines.append(f"duration {1 / fps:.4f}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compose(
    frames: list[Path],
    holds_ms: list[int],
    out_path: Path,
    *,
    audio: Path | None = None,
    fps: int = DEFAULT_FPS,
    crf: int = DEFAULT_CRF,
    work_dir: Path | None = None,
) -> ComposeResult:
    """把帧序列（带各自时长）合成 mp4，可选混入音轨。"""
    if not frames:
        raise ComposeError("没有可合成的帧")

    for frame in frames:
        if not frame.is_file():
            raise ComposeError(f"帧文件不存在：{frame}")

    work_dir = work_dir or out_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)
    concat_file = work_dir / "concat.txt"
    _write_concat(frames, holds_ms, concat_file, fps)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    args: list[str] = [
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
    ]
    if audio is not None:
        if not audio.is_file():
            raise ComposeError(f"音轨不存在：{audio}")
        args += ["-i", str(audio)]

    total_seconds = sum(holds_ms) / 1000

    args += [
        # concat 出来的时长是可变的；用 fps 滤镜转成固定帧率，
        # 不要用 -vsync（已弃用）或 -r（与 concat 的 VFR 冲突）。
        "-vf", f"fps={fps}",
        # 单帧或末帧时 concat 的 duration 会被忽略，
        # 用 -t 强制总时长，结果才可预测。
        "-t", f"{total_seconds:.3f}",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(crf),
        "-tune", "stillimage",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]
    if audio is not None:
        # 不要 -shortest：单帧视频只有 33ms，它会把音轨一起截断。
        # 总时长由上面的 -t 控制，音轨比画面短时自然留白。
        args += ["-c:a", "aac", "-b:a", "128k"]
    args.append(str(out_path))

    result = ffmpeg_tool.run(args, timeout=900)
    if result.returncode != 0 or not out_path.is_file():
        tail = (result.stderr or "")[-600:]
        raise ComposeError(f"ffmpeg 合成失败：{tail}")

    probe = ffmpeg_tool.probe(out_path)
    return ComposeResult(
        path=out_path,
        duration_ms=probe.get("duration_ms") or sum(holds_ms),
        frames=len(frames),
        fps=fps,
        has_audio=bool(probe.get("has_audio")),
        bytes=out_path.stat().st_size,
    )


def extract_frame(video: Path, at_ms: int, out_path: Path) -> Path:
    """从成片里取一帧，用于审核卡片的关键帧预览。"""
    seconds = at_ms / 1000
    args = [
        "-ss", f"{seconds:.3f}",
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", "2",
        str(out_path),
    ]
    result = ffmpeg_tool.run(args, timeout=120)
    if result.returncode != 0 or not out_path.is_file():
        raise ComposeError(f"抽帧失败：{(result.stderr or '')[-400:]}")
    return out_path


def extract_keyframes(video: Path, count: int, out_dir: Path) -> list[Path]:
    """均匀抽若干帧，供审核时预览画面（飞书卡片不能播放视频）。"""
    info = ffmpeg_tool.probe(video)
    duration = info.get("duration_ms")
    if not duration:
        raise ComposeError("读不到视频时长，无法均匀抽帧")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index in range(count):
        at_ms = int(duration * (index + 0.5) / count)
        target = out_dir / f"keyframe_{index + 1:02d}.jpg"
        paths.append(extract_frame(video, at_ms, target))
    return paths
