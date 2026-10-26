"""评论漏斗：从一堆评论里挑出**值得回的那几条**。

用法::

    # 只看某条动态/视频
    uv run python scripts/triage.py --oid 413402056 --type draw

    # 看规则
    uv run python scripts/triage.py --rules

    # 重置水位线（下次重新检查全部未回复评论）
    uv run python scripts/triage.py --oid 413402056 --reset
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

sys.path.insert(0, str(_HERE.parents[1] / "src"))

from engagement import (  # noqa: E402
    AuditLog,
    BiliClient,
    WatermarkStore,
    describe_relevance_rules,
    fetch_new,
)
from engagement.intent import classify as classify_intent  # noqa: E402
from engagement.llm import LlmClient, LlmConfig, LlmError  # noqa: E402
from engagement.models import AuditRecord, now_utc  # noqa: E402

STATE_DIR = PROJECT_ROOT / ".local" / "engagement"
WATERMARK_PATH = STATE_DIR / "watermarks.json"
AUDIT_PATH = STATE_DIR / "audit.jsonl"
CRED_FILE = PROJECT_ROOT / ".local" / "dsh" / ".credentials.yaml"
SELF_MID = "383714514"  # 内卷树懒


def record_skipped(results, oid: str, comment_type: str, log: AuditLog, queue=None) -> int:
    """把「决定不回」的判定也落盘——过程可追溯，不只是发了什么。

    同时确认掉队列里的对应条目，否则它会永远挂在 pending。
    """
    written = 0
    acked: list[str] = []
    for item in results:
        if item.accepted:
            continue
        comment = item.comment
        event_id = f"{comment_type}:{oid}:{comment.rpid}"
        acked.append(event_id)
        if log.already_handled(event_id):
            continue
        log.append(
            AuditRecord(
                at=now_utc(),
                event_id=event_id,
                oid=oid,
                rpid=comment.rpid,
                comment_type=comment_type,
                author_name=comment.user_name,
                author_mid=comment.user_mid,
                source_text=comment.content,
                reply_text="",
                risk="none",
                route="skip",
                rule=item.relevance.rule,
                reason=item.relevance.reason,
                outcome="skipped",
                detail=f"类别={item.relevance.category} 优先级={item.relevance.priority}",
                extra={
                    "layer": "relevance",
                    "category": item.relevance.category,
                    "priority": item.relevance.priority,
                    "nested": comment.is_nested,
                    "root": comment.root,
                },
            )
        )
        written += 1

    if queue is not None and acked:
        queue.ack(acked, outcome="skipped")
    return written


def load_llm(disabled: bool = False) -> LlmClient | None:
    if disabled:
        return None
    try:
        return LlmClient(LlmConfig.from_credentials(CRED_FILE))
    except LlmError:
        return None


def make_classifier(llm):
    """模型优先、正则兜底。返回函数，签名为 comment -> Relevance。"""

    def classify(comment):
        intent = classify_intent(
            comment.content,
            llm,
            is_supporter=comment.is_supporter,
            author_name=comment.user_name,
        )
        return intent.to_relevance()

    return classify


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oid")
    parser.add_argument("--type", default="draw", dest="comment_type")
    parser.add_argument("--limit", type=int, default=10, help="最多保留几条候选")
    parser.add_argument("--max-pages", type=int, default=2, help="最多翻几页")
    parser.add_argument("--rules", action="store_true")
    parser.add_argument("--reset", action="store_true", help="重置该 oid 的水位线")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    parser.add_argument(
        "--include-replied",
        action="store_true",
        help="连已回复的一起拉（调试规则用，不推进水位线）",
    )
    parser.add_argument("--no-llm", action="store_true", help="只用正则，不调模型")
    parser.add_argument(
        "--record-skipped",
        action="store_true",
        help="把「决定不回」的判定也写入审计日志（记录过程）",
    )
    args = parser.parse_args()

    if args.rules:
        print("第一层 · 该不该回：")
        for row in describe_relevance_rules():
            mark = "回" if row["reply"] else "不回"
            prio = row.get("priority", "-")
            print(f"  [{mark:>2}] {row['rule']:<20} {row['category']:<10} prio={prio:<3} {row['reason']}")
        return 0

    if not args.oid:
        parser.error("需要 --oid（或用 --rules）")

    store = WatermarkStore(WATERMARK_PATH)

    if args.reset:
        store.set(args.oid, args.comment_type, 0)
        print(f"已重置 {args.comment_type}:{args.oid} 的水位线")

    client = BiliClient(PROJECT_ROOT)
    llm = load_llm(disabled=args.no_llm)
    classifier = make_classifier(llm)
    print(f"判定方式：{'大模型 + 正则兜底' if llm else '仅正则（未配置模型）'}")

    if args.include_replied:
        # 调试模式：直接读全部评论，只跑分类，不碰水位线。
        items, meta = client.list_comments(
            args.oid, args.comment_type, page=1, unreplied=False
        )
        if meta.get("error"):
            print(f"读取失败：{meta['error']}", file=sys.stderr)
            return 3
        from engagement.collect import RawComment, summarize, triage as triage_comments

        comments = [c for c in (RawComment.from_api(i, args.oid) for i in items) if c]
        results = triage_comments(
            comments, limit=args.limit, self_mid=SELF_MID, classifier=classifier
        )
        stats = summarize(results)
        print(f"评论区 {args.comment_type}:{args.oid}（含已回复，共 {len(comments)} 条）")
        print(f"  进入候选 : {stats['accepted']}   过滤掉 : {stats['rejected']}  {stats['rejected_by_rule']}")
        print()
        for item in results:
            mark = "回" if item.accepted else "不回"
            cat = item.relevance.category
            scope = "楼中楼" if item.comment.is_nested else "根评论"
            print(f"  [{mark}] {cat:<10} {scope} rpid={item.comment.rpid} @{item.comment.user_name}")
            print(f"       {(item.comment.content or '')[:70]}")
            print(f"       → {item.relevance.reason}")
        if args.record_skipped:
            from engagement.queue import PendingQueue

            n = record_skipped(
                results, args.oid, args.comment_type,
                AuditLog(AUDIT_PATH), PendingQueue(STATE_DIR),
            )
            print(f"\n已记录 {n} 条「不回」判定，并确认队列条目。")
        return 0

    results, stats = fetch_new(
        client,
        args.oid,
        args.comment_type,
        store,
        max_pages=args.max_pages,
        limit=args.limit,
        self_mid=SELF_MID,
        classifier=classifier,
    )

    if args.json:
        print(json.dumps(
            {
                "stats": stats,
                "accepted": [
                    {
                        "rpid": t.comment.rpid,
                        "user": t.comment.user_name,
                        "content": t.comment.content,
                        "category": t.relevance.category,
                        "priority": t.relevance.priority,
                    }
                    for t in results if t.accepted
                ],
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    print(f"评论区 {args.comment_type}:{args.oid}")
    print(f"  翻页          : {stats['pages_read']}")
    print(f"  新评论        : {stats['new']}")
    print(f"  进入候选      : {stats['accepted']}")
    print(f"  过滤掉        : {stats['rejected']}  {stats['rejected_by_rule']}")
    print(f"  水位线        : {stats['watermark_before']} → {stats['watermark_after']}")
    if stats.get("errors"):
        print(f"  错误          : {stats['errors']}")

    accepted = [t for t in results if t.accepted]
    if not accepted:
        print("\n没有值得回复的新评论。")
        return 0

    print(f"\n按优先级排序（前 {len(accepted)} 条）：")
    for i, item in enumerate(accepted, 1):
        c = item.comment
        print(f"  {i}. [{item.relevance.category}] prio={item.relevance.priority} "
              f"rpid={c.rpid} @{c.user_name}")
        print(f"     {(c.content or '')[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
