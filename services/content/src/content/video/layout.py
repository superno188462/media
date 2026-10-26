"""版式与运镜的自动选择、卡片逐条出现的展开。

三件事分开做，都能单测：

1. ``default_motion(layout)`` —— 没写 motion 时按版式给一个默认
2. ``expand_card_reveal(board)`` —— 把 [1,2,3] 的一屏拆成三个子屏
3. ``audit(board)`` —— 反单调检查（VP-RULE-05），只提示不阻断
"""

from __future__ import annotations

from dataclasses import replace

from . import motion as M
from .scenes import (
    LAYOUT_CARD,
    LAYOUT_CENTER_CARD,
    LAYOUT_CLOSEUP,
    LAYOUT_HEADLINE,
    Card,
    Scene,
    Storyboard,
)

#: 版式到默认运镜的映射（VP-DATA-03）。
DEFAULT_MOTION = {
    LAYOUT_CARD: M.MOTION_ZOOM_IN,
    LAYOUT_HEADLINE: M.MOTION_ZOOM_OUT,
    LAYOUT_CLOSEUP: M.MOTION_PAN_RIGHT,
    LAYOUT_CENTER_CARD: M.MOTION_ZOOM_IN,
}

#: 反单调检查的阈值（VP-RULE-05）。
MAX_SAME_LAYOUT_RUN = 3
MIN_LAYOUTS = 2
MIN_POSES_LONG_VIDEO = 2
LONG_VIDEO_MS = 20_000


def default_motion(layout: str) -> str:
    return DEFAULT_MOTION.get(layout, M.MOTION_ZOOM_IN)


def resolve_motion(scene: Scene) -> str:
    return scene.motion or default_motion(scene.layout)


def resolve_transition(scene: Scene) -> str:
    return scene.transition or "fade"


def _visible_card(card: Card, visible: int) -> Card:
    """保留整卡不动；隐藏交给模板的 ``visible_lines``。

    不裁剪行数的原因：裁掉后卡片会变矮，逐条出现时整块卡片在跳。
    保留占位 + 透明，高度才稳定。
    """
    return card


def expand_card_reveal(board: Storyboard) -> Storyboard:
    """把带 ``card_reveal`` 的屏拆成若干子屏，总时长不变。

    例如 hold=6000、reveal=[1,2,3] → 三个子屏各 2000ms，
    分别显示 1、2、3 行。余数补给最后一段，保证 Σ 不变。
    """
    expanded: list[Scene] = []
    for scene in board.scenes:
        reveal = scene.card_reveal
        if not reveal or scene.card is None:
            expanded.append(scene)
            continue

        count = len(reveal)
        base = scene.hold_ms // count
        remainder = scene.hold_ms - base * count

        for position, visible in enumerate(reveal):
            hold = base + (remainder if position == count - 1 else 0)
            expanded.append(
                replace(
                    scene,
                    hold_ms=max(hold, 1),
                    card=_visible_card(scene.card, visible),
                    # 只有最后一次展开保留 reveal，避免二次展开
                    card_reveal=None,
                    visible_lines=visible,
                )
            )

    return Storyboard(
        scenes=expanded,
        width=board.width,
        height=board.height,
        assets=board.assets,
        brand=board.brand,
        disclaimer=board.disclaimer,
        accent=board.accent,
    )


def audit(board: Storyboard) -> list[str]:
    """反单调检查。返回提示列表，不阻断渲染。"""
    notes: list[str] = []
    if not board.scenes:
        return notes

    layouts = [s.layout for s in board.scenes]
    distinct = set(layouts)
    if len(distinct) < MIN_LAYOUTS:
        notes.append(
            f"整片只用了 {len(distinct)} 种版式（建议 ≥{MIN_LAYOUTS}），观感容易单调"
        )

    run = 1
    for previous, current in zip(layouts, layouts[1:]):
        run = run + 1 if current == previous else 1
        if run == MAX_SAME_LAYOUT_RUN + 1:
            notes.append(
                f"连续 {run} 屏都是「{current}」版式（建议 ≤{MAX_SAME_LAYOUT_RUN}）"
            )
            break

    total = sum(s.hold_ms for s in board.scenes)
    poses = {s.pose for s in board.scenes if s.pose}
    if total >= LONG_VIDEO_MS and len(poses) < MIN_POSES_LONG_VIDEO:
        notes.append(
            f"片长 {total // 1000} 秒但只用 {len(poses)} 个姿势（建议 ≥{MIN_POSES_LONG_VIDEO}）"
        )

    return notes
