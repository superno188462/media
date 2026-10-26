"""评论分级：决定「这一轮先看谁」。

分级只影响**顺序**，不影响「要不要回」——后者由 `intent.classify` 判。

| 级别 | 来源 | 说明 | 预算不足时 |
|---|---|---|---|
| P0 | `mentions` | 明确 @ 了账号 | **永不砍** |
| P1 | `inbox.replies` | 回复了我的评论 | **永不砍** |
| P2 | 我内容下的提问/技术/反馈 | 需要判断，量中等 | 按优先级处理 |
| P3 | 我内容下的闲聊 | 量大，多数不该回 | 最先砍 |

关键区别：P0/P1 来自 `feed inbox`，**读后即已读、不可重读**；
P2/P3 来自 `comment list`，下轮还能再拉。所以预算紧张时先保 P0/P1。
"""

from __future__ import annotations

TIER_P0 = "P0"
TIER_P1 = "P1"
TIER_P2 = "P2"
TIER_P3 = "P3"

TIER_ORDER = {TIER_P0: 0, TIER_P1: 1, TIER_P2: 2, TIER_P3: 3}

#: 这些来源不可重读，预算再紧也要处理。
UNRECOVERABLE_TIERS = {TIER_P0, TIER_P1}

#: 来源标识。
SOURCE_MENTION = "mention"
SOURCE_REPLY = "reply"
SOURCE_COMMENT = "comment"

#: 内容侧来源里，哪些类别算「值得优先看」。
_CONTENT_HIGH_CATEGORIES = {"question", "technical", "feedback", "supporter", "mention"}


def assign_tier(source: str, category: str = "") -> str:
    """给一条评论定级。"""
    if source == SOURCE_MENTION:
        return TIER_P0
    if source == SOURCE_REPLY:
        return TIER_P1
    if category in _CONTENT_HIGH_CATEGORIES:
        return TIER_P2
    return TIER_P3


def tier_sort_key(tier: str, priority: int, rpid: int) -> tuple[int, int, int]:
    """排序键：级别优先，其次内容优先级，最后按新旧（rpid 大的在前）。"""
    return (TIER_ORDER.get(tier, 9), -priority, -rpid)


def apply_budget(results, budget: int, *, keep_unrecoverable: bool = True):
    """从按优先级排好序的候选里，挑出这一轮真正处理的。

    「如果前面没有合适的可以向后顺延」——这里的语义是**填满预算**：
    顺着列表往下走，能填多少填多少，而不是「取前 N 条然后过滤」。
    所以调用方应先把不合规的剔除，再调用本函数。

    ``keep_unrecoverable=True`` 时，P0/P1 即使超出预算也保留——
    它们不可重读，丢了就永久没了。
    """
    if budget <= 0:
        return [r for r in results if keep_unrecoverable and r.tier in UNRECOVERABLE_TIERS]

    picked = []
    used = 0
    for item in results:
        unconditional = keep_unrecoverable and item.tier in UNRECOVERABLE_TIERS
        if unconditional or used < budget:
            picked.append(item)
            if not unconditional:
                used += 1
    return picked
