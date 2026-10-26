"""分镜数据模型。

一期视频 = 一串 ``Scene``，每段有固定的时长、字幕、可选卡片、立绘姿势。
渲染层据此逐场出图，合成层按时长拼接。

设计约束（来自鲸鱼娘 Day 0 的实机观察）：

- **版式固定**：角标、字幕条、立绘位置在整片里不变，只有卡片和字幕变。
- **卡片是状态机**：同一张卡片会「第 1 项高亮 → 变灰打勾 → 第 2 项高亮」，
  所以每场单独给出卡片状态，而不是靠动画。
- **立绘用预设名**，不写路径；由 ``assets`` 映射到实际文件，换素材只改映射。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: 卡片某一行的状态。视觉表现由 HTML 模板决定。
LINE_NORMAL = "normal"
LINE_ACTIVE = "active"
LINE_DONE = "done"
LINE_PENDING = "pending"

LINE_STATES = {LINE_NORMAL, LINE_ACTIVE, LINE_DONE, LINE_PENDING}

#: 版式（VP-DATA-02）。
LAYOUT_CARD = "card"
LAYOUT_HEADLINE = "headline"
LAYOUT_CLOSEUP = "closeup"
LAYOUT_CENTER_CARD = "center_card"

LAYOUTS = {LAYOUT_CARD, LAYOUT_HEADLINE, LAYOUT_CLOSEUP, LAYOUT_CENTER_CARD}


@dataclass
class CardLine:
    text: str
    sub: str = ""
    state: str = LINE_NORMAL
    index: str = ""  # 序号或图标，如 "1" "2"

    def __post_init__(self) -> None:
        if self.state not in LINE_STATES:
            raise ValueError(f"未知的行状态：{self.state}")


@dataclass
class Card:
    title: str = ""
    icon: str = ""
    lines: list[CardLine] = field(default_factory=list)
    footer: str = ""


@dataclass
class Scene:
    """一个镜头。

    ``hold_ms`` 是这个镜头在视频里占的时长。**可以给 0**，
    表示「由配音决定」——视频流程会按实际语音长度回填，
    避免话说一半画面就切走。
    """

    hold_ms: int
    caption: str = ""
    card: Card | None = None
    pose: str = ""
    #: 左侧大字，如 {"title": "来自深海的", "main": "鲸鱼娘", "sub": "DeepSeek"}
    title_block: dict | None = None
    #: 全屏字幕（片尾用），覆盖默认字幕条
    outro: str = ""
    outro_sub: str = ""
    #: 额外的角标文字，如 "Day 0"
    badge: str = ""
    #: 版式，见 VP-DATA-02：card / headline / closeup / center_card
    layout: str = LAYOUT_CARD
    #: 卡片逐条出现的行数进度，如 [1, 2, 3]；None 表示整卡一次出现
    card_reveal: list[int] | None = None
    #: 运镜，见 VP-DATA-03；None 时按版式自动选
    motion: str | None = None
    #: 转场，fade / none；None 用默认淡入淡出
    transition: str | None = None
    #: 卡片只显示前 N 行（其余保持占位、透明）；None 表示全部可见。
    #: 由 card_reveal 展开时自动填入，不要让作者手写。
    visible_lines: int | None = None

    def __post_init__(self) -> None:
        if self.hold_ms < 0:
            raise ValueError("hold_ms 不能为负；给 0 表示由配音决定")
        if self.layout not in LAYOUTS:
            raise ValueError(f"未知版式：{self.layout}")
        if self.card_reveal is not None:
            if not self.card_reveal:
                raise ValueError("card_reveal 不能是空数组；要整卡出现请留 null")
            if any(v <= 0 for v in self.card_reveal):
                raise ValueError("card_reveal 的每一项都必须为正")
            if self.card is None:
                raise ValueError("card_reveal 需要同时提供 card")

    @property
    def has_dialogue(self) -> bool:
        return bool(self.caption or self.outro)


@dataclass
class Storyboard:
    """整片分镜。"""

    scenes: list[Scene]
    width: int = 1920
    height: int = 1080
    #: 立绘预设名 -> 图片路径
    assets: dict[str, str] = field(default_factory=dict)
    #: 顶部左侧角标文案
    brand: str = "内卷树懒运营日志"
    #: 右上角声明
    disclaimer: str = "本视频含 AI 生成内容"
    #: 主角名，用于取景框
    accent: str = "#2E6BD6"

    @property
    def total_ms(self) -> int:
        return sum(scene.hold_ms for scene in self.scenes)

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "assets": self.assets,
            "brand": self.brand,
            "disclaimer": self.disclaimer,
            "accent": self.accent,
            "scenes": [
                {
                    **asdict(scene),
                    "card": asdict(scene.card) if scene.card else None,
                }
                for scene in self.scenes
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Storyboard":
        scenes: list[Scene] = []
        for raw in data.get("scenes") or []:
            card_raw = raw.get("card")
            card = None
            if card_raw:
                lines = [CardLine(**line) for line in card_raw.get("lines") or []]
                card = Card(
                    title=card_raw.get("title", ""),
                    icon=card_raw.get("icon", ""),
                    lines=lines,
                    footer=card_raw.get("footer", ""),
                )
            scenes.append(
                Scene(
                    hold_ms=int(raw["hold_ms"]),
                    caption=raw.get("caption", ""),
                    card=card,
                    pose=raw.get("pose", ""),
                    title_block=raw.get("title_block"),
                    outro=raw.get("outro", ""),
                    outro_sub=raw.get("outro_sub", ""),
                    badge=raw.get("badge", ""),
                    layout=raw.get("layout", LAYOUT_CARD),
                    card_reveal=raw.get("card_reveal"),
                    motion=raw.get("motion"),
                    transition=raw.get("transition"),
                    visible_lines=raw.get("visible_lines"),
                )
            )
        return cls(
            scenes=scenes,
            width=int(data.get("width", 1920)),
            height=int(data.get("height", 1080)),
            assets=dict(data.get("assets") or {}),
            brand=data.get("brand", "内卷树懒运营日志"),
            disclaimer=data.get("disclaimer", "本视频含 AI 生成内容"),
            accent=data.get("accent", "#2E6BD6"),
        )

    @classmethod
    def load(cls, path: Path) -> "Storyboard":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def validate(self) -> list[str]:
        """返回所有问题；空列表表示可用。"""
        problems: list[str] = []
        if not self.scenes:
            problems.append("没有任何镜头")
        for index, scene in enumerate(self.scenes, 1):
            if scene.pose and scene.pose not in self.assets:
                problems.append(f"第 {index} 场引用了未定义的立绘：{scene.pose}")
            if not scene.pose and not scene.title_block and not scene.outro:
                problems.append(f"第 {index} 场既没有立绘也没有标题或片尾")
            if scene.hold_ms == 0 and not scene.has_dialogue:
                problems.append(
                    f"第 {index} 场时长为 0 且没有台词，无法由配音推算时长"
                )
        for name, path in self.assets.items():
            if not Path(path).is_file():
                problems.append(f"立绘 {name} 的文件不存在：{path}")
        if self.total_ms > 600_000:
            problems.append(f"总时长 {self.total_ms} ms 超过契约上限 10 分钟")
        return problems

    def holds(self) -> list[int]:
        """各场时长。含 0 的场次需由配音流程回填后才能渲染。"""
        return [scene.hold_ms for scene in self.scenes]
