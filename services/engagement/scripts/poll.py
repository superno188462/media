"""一轮采集：`feed inbox` + `comment list` → 持久队列。

用法::

    # 只采集入队，并显示这一小时能处理多少
    uv run python scripts/poll.py --oid 413402121

    # 连队列内容一起列出
    uv run python scripts/poll.py --oid 413402121 --show

    # 只看队列和预算，不采集
    uv run python scripts/poll.py --status

**本脚本不发送任何内容。** 发送在 reply.py，且必须过门禁。

顺序很重要：`feed inbox` 读完即标记已读，所以必须
「读 → 立刻落盘 → 落盘成功后才处理」。落盘失败就中止这一轮。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

sys.path.insert(0, str(_HERE.parents[1] / "src"))

from engagement import BiliClient, WatermarkStore, fetch_new  # noqa: E402
from engagement.budget import HourlyBudget  # noqa: E402
from engagement.intent import classify as classify_intent  # noqa: E402
from engagement.llm import LlmClient, LlmConfig, LlmError  # noqa: E402
from engagement.queue import PendingQueue, QueueItem  # noqa: E402
from engagement.tiers import (  # noqa: E402
    SOURCE_COMMENT,
    SOURCE_MENTION,
    SOURCE_REPLY,
    TIER_P0,
    TIER_P1,
    TIER_P2,
    TIER_P3,
    assign_tier,
    tier_sort_key,
)

STATE_DIR = PROJECT_ROOT / ".local" / "engagement"
WATERMARK_PATH = STATE_DIR / "watermarks.json"
BUDGET_PATH = STATE_DIR / "budget.json"
CRED_FILE = PROJECT_ROOT / ".local" / "dsh" / ".credentials.yaml"
SELF_MID = "383714514"


def load_llm(disabled: bool = False) -> LlmClient | None:
    if disabled:
        return None
    try:
        return LlmClient(LlmConfig.from_credentials(CRED_FILE))
    except LlmError:
        return None


def run_inbox() -> dict | None:
    proc = subprocess.run(
        ["cmd", "/c", str(PROJECT_ROOT / "bili.cmd"), "feed", "inbox"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not parsed.get("ok"):
        return None
    return parsed.get("data") or {}


def items_from_inbox(data: dict) -> list[QueueItem]:
    """把 inbox 的 replies / mentions 转成队列入参。"""
    items: list[QueueItem] = []
    for key, source in (("mentions", SOURCE_MENTION), ("replies", SOURCE_REPLY)):
        for entry in data.get(key) or []:
            on = entry.get("on") or {}
            oid = on.get("oid")
            comment_type = on.get("type") or "draw"
            try:
                rpid = int(entry.get("rpid"))
            except (TypeError, ValueError):
                continue
            if not oid:
                continue
            user = entry.get("user") or {}
            root = entry.get("root")
            try:
                root = int(root) if root not in (None, "") else None
            except (TypeError, ValueError):
                root = None
            items.append(
                QueueItem(
                    event_id=f"{comment_type}:{oid}:{rpid}",
                    source=source,
                    tier=assign_tier(source),
                    oid=str(oid),
                    rpid=rpid,
                    comment_type=str(comment_type),
                    root=root,
                    author_name=str(user.get("name", "")),
                    author_mid=str(user.get("mid", "")),
                    content=str(entry.get("content") or ""),
                    time=str(entry.get("time") or ""),
                )
            )
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oid", action="append", default=[], help="要采集的评论区 oid，可重复")
    parser.add_argument("--type", default="draw", dest="comment_type")
    parser.add_argument("--status", action="store_true", help="只看队列与预算，不采集")
    parser.add_argument("--show", action="store_true", help="列出队列内容")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--base", type=int, default=20, help="每小时基准回复数")
    parser.add_argument("--jitter", type=int, default=1, help="抖动幅度 ±N")
    args = parser.parse_args()

    queue = PendingQueue(STATE_DIR)
    budget = HourlyBudget(BUDGET_PATH, base=args.base, jitter=args.jitter)
    llm = load_llm(disabled=args.no_llm)

    if not args.status:
        # --- 1. inbox：读 → 立刻落盘 ---
        data = run_inbox()
        if data is None:
            print("feed inbox 读取失败，本轮中止（不改动任何状态）。", file=sys.stderr)
            return 2

        try:
            queue.store_batch(data)
        except OSError as exc:
            print(f"inbox 落盘失败，中止：{exc}", file=sys.stderr)
            print("注意：inbox 已读，这批消息可能无法再次读取。", file=sys.stderr)
            return 3

        inbox_items = items_from_inbox(data)
        added_inbox = queue.push(inbox_items)
        print(f"inbox：{len(inbox_items)} 条（新入队 {added_inbox}）")
        for tier in (TIER_P0, TIER_P1):
            count = sum(1 for i in inbox_items if i.tier == tier)
            if count:
                print(f"  {tier}: {count}")

        # --- 2. comment list 增量 ---
        if args.oid:
            client = BiliClient(PROJECT_ROOT)
            watermarks = WatermarkStore(WATERMARK_PATH)

            def classifier(comment):
                intent = classify_intent(
                    comment.content, llm,
                    is_supporter=comment.is_supporter,
                    author_name=comment.user_name,
                )
                return intent.to_relevance()

            for oid in args.oid:
                results, stats = fetch_new(
                    client, oid, args.comment_type, watermarks,
                    limit=40, self_mid=SELF_MID, classifier=classifier,
                )
                new_items = []
                for item in results:
                    c = item.comment
                    cat = item.relevance.category
                    new_items.append(
                        QueueItem(
                            event_id=f"{args.comment_type}:{oid}:{c.rpid}",
                            source=SOURCE_COMMENT,
                            tier=assign_tier(SOURCE_COMMENT, cat),
                            oid=oid,
                            rpid=c.rpid,
                            comment_type=args.comment_type,
                            root=c.root,
                            author_name=c.user_name,
                            author_mid=c.user_mid,
                            content=c.content,
                            time=c.time,
                        )
                    )
                added = queue.push(new_items)
                print(
                    f"评论 {oid}：新 {stats['new']} 条（含楼中楼 {stats['nested_found']}），"
                    f"入队 {added}"
                )

    # --- 3. 报告 ---
    state = budget.state()
    pending = queue.pending_items()
    ordered = sorted(
        pending,
        key=lambda i: tier_sort_key(i.tier, 0, i.rpid),
    )
    counts = {t: sum(1 for i in ordered if i.tier == t) for t in (TIER_P0, TIER_P1, TIER_P2, TIER_P3)}

    print()
    print(f"预算：{state.hour} 已用 {state.sent}/{state.quota}，剩余 {state.remaining}")
    print(f"队列：待处理 {len(pending)}（P0={counts[TIER_P0]} P1={counts[TIER_P1]} "
          f"P2={counts[TIER_P2]} P3={counts[TIER_P3]}）")

    if args.show and ordered:
        print()
        print("按级别排序（前 15 条）：")
        for i, item in enumerate(ordered[:15], 1):
            scope = "楼中楼" if item.root else "根评论"
            print(f"  {i}. [{item.tier}] {item.source:<7} {scope} rpid={item.rpid} @{item.author_name}")
            print(f"     {(item.content or '')[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
