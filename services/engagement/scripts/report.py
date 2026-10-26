"""把一条评论区上「做过什么、结果如何」全部摊开。

用法::

    uv run python scripts/report.py                 # 汇总所有记录过的评论区
    uv run python scripts/report.py --oid 413402121 # 只看某个
    uv run python scripts/report.py --platform      # 再拉一次平台现状对照
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

from engagement.budget import HourlyBudget  # noqa: E402
from engagement.queue import PendingQueue  # noqa: E402

STATE_DIR = PROJECT_ROOT / ".local" / "engagement"
AUDIT_PATH = STATE_DIR / "audit.jsonl"
WATERMARK_PATH = STATE_DIR / "watermarks.json"
BUDGET_PATH = STATE_DIR / "budget.json"

OUTCOME_LABEL = {
    "sent": "已发送",
    "skipped": "决定不回",
    "held": "拦下待确认",
    "gate_denied": "门禁拒绝",
    "failed": "发送失败",
}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def platform_comments(oid: str, comment_type: str) -> list[dict]:
    proc = subprocess.run(
        ["cmd", "/c", str(PROJECT_ROOT / "bili.cmd"),
         "comment", "list", oid, "--type", comment_type],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    try:
        parsed = json.loads(proc.stdout or "")
    except json.JSONDecodeError:
        return []
    return ((parsed.get("data") or {}).get("items")) or []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oid", action="append", default=[])
    parser.add_argument("--platform", action="store_true", help="同时拉平台现状对照")
    args = parser.parse_args()

    audit = read_jsonl(AUDIT_PATH)
    acked = read_jsonl(STATE_DIR / "acked.jsonl")
    pending = PendingQueue(STATE_DIR).pending_items()
    watermarks = json.loads(WATERMARK_PATH.read_text(encoding="utf-8")) if WATERMARK_PATH.exists() else {}
    budget = HourlyBudget(BUDGET_PATH).state()

    oids = args.oid or sorted({row.get("oid") for row in audit if row.get("oid")})
    if not oids:
        print("还没有任何处理记录。")
        return 0

    print(f"预算：{budget.hour} 已用 {budget.sent}/{budget.quota}")
    print(f"队列：待处理 {len(pending)}，已确认 {len(acked)}")
    print()

    for oid in oids:
        rows = [r for r in audit if r.get("oid") == oid]
        print("=" * 60)
        print(f"评论区 oid={oid}  审计记录 {len(rows)} 条")
        wm = watermarks.get(f"draw:{oid}") or {}
        if wm:
            print(f"  水位线 last_rpid={wm.get('last_rpid')}")
        print()

        for row in rows:
            outcome = row.get("outcome", "?")
            extra = row.get("extra") or {}
            print(f"  rpid={row.get('rpid')}  @{row.get('author_name')}")
            print(f"    内容：{(row.get('source_text') or '').replace(chr(10), ' ')[:60]}")
            print(f"    结果：{OUTCOME_LABEL.get(outcome, outcome)}")
            print(f"    依据：{row.get('rule')} | {row.get('reason')}")
            if extra.get("category"):
                print(f"    分类：{extra.get('category')}  优先级={extra.get('priority')}"
                      f"  规则层={extra.get('layer')}")
            if extra.get("gate_decision"):
                print(f"    门禁：{extra.get('gate_decision')} 风险={extra.get('gate_risk')}"
                      f" 来源={extra.get('gate_source')}")
            if row.get("platform_rpid"):
                print(f"    平台：rpid={row.get('platform_rpid')}")
            print()

        if args.platform:
            items = platform_comments(oid, "draw")
            print(f"  --- 平台现状：{len(items)} 条 ---")
            for item in items:
                user = item.get("user") or {}
                mine = "【我方】" if str(user.get("mid")) == "383714514" else ""
                print(f"    rpid={item.get('rpid')} @{user.get('name')} {mine}")
                print(f"      {(item.get('content') or '')[:60]}")
                for reply in item.get("replies_preview") or []:
                    ru = reply.get("user") or {}
                    mine_r = "【我方】" if str(ru.get("mid")) == "383714514" else ""
                    print(f"      └ rpid={reply.get('rpid')} @{ru.get('name')} {mine_r}")
                    print(f"         {(reply.get('content') or '')[:60]}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
