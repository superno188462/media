"""持久化。

首期用单个 JSON 文件保存一个工作区的全部记录，原子写入（临时文件 + 替换）。
BE-DATA-02 要求：审批对外可见时，决定、草稿版本和唯一发布任务必须**已经**
落盘；因此所有写入都先完成再返回。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .errors import STORAGE_UNAVAILABLE, ApprovalError
from .models import Draft, PublishJob, ReviewRequest


class Store:
    """工作区级的 JSON 存储。"""

    def __init__(self, root: Path, workspace_id: str) -> None:
        self.root = root
        self.workspace_id = workspace_id
        self.path = root / f"{workspace_id}.json"

    # ------------------------------------------------------------------ 读写

    def _empty(self) -> dict:
        return {"drafts": {}, "reviews": {}, "jobs": {}}

    def load(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # 读不出来就是存储不可用，不能当成「没有数据」继续操作。
            raise ApprovalError(
                STORAGE_UNAVAILABLE,
                f"无法读取存储文件 {self.path.name}",
                hint="检查文件权限或内容是否损坏；不要在此状态下做审批决定。",
            ) from None
        for key in ("drafts", "reviews", "jobs"):
            data.setdefault(key, {})
        return data

    def save(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, self.path)
        except OSError as exc:
            raise ApprovalError(
                STORAGE_UNAVAILABLE,
                f"写入存储失败：{exc}",
                hint="未发生外发；确认磁盘与权限后重试。",
            ) from exc

    # ------------------------------------------------------------------ 便捷

    def drafts(self, data: dict) -> dict[str, Draft]:
        return {k: Draft.from_dict(v) for k, v in data["drafts"].items()}

    def reviews(self, data: dict) -> dict[str, ReviewRequest]:
        return {k: ReviewRequest.from_dict(v) for k, v in data["reviews"].items()}

    def jobs(self, data: dict) -> dict[str, PublishJob]:
        return {k: PublishJob.from_dict(v) for k, v in data["jobs"].items()}
