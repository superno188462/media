"""按镜头配音，并把「每场多长」交给音频决定。

这一步是闭环的关键：**`hold_ms` 不再手写，而是由实际语音时长推出来。**
否则会出现「话说一半画面切了」。

做法：

1. 每场取它的台词（``caption`` 或片尾的 ``outro``+``outro_sub``）
2. 合成一段语音，量出真实时长
3. ``hold_ms = 语音时长 + 留白``
4. 若语音比原分镜规定的时长还长，用语音时长（画面不能截断话）

留白用静音补齐，最后拼成一条完整音轨，和静帧序列一起交给 ffmpeg。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import ffmpeg as ffmpeg_tool
from .. import tts as tts_tool
from .scenes import Scene, Storyboard

#: 每句之后留的空白，避免话赶话。
DEFAULT_GAP_MS = 450


@dataclass
class SceneVoice:
    index: int
    text: str
    audio: Path | None
    audio_ms: int
    hold_ms: int


def scene_text(scene: Scene) -> str:
    """这一场要念的话。片尾场把主副标题连起来念。"""
    parts: list[str] = []
    if scene.outro:
        parts.append(scene.outro)
        if scene.outro_sub:
            parts.append(scene.outro_sub)
    elif scene.caption:
        parts.append(scene.caption)
    return "。".join(p.rstrip("。！？…") for p in parts if p).strip()


def plan(
    storyboard: Storyboard,
    out_dir: Path,
    *,
    speaker: str = tts_tool.DEFAULT_SPEAKER,
    speed: float | None = None,
    gap_ms: int = DEFAULT_GAP_MS,
    synthesize_fn=None,
    probe_fn=None,
) -> list[SceneVoice]:
    """逐场合成语音并算出最终时长。

    ``synthesize_fn`` / ``probe_fn`` 可注入，测试时不必联网。
    """
    synth = synthesize_fn or (
        lambda text, path: tts_tool.synthesize_to_file(
            text, path, speaker=speaker, speed=speed
        )
    )
    probe = probe_fn or ffmpeg_tool.probe_duration_ms

    out_dir.mkdir(parents=True, exist_ok=True)
    result: list[SceneVoice] = []

    for index, scene in enumerate(storyboard.scenes, 1):
        text = scene_text(scene)
        if not text:
            # 没台词的镜头保留手写时长
            result.append(
                SceneVoice(index, "", None, 0, max(scene.hold_ms, 1))
            )
            continue

        audio_path = out_dir / f"voice_{index:03d}.mp3"
        synth(text, audio_path)

        if not audio_path.is_file():
            raise tts_tool.TtsError(f"第 {index} 场语音没有生成：{audio_path}")

        audio_ms = probe(audio_path)
        if not audio_ms:
            raise tts_tool.TtsError(f"读不到第 {index} 场语音时长：{audio_path}")

        # 画面不能比语音短，否则话说一半就切走了
        hold = max(audio_ms, scene.hold_ms) + gap_ms
        result.append(SceneVoice(index, text, audio_path, audio_ms, hold))

    return result


def build_track(
    voices: list[SceneVoice],
    out_path: Path,
    *,
    gap_ms: int = DEFAULT_GAP_MS,
    work_dir: Path | None = None,
) -> Path:
    """把各场语音按镜头顺序拼成一条音轨，段间补静音。"""
    work_dir = work_dir or out_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    # 生成两种采样率的静音都麻烦，统一用 24k 单声道
    silence = work_dir / "_silence.mp3"
    ffmpeg_tool.run(
        ["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{gap_ms / 1000:.3f}", str(silence)]
    )

    lines: list[str] = []
    for voice in voices:
        if voice.audio is not None:
            lines.append(f"file '{voice.audio.as_posix()}'")
        lines.append(f"file '{silence.as_posix()}'")

    concat_file = work_dir / "voice_concat.txt"
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = ffmpeg_tool.run(
        ["-f", "concat", "-safe", "0", "-i", str(concat_file),
         "-c:a", "libmp3lame", "-b:a", "128k", str(out_path)]
    )
    if result.returncode != 0 or not out_path.is_file():
        raise tts_tool.TtsError(f"音轨拼接失败：{(result.stderr or '')[-400:]}")
    return out_path
