"""评论回复的分流执行。

用法::

    # 先看看会怎么判（不发送）
    uv run python scripts/reply.py --assess-only \
        --oid 413402056 --rpid 318247075745 --file reply.txt

    # 判定为直发就真的发出去
    uv run python scripts/reply.py \
        --oid 413402056 --rpid 318247075745 --file reply.txt

    # 从收件箱列出待回复项（只读）
    uv run python scripts/reply.py --inbox

判定规则见 ``src/engagement/policy.py``，全部是确定性规则。
低风险 → 直接发；中/高风险 → 只记录「被拦下」，卡片通道尚未实现。
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

from engagement import (  # noqa: E402
    ROUTE_DIRECT,
    ROUTE_LABEL,
    AuditLog,
    BiliClient,
    ReplyCandidate,
    assess,
    describe_rules,
    make_record,
)
from engagement.gate import check as gate_check  # noqa: E402
from engagement.llm import LlmClient, LlmConfig, LlmError  # noqa: E402

AUDIT_PATH = PROJECT_ROOT / ".local" / "engagement" / "audit.jsonl"
CRED_FILE = PROJECT_ROOT / ".local" / "dsh" / ".credentials.yaml"


def load_llm(disabled: bool = False) -> LlmClient | None:
    """加载门禁用的模型。拿不到就返回 None——门禁会因此拒绝发送。"""
    if disabled:
        return None
    try:
        return LlmClient(LlmConfig.from_credentials(CRED_FILE))
    except LlmError:
        return None


def load_inbox() -> list[dict]:
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
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return ((parsed.get("data") or {}).get("replies")) or []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbox", action="store_true", help="列出待回复项（只读）")
    parser.add_argument("--rules", action="store_true", help="打印判定规则表")
    parser.add_argument("--assess-only", action="store_true", help="只判定不发送")
    parser.add_argument("--oid")
    parser.add_argument("--rpid", type=int)
    parser.add_argument("--type", default="draw", dest="comment_type")
    parser.add_argument("--root", type=int, default=None, help="回复楼中楼时填根评论 ID")
    parser.add_argument("--file", help="回复正文文件（UTF-8）")
    parser.add_argument("--event-id", default=None, help="自定义幂等键，默认用 oid:rpid")
    parser.add_argument("--source-file", help="对方原评论的正文文件；门禁需要它来判断相关性")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="禁用模型门禁（会因此拒绝发送，仅用于测试 fail-closed）",
    )
    args = parser.parse_args()

    if args.rules:
        for row in describe_rules():
            print(f"  {row['rule']:<20} risk={row['risk']:<6} route={row['route']:<7} {row['reason']}")
        return 0

    if args.inbox:
        replies = load_inbox()
        if not replies:
            print("没有新的回复。")
            return 0
        print(f"待处理 {len(replies)} 条：")
        for item in replies:
            on = item.get("on") or {}
            print(f"  rpid={item.get('rpid')} oid={on.get('oid')} type={on.get('type')}")
            print(f"    @{item.get('user', {}).get('name')}: {(item.get('content') or '')[:60]}")
        return 0

    if not (args.oid and args.rpid and args.file):
        parser.error("需要 --oid、--rpid、--file（或用 --inbox / --rules）")

    reply_path = Path(args.file)
    if not reply_path.exists():
        print(f"回复文件不存在：{reply_path}", file=sys.stderr)
        return 2
    reply_text = reply_path.read_text(encoding="utf-8").strip()

    source_text = ""
    if args.source_file:
        src_path = Path(args.source_file)
        if not src_path.exists():
            print(f"原评论文件不存在：{src_path}", file=sys.stderr)
            return 2
        source_text = src_path.read_text(encoding="utf-8").strip()

    candidate = ReplyCandidate(
        event_id=args.event_id or f"{args.oid}:{args.rpid}",
        oid=args.oid,
        rpid=args.rpid,
        comment_type=args.comment_type,
        source_text=source_text,
        reply_text=reply_text,
    )

    log = AuditLog(AUDIT_PATH)
    assessment = assess(candidate)
    print(f"第二层判定（怎么发）：{assessment.describe()}")
    print(f"回复内容（{len(reply_text)} 字）：{reply_text}")

    if log.already_handled(candidate.event_id):
        print("该事件已处理过，跳过（幂等）。")
        return 0

    if args.assess_only:
        print("（--assess-only，未发送）")
        return 0

    if assessment.route != ROUTE_DIRECT:
        log.append(
            make_record(
                candidate,
                assessment,
                outcome="held",
                detail=f"需要人工确认（{ROUTE_LABEL[assessment.route]}），当前未自动发送",
            )
        )
        print(f"\n已拦下：{ROUTE_LABEL[assessment.route]}。未发送，已记入审计。")
        return 0

    # --- 发送前门禁：拿不到 approve 就到这里为止 ---
    llm = load_llm(disabled=args.no_llm)
    gate = gate_check(source_text, reply_text, llm, author_name=candidate.author_name)
    print(f"\n发送前门禁：{gate.describe()}")

    gate_extra = {
        "gate_decision": gate.decision,
        "gate_risk": gate.risk,
        "gate_reasons": gate.reasons,
        "gate_source": gate.source,
        "model_gate": gate.source == "llm",
    }

    if not gate.allows_send:
        log.append(
            make_record(
                candidate,
                assessment,
                outcome="gate_denied",
                detail=gate.describe(),
                extra=gate_extra,
            )
        )
        print("门禁未通过，**未发送**。")
        return 0

    client = BiliClient(PROJECT_ROOT)
    result = client.reply(
        args.oid, args.rpid, reply_text, comment_type=args.comment_type, root=args.root
    )
    if not result.sent:
        log.append(
            make_record(
                candidate, assessment, outcome="failed",
                detail=result.detail, extra=gate_extra,
            )
        )
        print(f"\n发送失败：{result.detail}", file=sys.stderr)
        return 4

    visible, note = client.is_visible(
        args.oid, result.rpid, comment_type=args.comment_type, root=args.rpid
    )
    log.append(
        make_record(
            candidate,
            assessment,
            outcome="sent",
            detail=f"visible={visible} {note}".strip(),
            platform_rpid=result.rpid,
            extra=gate_extra,
        )
    )
    print(f"\n已发送 rpid={result.rpid}；可见性 {visible}（{note}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
