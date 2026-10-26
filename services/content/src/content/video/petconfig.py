"""宠物配置：一个 JSON 决定角色怎么动。

放在配置文件而不是代码里，是因为后续要做**前台配置页**——
页面最终改的就是这个结构。代码只负责校验和应用。

示例见 ``services/content/examples/pet_config.json``。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import pet as pet_mod
from . import petclip as clip_mod


class ConfigError(RuntimeError):
    """配置非法。"""


@dataclass
class PetConfig:
    """宠物行为与素材的完整配置。"""

    enabled: bool = True
    #: 帧源类型：flipbook（当前）/ static / video（预留）
    source: str = clip_mod.SOURCE_FLIPBOOK
    #: 行为状态 -> 帧目录（相对配置文件所在目录或项目根）
    clips: dict[str, str] = field(default_factory=dict)
    #: 播放帧率
    clip_fps: int = clip_mod.DEFAULT_CLIP_FPS
    #: 相邻帧交叉淡化比例
    crossfade: float = clip_mod.DEFAULT_CROSSFADE
    #: 角色高度（像素）
    size: int = 420
    #: 行为种子；0 表示每条视频随机
    seed: int = 0
    #: 压上受保护区的面积比例阈值
    trigger_ratio: float = pet_mod.DRAG_TRIGGER_RATIO
    #: 活动区，归一化 [x, y, w, h]
    wander_area: tuple[float, float, float, float] = (0.36, 0.09, 0.58, 0.89)
    #: 受保护区，像素 [[x, y, w, h], ...]
    protected_zones: list[tuple[int, int, int, int]] = field(
        default_factory=lambda: [(300, 150, 1320, 720), (300, 880, 1320, 160)]
    )

    def __post_init__(self) -> None:
        if self.source not in clip_mod.SOURCES:
            raise ConfigError(f"未知帧源：{self.source}（可选 {sorted(clip_mod.SOURCES)}）")
        if self.size < 80 or self.size > 1200:
            raise ConfigError(f"角色高度不合理：{self.size}")
        if not 0.0 <= self.crossfade < 1.0:
            raise ConfigError(f"crossfade 必须在 [0,1)：{self.crossfade}")
        if not 0.0 < self.trigger_ratio <= 1.0:
            raise ConfigError(f"trigger_ratio 必须在 (0,1]：{self.trigger_ratio}")
        if len(self.wander_area) != 4:
            raise ConfigError("wander_area 必须是 4 个归一化值")
        if not self.enabled:
            return
        if self.source == clip_mod.SOURCE_FLIPBOOK and "idle" not in self.clips:
            raise ConfigError("flipbook 模式必须配置 idle 动作")

    # -------------------------------------------------------------- 几何

    def wander_rect(self, width: int, height: int) -> pet_mod.Rect:
        x, y, w, h = self.wander_area
        return pet_mod.Rect(
            int(width * x), int(height * y), int(width * w), int(height * h)
        )

    def protected_rects(self) -> list[pet_mod.Rect]:
        return [pet_mod.Rect(*zone) for zone in self.protected_zones]

    # -------------------------------------------------------------- 加载

    @classmethod
    def from_dict(cls, data: dict, base_dir: Path | None = None) -> "PetConfig":
        raw = data.get("pet", data)
        if not isinstance(raw, dict):
            raise ConfigError("配置必须是对象")

        clips = raw.get("clips") or {}
        if not isinstance(clips, dict):
            raise ConfigError("clips 必须是「动作名 -> 路径」的对象")

        resolved: dict[str, str] = {}
        for name, value in clips.items():
            path = Path(value)
            if not path.is_absolute() and base_dir is not None:
                path = (base_dir / path).resolve()
            resolved[str(name)] = str(path)

        wander = raw.get("wander_area", (0.36, 0.09, 0.58, 0.89))
        zones = raw.get("protected_zones") or [(300, 150, 1320, 720), (300, 880, 1320, 160)]

        return cls(
            enabled=bool(raw.get("enabled", True)),
            source=str(raw.get("source", clip_mod.SOURCE_FLIPBOOK)),
            clips=resolved,
            clip_fps=int(raw.get("clip_fps", clip_mod.DEFAULT_CLIP_FPS)),
            crossfade=float(raw.get("crossfade", clip_mod.DEFAULT_CROSSFADE)),
            size=int(raw.get("size", 420)),
            seed=int(raw.get("seed", 0)),
            trigger_ratio=float(raw.get("trigger_ratio", pet_mod.DRAG_TRIGGER_RATIO)),
            wander_area=tuple(float(v) for v in wander),
            protected_zones=[tuple(int(v) for v in zone) for zone in zones],
        )

    @classmethod
    def load(cls, path: Path) -> "PetConfig":
        path = Path(path)
        if not path.is_file():
            raise ConfigError(f"配置文件不存在：{path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"配置不是合法 JSON：{exc}") from exc
        return cls.from_dict(data, base_dir=path.parent)

    # -------------------------------------------------------------- 帧源

    def build_clip(self, action: str = "idle"):
        """构造某个动作的帧源。缺该动作时退回 idle。"""
        if action not in self.clips:
            action = "idle"
        target = self.clips.get(action)
        if not target:
            raise ConfigError(f"没有配置任何动作：{sorted(self.clips)}")

        path = Path(target)
        if self.source == clip_mod.SOURCE_FLIPBOOK:
            return clip_mod.build_clip(
                self.source, directory=path,
                fps=self.clip_fps, crossfade=self.crossfade, height=self.size,
            )
        return clip_mod.build_clip(
            self.source, path=path, fps=self.clip_fps,
            crossfade=self.crossfade, height=self.size,
        )

    def to_dict(self) -> dict:
        """回写成配置结构，供前台页面读取当前值。"""
        return {
            "enabled": self.enabled,
            "source": self.source,
            "clips": dict(self.clips),
            "clip_fps": self.clip_fps,
            "crossfade": self.crossfade,
            "size": self.size,
            "seed": self.seed,
            "trigger_ratio": self.trigger_ratio,
            "wander_area": list(self.wander_area),
            "protected_zones": [list(z) for z in self.protected_zones],
        }
