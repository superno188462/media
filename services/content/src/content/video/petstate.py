"""宠物动作状态机：按权重随机选动作，播完换下一个。

和"每个动作一段循环"的区别：这里产出的是**整条时间轴上每一帧该播哪个动作**。

规则
----

1. 从 ``idle`` 开始，按配置的时长范围停留。
2. 停留结束后按**权重**抽下一个动作；连续重复同一个动作的概率被压低
   （``repeat_penalty``），否则容易连着放两次 eat 显得呆。
3. **被拖走会打断**：拖拽期间的帧全部映射成 ``grab`` 动作。
   拖完回到 ``idle``，重新计时。
4. 某个动作没有素材时退回 ``idle``，不静默失败。

种子决定选动作顺序，同种子可复现。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

#: 拖拽期间使用的动作名。素材缺失时退回 idle。
GRAB_ACTION = "grab"

#: 换位置期间使用的动作名。没有该素材时沿用状态机选中的动作。
WALK_ACTION = "walk"

#: 默认动作集合：权重越大出现越频繁。
DEFAULT_ACTIONS = {
    "idle": {"weight": 4.0, "duration": [3000, 8000]},
    "wave": {"weight": 1.0, "duration": [2000, 4000]},
}

#: 连续两次抽到同一动作时，权重乘这个系数。
REPEAT_PENALTY = 0.35


class ActionError(RuntimeError):
    """动作配置非法。"""


@dataclass
class ActionSpec:
    name: str
    weight: float
    duration_ms: tuple[int, int]

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ActionError(f"动作 {self.name} 的权重必须为正")
        low, high = self.duration_ms
        if low <= 0 or high < low:
            raise ActionError(f"动作 {self.name} 的时长范围非法：{self.duration_ms}")


@dataclass
class ActionPlan:
    """整条时间轴上每一帧的动作名。"""

    actions: list[str]
    fps: int
    timeline: list[tuple[float, str, float]] = field(default_factory=list)

    def action_at_frame(self, index: int) -> str:
        if not self.actions:
            return "idle"
        return self.actions[min(index, len(self.actions) - 1)]

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for name in self.actions:
            counts[name] = counts.get(name, 0) + 1
        total = len(self.actions) or 1
        return {
            "segments": len(self.timeline),
            "actions": {k: round(v / total * 100, 1) for k, v in counts.items()},
        }


def parse_specs(raw: dict | None) -> dict[str, ActionSpec]:
    """把配置里的 actions 解析成 ActionSpec。"""
    if not raw:
        raw = DEFAULT_ACTIONS
    specs: dict[str, ActionSpec] = {}
    for name, value in raw.items():
        if not isinstance(value, dict):
            raise ActionError(f"动作 {name} 的配置必须是对象")
        duration = value.get("duration") or [3000, 6000]
        if len(duration) != 2:
            raise ActionError(f"动作 {name} 的 duration 必须是 [最小, 最大]")
        specs[str(name)] = ActionSpec(
            name=str(name),
            weight=float(value.get("weight", 1.0)),
            duration_ms=(int(duration[0]), int(duration[1])),
        )
    if "idle" not in specs:
        raise ActionError("动作集合必须包含 idle")
    return specs


def plan_actions(
    total_ms: int,
    *,
    fps: int,
    specs: dict[str, ActionSpec],
    drag_flags: list[bool] | None = None,
    move_flags: list[bool] | None = None,
    seed: int = 0,
    available: set[str] | None = None,
) -> ActionPlan:
    """生成逐帧动作名。

    ``available`` 是有素材的动作集合；不在其中的动作会被跳过。
    ``drag_flags`` 与帧一一对应，为 True 的帧强制变成 ``grab``。
    """
    if total_ms <= 0:
        return ActionPlan(actions=[], fps=fps)

    count = max(1, round(total_ms / 1000 * fps))
    frame_ms = 1000.0 / fps
    rng = random.Random(seed)

    usable = {n: s for n, s in specs.items() if available is None or n in available}
    if "idle" not in usable:
        usable["idle"] = specs.get("idle") or ActionSpec("idle", 1.0, (3000, 6000))

    names = list(usable)
    current = "idle"
    remaining_ms = rng.uniform(*usable["idle"].duration_ms)
    elapsed_ms = 0.0

    actions: list[str] = []
    timeline: list[tuple[float, str, float]] = []
    segment_start = 0.0

    for index in range(count):
        now = index * frame_ms

        if elapsed_ms >= remaining_ms:
            # 换动作：按权重抽，压低连续重复
            weights = []
            for name in names:
                weight = usable[name].weight
                if name == current:
                    weight *= REPEAT_PENALTY
                weights.append(weight)
            current = rng.choices(names, weights=weights, k=1)[0]
            remaining_ms = rng.uniform(*usable[current].duration_ms)
            elapsed_ms = 0.0
            timeline.append((segment_start, current, now - segment_start))
            segment_start = now

        actions.append(current)
        elapsed_ms += frame_ms

    timeline.append((segment_start, current, count * frame_ms - segment_start))

    # 换位置时优先播 walk；没有素材就保持状态机选的动作
    if move_flags is not None and (available is None or WALK_ACTION in available):
        if len(move_flags) != count:
            raise ActionError(
                f"移动标记有 {len(move_flags)} 帧，动作需要 {count} 帧"
            )
        for index, moving in enumerate(move_flags):
            if moving:
                actions[index] = WALK_ACTION

    if drag_flags is not None:
        if len(drag_flags) != count:
            raise ActionError(
                f"拖拽标记有 {len(drag_flags)} 帧，动作需要 {count} 帧"
            )
        # 拖拽优先级最高：覆盖 walk
        for index, dragging in enumerate(drag_flags):
            if dragging:
                actions[index] = GRAB_ACTION

    return ActionPlan(actions=actions, fps=fps, timeline=timeline)
