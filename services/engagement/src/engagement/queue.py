"""待处理队列：**先落盘，再处理**。

存在的原因是 ``feed inbox`` 的破坏性读取：平台在你读取后就把消息标为已读，
重复调用拿不到同一批。所以顺序必须是

    读 → 立刻原子落盘 → 落盘成功后才允许处理

如果落盘失败，宁可这一轮报错停止，也不能"边读边处理"——
否则进程一崩，那批消息就永久丢了。

全部用 append-only JSONL：

- ``inbox_batches.jsonl``：每次 inbox 的原始载荷（证据，不改）
- ``pending.jsonl``：待处理项
- ``acked.jsonl``：已处理的 event_id
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .models import now_utc


@dataclass
class QueueItem:
    """一条待处理的评论。"""

    event_id: str
    source: str            # mention / reply / comment
    tier: str              # P0–P3
    oid: str
    rpid: int
    comment_type: str      # draw / dynamic / video / article
    root: int | None       # 楼中楼时所属根评论
    author_name: str = ""
    author_mid: str = ""
    content: str = ""
    time: str = ""
    added_at: str = field(default_factory=now_utc)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "QueueItem":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


class PendingQueue:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.pending_path = root / "pending.jsonl"
        self.acked_path = root / "acked.jsonl"
        self.batches_path = root / "inbox_batches.jsonl"

    # ------------------------------------------------------------ 原子写

    def _append(self, path: Path, lines: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for line in lines:
                handle.write(line + "\n")
            handle.flush()

    # ------------------------------------------------------------ 原始批次

    def store_batch(self, payload: dict) -> None:
        """原样保存一次 inbox 的返回。**这一步失败就不应继续处理。**"""
        record = {"at": now_utc(), "payload": payload}
        self._append(self.batches_path, [json.dumps(record, ensure_ascii=False)])

    # ------------------------------------------------------------ 入队

    def push(self, items: list[QueueItem]) -> int:
        """批量入队。已存在或已处理的跳过。"""
        existing = {item.event_id for item in self.all_items()}
        acked = self.acked_ids()
        fresh = [i for i in items if i.event_id not in existing and i.event_id not in acked]
        if fresh:
            self._append(self.pending_path, [json.dumps(i.to_dict(), ensure_ascii=False) for i in fresh])
        return len(fresh)

    # ------------------------------------------------------------ 读取

    def all_items(self) -> list[QueueItem]:
        if not self.pending_path.exists():
            return []
        items: list[QueueItem] = []
        for line in self.pending_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(QueueItem.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
        return items

    def acked_ids(self) -> set[str]:
        if not self.acked_path.exists():
            return set()
        ids: set[str] = set()
        for line in self.acked_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    ids.add(str(json.loads(line)["event_id"]))
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
        return ids

    def pending_items(self) -> list[QueueItem]:
        acked = self.acked_ids()
        return [i for i in self.all_items() if i.event_id not in acked]

    # ------------------------------------------------------------ 确认

    def ack(self, event_ids: list[str], outcome: str = "done") -> int:
        if not event_ids:
            return 0
        stamp = now_utc()
        lines = [
            json.dumps({"event_id": eid, "outcome": outcome, "at": stamp}, ensure_ascii=False)
            for eid in event_ids
        ]
        self._append(self.acked_path, lines)
        return len(lines)

    def stats(self) -> dict:
        return {
            "pending": len(self.pending_items()),
            "acked": len(self.acked_ids()),
            "total_ever": len(self.all_items()),
        }
