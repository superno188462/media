"""内容项的数据模型。

对应 `manual/contracts/cyber-sloth.schema.json` 的公共字段，
以及只属于内容侧的结构（正文、配图、平台参数）。

状态机：
    draft ──→ pending_review ──→ approved ──→ published
                   │
                   └──→ draft（人工驳回）
    published ──→ failed（发布结果未知，需人工核对平台证据）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

Status = Literal["draft", "pending_review", "approved", "published", "failed"]

#: 允许的状态流转。任何不在表里的流转都要拒绝。
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending_review"},
    "pending_review": {"draft", "approved"},
    "approved": {"published", "failed"},
    "published": set(),
    "failed": set(),
}


@dataclass
class ContentItem:
    """一条待发布的内容。

    图片顺序即发布顺序（契约 R3）：``images`` 的下标就是发布时的排列次序，
    不可在发布阶段重排。
    """

    id: str
    topic_id: str
    title: str
    body: str
    images: list[str] = field(default_factory=list)
    #: 每张图对应的来源说明，用于素材台账（见 assets/SOURCES.md）。
    source_urls: list[str] = field(default_factory=list)
    #: 平台话题；None 表示不带话题。
    topic: str | None = None
    #: 要 @ 的人（昵称或 UID）。
    at_users: list[str] = field(default_factory=list)
    #: AI 参与声明。动态与评论没有平台级 AI 开关，只能写进正文，
    #: 因此这一项必须显式给出，且由 validate.py 的 R2 强制检查。
    ai_declaration: str | None = None
    status: Status = "draft"
    #: 平台侧的稿件 ID 或链接；published 后写入，用于对账。
    published_ref: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    # ---------------------------------------------------------------- transitions

    def can_transition_to(self, target: str) -> bool:
        return target in ALLOWED_TRANSITIONS.get(self.status, set())

    def transition_to(self, target: str) -> None:
        """按状态机流转。非法流转抛 ValueError。"""
        if not self.can_transition_to(target):
            raise ValueError(f"非法状态流转: {self.status} -> {target}")
        self.status = target  # type: ignore[assignment]

    # ---------------------------------------------------------------- persistence

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ContentItem":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> "ContentItem":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
