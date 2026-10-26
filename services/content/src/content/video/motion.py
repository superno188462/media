"""运镜与转场的 ffmpeg 滤镜图构造。

单独成模块的原因：滤镜字符串很长且容易写错，**纯函数便于离线测试**，
不需要真的调用 ffmpeg 就能断言「总时长是否守恒」「片段是否都接上了」。

核心不变量（VP-RULE-01）：

    成片总时长 == Σ 各屏 hold_ms

实现方式：转场靠「片段加长 + 相邻重叠」实现。

    第 i 段长度 = hold_i + d      （i < n−1，末段不加）
    总长 = Σ(hold) + (n−1)·d − (n−1)·d = Σ(hold)

历史上的坑：concat 分离器会丢掉最后一帧的 duration，导致 26.9 秒的片子
只有 23.0 秒画面；所以这里用 zoompan 显式指定帧数，不依赖 duration 语义。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 运镜种类。
MOTION_NONE = "none"
MOTION_ZOOM_IN = "zoom_in"
MOTION_ZOOM_OUT = "zoom_out"
MOTION_PAN_LEFT = "pan_left"
MOTION_PAN_RIGHT = "pan_right"

MOTIONS = {MOTION_NONE, MOTION_ZOOM_IN, MOTION_ZOOM_OUT, MOTION_PAN_LEFT, MOTION_PAN_RIGHT}

#: 默认转场时长（毫秒）。
DEFAULT_TRANSITION_MS = 300

#: 缩放幅度。上限受**安全边距**约束：放大 z 会在左右各裁掉
#: (z-1)/2 的宽度。版式把角标放在距左 48px，若裁掉超过 48px 就会切字，
#: 所以 1920 宽最多放大到 1.05；这里取 4% 留余量。
ZOOM_RANGE = 0.04

#: 平移时的固定放大倍数；平移范围 = 宽度 × (1 − 1/PAN_ZOOM)。
PAN_ZOOM = 1.04

#: 预放大倍数：先放大再 zoompan，减少放大时的模糊。
PRESCALE = 1.2


class MotionError(RuntimeError):
    """滤镜图参数非法。"""


@dataclass(frozen=True)
class Segment:
    """一个已规划好的片段。"""

    index: int
    hold_ms: int
    #: 实际片段长度（含与下一段的重叠部分）。
    length_ms: int
    motion: str

    @property
    def frames(self) -> int:
        raise NotImplementedError


def _zoom_expr(motion: str, frames: int) -> tuple[str, str, str]:
    """返回 zoompan 的 z/x/y 表达式。"""
    span = max(frames - 1, 1)
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"

    if motion == MOTION_ZOOM_IN:
        step = ZOOM_RANGE / span
        return f"min(1+{step:.6f}*on,{1 + ZOOM_RANGE:.3f})", center_x, center_y

    if motion == MOTION_ZOOM_OUT:
        step = ZOOM_RANGE / span
        return f"max({1 + ZOOM_RANGE:.3f}-{step:.6f}*on,1.000)", center_x, center_y

    if motion == MOTION_PAN_LEFT:
        # 从右向左移动（画面内容左移）
        return (
            f"{PAN_ZOOM}",
            f"(iw-iw/zoom)*(1-on/{span})",
            center_y,
        )

    if motion == MOTION_PAN_RIGHT:
        return (
            f"{PAN_ZOOM}",
            f"(iw-iw/zoom)*(on/{span})",
            center_y,
        )

    # none（及未知值）：完全静止，但仍输出等量帧，保持时长一致
    return "1", center_x, center_y


def plan_segments(
    holds_ms: list[int],
    motions: list[str],
    transition_ms: int,
) -> list[Segment]:
    """规划片段长度：除末段外，每段补上转场重叠时长。"""
    if len(holds_ms) != len(motions):
        raise MotionError("时长与运镜数量不一致")
    if not holds_ms:
        raise MotionError("没有片段")
    if any(h <= 0 for h in holds_ms):
        raise MotionError("每条时长必须为正")

    count = len(holds_ms)
    # 转场不能长于最短的一场：否则这一屏整段都在淡化，等于没有内容。
    if count > 1 and transition_ms > min(holds_ms):
        raise MotionError(
            f"转场 {transition_ms}ms 超过最短场景 {min(holds_ms)}ms，画面会被淡化吃掉"
        )
    overlap = transition_ms if count > 1 else 0
    segments: list[Segment] = []
    for index, (hold, motion) in enumerate(zip(holds_ms, motions)):
        if motion not in MOTIONS:
            raise MotionError(f"未知运镜：{motion}")
        extra = overlap if index < count - 1 else 0
        segments.append(
            Segment(index=index, hold_ms=hold, length_ms=hold + extra, motion=motion)
        )
    return segments


def total_ms(holds_ms: list[int]) -> int:
    return sum(holds_ms)


def build_filter(
    segments: list[Segment],
    width: int,
    height: int,
    fps: int,
    transition_ms: int,
) -> tuple[str, str]:
    """构造 filter_complex 与输出标签。

    返回 ``(filter_complex, out_label)``。
    """
    if not segments:
        raise MotionError("没有片段")

    parts: list[str] = []
    for seg in segments:
        frames = max(1, round(seg.length_ms / 1000 * fps))
        z, x, y = _zoom_expr(seg.motion, frames)
        parts.append(
            f"[{seg.index}:v]scale=trunc(iw*{PRESCALE}):trunc(ih*{PRESCALE}),"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
            f"setsar=1,format=yuv420p[v{seg.index}]"
        )

    if len(segments) == 1:
        return ";".join(parts), "v0"

    if transition_ms <= 0:
        # 无转场：直接拼接
        inputs = "".join(f"[v{seg.index}]" for seg in segments)
        parts.append(f"{inputs}concat=n={len(segments)}:v=1:a=0[out]")
        return ";".join(parts), "out"

    duration = transition_ms / 1000
    accumulated = segments[0].length_ms / 1000
    current = "v0"
    for seg in segments[1:]:
        offset = accumulated - duration
        if offset < 0:
            raise MotionError(
                f"转场 {transition_ms}ms 超过片段长度，无法重叠（offset={offset:.3f}）"
            )
        label = f"x{seg.index}"
        parts.append(
            f"[{current}][v{seg.index}]xfade=transition=fade:"
            f"duration={duration:.3f}:offset={offset:.3f}[{label}]"
        )
        accumulated = accumulated + seg.length_ms / 1000 - duration
        current = label

    return ";".join(parts), current
