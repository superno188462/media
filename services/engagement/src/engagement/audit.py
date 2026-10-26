"""审计日志。

每次判定与执行都追加一行 JSONL。要求：

- 能回答「为什么这条没走审核」
- 能回答「这条到底发没发出去」
- 崩溃后不丢已完成的记录（逐条 append，不做批量重写）
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import AuditRecord


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: AuditRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        records: list[dict] = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    # 坏行跳过，不要让一条脏数据挡住整个审计
                    continue
        return records

    def already_handled(self, event_id: str) -> bool:
        """同一个事件是否已经处理过（幂等用）。"""
        return any(r.get("event_id") == event_id for r in self.read_all())
