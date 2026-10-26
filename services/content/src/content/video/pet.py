"""角色的"宠物式"运动：随机游走 + 踩到 UI 被拖走。

为什么单独成模块：这部分是**纯逻辑**（不碰像素），可以用种子复现、
可以单测，不需要跑 ffmpeg。

行为模型
--------

1. **游走**：角色在活动区里随机选点，缓慢移过去；到了再选下一个点。
2. **允许越界**：活动区覆盖卡片和字幕区——**故意让它能飘到 UI 上面**。
3. **被拖走**：一旦角色的矩形和"受保护区"重叠，立刻进入"拖拽"状态，
   以快得多的速度滑到最近的合法点，之后有短暂冷却（不会一直抽搐）。
4. **叠加微动**：浮动 + 轻微倾斜，让静止时也不像贴图。

种子决定：选点、速度、是否越界、什么时候被拖。同一个种子出同一段动画。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def overlaps(self, other: "Rect") -> bool:
        return self.overlap_area(other) > 0

    def overlap_area(self, other: "Rect") -> int:
        width = min(self.right, other.right) - max(self.x, other.x)
        height = min(self.bottom, other.bottom) - max(self.y, other.y)
        return max(0, width) * max(0, height)

    def clamp_to(self, bounds: "Rect") -> "Rect":
        x = min(max(self.x, bounds.x), bounds.right - self.w)
        y = min(max(self.y, bounds.y), bounds.bottom - self.h)
        return Rect(x, y, self.w, self.h)

    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2


@dataclass
class PetFrame:
    """一帧里角色的位置与姿态。"""

    x: int
    y: int
    angle: float
    dragging: bool
    #: 是否处于「换位置」过程；False 表示停在原地做动作
    moving: bool = False

    def box(self, width: int, height: int) -> Rect:
        return Rect(self.x, self.y, width, height)


#: 游走速度范围（像素/秒）。慢到像树懒。
WANDER_SPEED = (55.0, 130.0)

#: 被拖走时的速度范围。明显快于游走，才有"被拽"的观感。
#: 但不能太快：900–1500 时整段拖拽只有 0.1–0.3 秒，
#: 手伸下来根本看不清。降到 320–520 后约 1–2 秒，动作能被眼睛跟上。
DRAG_SPEED = (320.0, 520.0)

#: 停留时长。风格 C：大部分时间待在原地做动作，只偶尔换位置。
#: 配合下面的移动速度，停留约占 70%，移动约占 30%。
STAY_MS = (3800, 9500)

#: 两个目标点之间的间隔（移动模式下重新选点的兜底）。
TARGET_INTERVAL_MS = (1600, 3400)

#: 被拖之后的冷却，避免贴着边缘反复抽搐。
DRAG_COOLDOWN_MS = (1400, 2600)

#: 只有**压上去的面积**超过角色面积的这个比例才触发拖拽。
#: 轻微擦边不拖——否则会被拖得过于频繁，看着像抽搐。
DRAG_TRIGGER_RATIO = 0.18

#: 每次换位置时，"故意走到受保护区上"的概率。
#: 没有这个，角色总待在安全区，被抓就永远不发生。
MISCHIEF_CHANCE = 0.35

#: 浮动与倾斜的幅度与周期。
BOB_AMPLITUDE = 10.0
BOB_PERIOD_MS = 3600.0
TILT_AMPLITUDE = 1.2
TILT_PERIOD_MS = 5200.0


class PetPlanner:
    """按种子生成整条角色轨迹。"""

    def __init__(
        self,
        *,
        seed: int,
        fps: int,
        stage: Rect,
        pet_size: tuple[int, int],
        wander: Rect,
        protected: list[Rect],
        trigger_ratio: float = DRAG_TRIGGER_RATIO,
        mischief_chance: float = MISCHIEF_CHANCE,
    ) -> None:
        self.fps = fps
        self.trigger_ratio = trigger_ratio
        self.mischief_chance = max(0.0, min(1.0, mischief_chance))
        self.stage = stage
        self.pet_w, self.pet_h = pet_size
        self.wander = wander
        self.protected = list(protected)
        self.rng = random.Random(seed)
        self.seed = seed

    # -------------------------------------------------------------- 工具

    def _random_point(self) -> tuple[float, float]:
        """在活动区里随机取一个左上角坐标。"""
        max_x = max(self.wander.x, self.wander.right - self.pet_w)
        max_y = max(self.wander.y, self.wander.bottom - self.pet_h)
        return (
            self.rng.uniform(self.wander.x, max_x),
            self.rng.uniform(self.wander.y, max_y),
        )

    def _mischief_point(self) -> tuple[float, float] | None:
        """故意选一个压在受保护区上的目标点。"""
        zones = [z for z in self.protected if z.w > 0 and z.h > 0]
        if not zones:
            return None
        zone = self.rng.choice(zones)
        # 目标点落在禁区内部，保证角色会压上去
        x = self.rng.uniform(zone.x, max(zone.x, zone.right - self.pet_w * 0.6))
        y = self.rng.uniform(zone.y, max(zone.y, zone.bottom - self.pet_h * 0.6))
        max_x = max(self.wander.x, self.wander.right - self.pet_w)
        max_y = max(self.wander.y, self.wander.bottom - self.pet_h)
        return (min(max(x, self.wander.x), max_x), min(max(y, self.wander.y), max_y))

    def _pick_target(self) -> tuple[float, float]:
        """换位置时的目标点：有概率故意去惹 UI。"""
        if self.rng.random() < self.mischief_chance:
            point = self._mischief_point()
            if point is not None:
                return point
        return self._random_point()

    def _violates(self, box: Rect) -> bool:
        """压上去的面积是否超过阈值（不是一碰就算）。"""
        pet_area = float(box.w * box.h) or 1.0
        for zone in self.protected:
            if box.overlap_area(zone) / pet_area >= self.trigger_ratio:
                return True
        return False

    def _escape_point(self, box: Rect) -> tuple[float, float]:
        """选一个**尽量远**的合法落点——扔出去才有距离感。

        不用"最近点"：角色只是轻微越界时，最近点就在旁边，
        拖拽只持续 0.1 秒，手伸下来根本看不清。
        这里在所有合法落点里挑最靠右的，形成"被拎起来扔到一边"。
        """
        best: tuple[float, float] | None = None
        best_x = float("-inf")
        cx, cy = box.center()

        max_x = max(self.wander.x, self.wander.right - self.pet_w)
        max_y = max(self.wander.y, self.wander.bottom - self.pet_h)
        steps_x = 12
        steps_y = 10
        for i in range(steps_x + 1):
            for j in range(steps_y + 1):
                x = self.wander.x + (max_x - self.wander.x) * i / steps_x
                y = self.wander.y + (max_y - self.wander.y) * j / steps_y
                candidate = Rect(int(x), int(y), self.pet_w, self.pet_h)
                if self._violates(candidate):
                    continue
                # 优先最右；同样靠右时取离当前位置近的
                score = (x, -math.hypot(x + self.pet_w / 2 - cx, y + self.pet_h / 2 - cy))
                if score[0] > best_x:
                    best_x = score[0]
                    best = (x, y)

        return best or (max_x, self.wander.y)

    # -------------------------------------------------------------- 主循环

    def frames(self, total_ms: int) -> list[PetFrame]:
        """生成整段轨迹。``seed`` 相同则结果相同。"""
        if total_ms <= 0:
            return []

        count = max(1, round(total_ms / 1000 * self.fps))
        frame_ms = 1000.0 / self.fps

        x, y = self._random_point()
        target_x, target_y = x, y
        # 风格 C：先停一会儿，再换位置
        moving = False
        mode_deadline = self.rng.uniform(*STAY_MS)
        speed = self.rng.uniform(*WANDER_SPEED)

        dragging = False
        drag_speed = 0.0
        cooldown_until = 0.0
        out: list[PetFrame] = []

        for index in range(count):
            now = index * frame_ms

            if not dragging:
                if not moving and now >= mode_deadline:
                    # 开始换位置
                    moving = True
                    target_x, target_y = self._pick_target()
                    speed = self.rng.uniform(*WANDER_SPEED)

            step = (drag_speed if dragging else speed) * frame_ms / 1000.0

            dx = target_x - x
            dy = target_y - y
            distance = math.hypot(dx, dy)

            if dragging or moving:
                if distance <= step or distance == 0:
                    x, y = target_x, target_y
                    if dragging:
                        # 拖到位了：结束拖拽，进入冷却，然后停一会儿
                        dragging = False
                        cooldown_until = now + self.rng.uniform(*DRAG_COOLDOWN_MS)
                        moving = False
                        mode_deadline = now + self.rng.uniform(*STAY_MS)
                        target_x, target_y = x, y
                    elif moving:
                        # 到位了：进入停留
                        moving = False
                        mode_deadline = now + self.rng.uniform(*STAY_MS)
                else:
                    x += dx / distance * step
                    y += dy / distance * step

            box = Rect(int(x), int(y), self.pet_w, self.pet_h)

            # 踩到受保护区且不在冷却 → 开始被拖走
            if not dragging and now >= cooldown_until and self._violates(box):
                dragging = True
                moving = False
                drag_speed = self.rng.uniform(*DRAG_SPEED)
                target_x, target_y = self._escape_point(box)

            # 叠加浮动与倾斜
            bob = BOB_AMPLITUDE * math.sin(2 * math.pi * now / BOB_PERIOD_MS)
            angle = TILT_AMPLITUDE * math.sin(2 * math.pi * now / TILT_PERIOD_MS)

            out.append(
                PetFrame(
                    x=int(x),
                    y=int(y + bob),
                    angle=angle,
                    dragging=dragging,
                    moving=moving,
                )
            )

        return out

    def summary(self, frames: list[PetFrame]) -> dict:
        """统计：这一版到底有没有真的拖动过。"""
        drag_frames = sum(1 for f in frames if f.dragging)
        events = 0
        for previous, current in zip(frames, frames[1:]):
            if current.dragging and not previous.dragging:
                events += 1
        xs = [f.x for f in frames] or [0]
        ys = [f.y for f in frames] or [0]
        moving_frames = sum(1 for f in frames if f.moving)
        return {
            "seed": self.seed,
            "frames": len(frames),
            "moving_pct": round(moving_frames / len(frames) * 100, 1) if frames else 0.0,
            "drag_events": events,
            "drag_frame_ratio_pct": round(drag_frames / len(frames) * 100, 1) if frames else 0.0,
            "x_range": [min(xs), max(xs)],
            "y_range": [min(ys), max(ys)],
        }
