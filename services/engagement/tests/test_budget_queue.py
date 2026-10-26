"""预算、分级、队列的测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from engagement.budget import (
    DEFAULT_QUOTA,
    HourlyBudget,
    hour_key,
    quota_for,
)
from engagement.queue import PendingQueue, QueueItem
from engagement.tiers import (
    TIER_P0,
    TIER_P1,
    TIER_P2,
    TIER_P3,
    apply_budget,
    assign_tier,
    tier_sort_key,
)

FIXED = datetime(2026, 10, 26, 19, 30, 0)


# ============================================================ 预算

def test_quota_is_within_jitter_range():
    for hour in range(24):
        moment = datetime(2026, 10, 26, hour, 0, 0)
        q = quota_for(moment)
        assert DEFAULT_QUOTA - 1 <= q <= DEFAULT_QUOTA + 1


def test_quota_is_stable_within_same_hour():
    a = quota_for(datetime(2026, 10, 26, 19, 1, 0))
    b = quota_for(datetime(2026, 10, 26, 19, 59, 0))
    assert a == b


def test_quota_varies_across_hours():
    values = {quota_for(datetime(2026, 10, 26, h, 0, 0)) for h in range(24)}
    assert len(values) > 1  # 不是永远同一个数


def test_zero_jitter_gives_exact_quota():
    moment = datetime(2026, 10, 26, 19, 0, 0)
    assert quota_for(moment, base=20, jitter=0) == 20


def test_hour_key_format():
    assert hour_key(FIXED) == "2026-10-26T19"


def test_budget_counts_and_persists(tmp_path):
    budget = HourlyBudget(tmp_path / "b.json", clock=lambda: FIXED)
    start = budget.remaining()
    assert start == budget.state().quota

    budget.record(3)
    assert budget.remaining() == start - 3

    # 重新打开，计数还在
    reopened = HourlyBudget(tmp_path / "b.json", clock=lambda: FIXED)
    assert reopened.remaining() == start - 3


def test_budget_can_send_respects_remaining(tmp_path):
    budget = HourlyBudget(tmp_path / "b.json", base=2, jitter=0, clock=lambda: FIXED)
    assert budget.can_send(2) is True
    budget.record(2)
    assert budget.can_send(1) is False


def test_budget_rolls_over_next_hour(tmp_path):
    moment = {"now": FIXED}
    budget = HourlyBudget(tmp_path / "b.json", clock=lambda: moment["now"])
    budget.record(budget.state().quota)          # 用完这一小时
    assert budget.remaining() == 0

    moment["now"] = datetime(2026, 10, 26, 20, 5, 0)   # 下一个小时
    assert budget.remaining() > 0


def test_budget_keeps_file_bounded(tmp_path):
    moment = {"now": datetime(2026, 10, 20, 0, 0, 0)}
    budget = HourlyBudget(tmp_path / "b.json", clock=lambda: moment["now"])
    for _ in range(60):
        budget.record(1)
        moment["now"] = moment["now"].replace(hour=(moment["now"].hour + 1) % 24)
    import json

    data = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    assert len(data) <= 48


def test_budget_corrupt_file_does_not_crash(tmp_path):
    path = tmp_path / "b.json"
    path.write_text("{broken", encoding="utf-8")
    budget = HourlyBudget(path, clock=lambda: FIXED)
    assert budget.remaining() == budget.state().quota


# ============================================================ 分级

def test_mention_is_p0():
    assert assign_tier("mention") == TIER_P0


def test_reply_is_p1():
    assert assign_tier("reply") == TIER_P1


def test_content_question_is_p2():
    assert assign_tier("comment", "question") == TIER_P2
    assert assign_tier("comment", "technical") == TIER_P2


def test_content_chatter_is_p3():
    assert assign_tier("comment", "noise") == TIER_P3
    assert assign_tier("comment", "unclear") == TIER_P3


def test_sort_key_orders_tiers():
    keys = [
        tier_sort_key(TIER_P3, 0, 100),
        tier_sort_key(TIER_P0, 0, 1),
        tier_sort_key(TIER_P1, 0, 50),
        tier_sort_key(TIER_P2, 9, 200),
    ]
    ordered = sorted(keys)
    assert ordered[0][0] == 0  # P0 最前
    assert ordered[-1][0] == 3  # P3 最后


class FakeCandidate:
    def __init__(self, tier: str, rpid: int = 1) -> None:
        self.tier = tier
        self.rpid = rpid


def test_apply_budget_fills_sequentially():
    items = [FakeCandidate(TIER_P2, i) for i in range(10)]
    picked = apply_budget(items, budget=4, keep_unrecoverable=False)
    assert len(picked) == 4


def test_apply_budget_keeps_unrecoverable_even_over_budget():
    items = [
        FakeCandidate(TIER_P0, 1),
        FakeCandidate(TIER_P1, 2),
        FakeCandidate(TIER_P2, 3),
        FakeCandidate(TIER_P2, 4),
    ]
    picked = apply_budget(items, budget=1, keep_unrecoverable=True)
    tiers = [i.tier for i in picked]
    assert TIER_P0 in tiers and TIER_P1 in tiers


def test_apply_budget_zero_still_keeps_unrecoverable():
    items = [FakeCandidate(TIER_P0, 1), FakeCandidate(TIER_P2, 2)]
    picked = apply_budget(items, budget=0, keep_unrecoverable=True)
    assert [i.tier for i in picked] == [TIER_P0]


# ============================================================ 队列

def make_item(event_id: str = "e1", tier: str = TIER_P2, rpid: int = 1) -> QueueItem:
    return QueueItem(
        event_id=event_id,
        source="comment",
        tier=tier,
        oid="413402121",
        rpid=rpid,
        comment_type="draw",
        root=None,
        author_name="某人",
        author_mid="9",
        content="怎么弄？",
        time="2026-10-26T19:00:00+08:00",
    )


def test_push_and_read(tmp_path):
    q = PendingQueue(tmp_path)
    assert q.push([make_item("e1"), make_item("e2")]) == 2
    assert len(q.pending_items()) == 2


def test_push_is_idempotent(tmp_path):
    q = PendingQueue(tmp_path)
    q.push([make_item("e1")])
    assert q.push([make_item("e1")]) == 0
    assert len(q.pending_items()) == 1


def test_ack_removes_from_pending(tmp_path):
    q = PendingQueue(tmp_path)
    q.push([make_item("e1"), make_item("e2")])
    q.ack(["e1"], outcome="skipped")
    pending = q.pending_items()
    assert [i.event_id for i in pending] == ["e2"]


def test_acked_items_not_requeued(tmp_path):
    q = PendingQueue(tmp_path)
    q.push([make_item("e1")])
    q.ack(["e1"])
    assert q.push([make_item("e1")]) == 0


def test_store_batch_keeps_raw_payload(tmp_path):
    q = PendingQueue(tmp_path)
    q.store_batch({"unread": {"replies": 1}, "replies": [{"rpid": 1}]})
    assert q.batches_path.exists()
    text = q.batches_path.read_text(encoding="utf-8")
    assert '"replies"' in text


def test_stats(tmp_path):
    q = PendingQueue(tmp_path)
    q.push([make_item("e1"), make_item("e2")])
    q.ack(["e1"])
    s = q.stats()
    assert s["pending"] == 1
    assert s["acked"] == 1


def test_bad_lines_are_skipped(tmp_path):
    q = PendingQueue(tmp_path)
    q.push([make_item("e1")])
    with q.pending_path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    q.push([make_item("e2")])
    assert len(q.pending_items()) == 2
