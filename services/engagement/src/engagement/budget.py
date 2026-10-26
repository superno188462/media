"""回复预算：每小时 20 条，带 ±1 随机抖动。

为什么要有预算：

1. bili-cli 自己限流「评论 10 秒/次、30 次/小时」。撞上去要等，反而更慢。
2. 固定整点执行 + 固定条数，看起来像机器人在刷。加一点抖动不那么机械。

抖动必须**同一小时内稳定**——否则每次检查都变一个数，计数会乱。
所以用「小时桶」做随机种子：每小时不同，但同一小时内恒定。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: 每小时基准回复数。
DEFAULT_QUOTA = 20

#: 抖动幅度：quota = DEFAULT_QUOTA ± JITTER。
DEFAULT_JITTER = 1

#: 单条之间的最小间隔（秒）。bili-cli 硬限流是 10 秒。
MIN_INTERVAL_SECONDS = 10


def hour_key(moment: datetime) -> str:
    """小时桶标识，本地时间。"""
    return moment.strftime("%Y-%m-%dT%H")


def quota_for(moment: datetime, base: int = DEFAULT_QUOTA, jitter: int = DEFAULT_JITTER) -> int:
    """这一小时的配额。同一小时恒定，跨小时随机。"""
    if jitter <= 0:
        return base
    # 用字符串做种子：可复现，但每小时不同。
    rng = random.Random(f"{hour_key(moment)}|{base}|{jitter}")
    return base + rng.randint(-jitter, jitter)


@dataclass
class BudgetState:
    hour: str
    quota: int
    sent: int

    @property
    def remaining(self) -> int:
        return max(0, self.quota - self.sent)


class HourlyBudget:
    """按小时计数的回复预算。状态落在 JSON 里，重启不丢。"""

    def __init__(
        self,
        path: Path,
        base: int = DEFAULT_QUOTA,
        jitter: int = DEFAULT_JITTER,
        clock=None,
    ) -> None:
        self.path = path
        self.base = base
        self.jitter = jitter
        self._clock = clock or datetime.now

    # ---------------------------------------------------------------- 读写

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def _now(self) -> datetime:
        return self._clock()

    # ---------------------------------------------------------------- 查询

    def state(self) -> BudgetState:
        moment = self._now()
        key = hour_key(moment)
        data = self._load()
        entry = data.get(key) or {}
        quota = quota_for(moment, self.base, self.jitter)
        try:
            sent = int(entry.get("sent", 0))
        except (TypeError, ValueError):
            sent = 0
        return BudgetState(hour=key, quota=quota, sent=sent)

    def remaining(self) -> int:
        return self.state().remaining

    def can_send(self, count: int = 1) -> bool:
        return self.remaining() >= count

    # ---------------------------------------------------------------- 记账

    def record(self, count: int = 1) -> BudgetState:
        moment = self._now()
        key = hour_key(moment)
        data = self._load()
        entry = data.setdefault(key, {"quota": quota_for(moment, self.base, self.jitter), "sent": 0})
        entry["sent"] = int(entry.get("sent", 0)) + count
        # 只保留最近 48 小时，避免文件无限增长。
        keep = sorted(data.keys())[-48:]
        data = {k: data[k] for k in keep}
        self._save(data)
        return self.state()

    def reset_hour(self) -> None:
        """把当前小时计数清零（测试或人工纠错用）。"""
        moment = self._now()
        key = hour_key(moment)
        data = self._load()
        data[key] = {"quota": quota_for(moment, self.base, self.jitter), "sent": 0}
        self._save(data)
