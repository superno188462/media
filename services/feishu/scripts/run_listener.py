"""启动飞书长连接监听，接收审核卡片按钮动作，并驱动审核状态机。

用法::

    uv run --with lark-oapi --no-project python scripts/run_listener.py

配置从 `.local/dsh/.credentials.yaml` 或环境变量读取。

每条可信决定会：
- 交给 ``services/approval`` 的状态机：落审核状态、必要时创建唯一发布任务
- 打印到 stdout（一行 JSON）
- 追加到 ``.local/feishu-decisions.jsonl``

**本脚本不执行发布**。批准后只创建 QUEUED 任务；真正提交由受信执行器
（BE-IF-03）负责，尚未实现。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

sys.path.insert(0, str(_HERE.parents[1] / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "approval" / "src"))

from approval import ApprovalError, ApprovalService  # noqa: E402
from feishu.credentials import load_from_file  # noqa: E402
from feishu.listener import FeishuCardListener  # noqa: E402

CRED_FILE = PROJECT_ROOT / ".local" / "dsh" / ".credentials.yaml"
DECISION_LOG = PROJECT_ROOT / ".local" / "feishu-decisions.jsonl"
RAW_LOG = PROJECT_ROOT / ".local" / "feishu-raw-actions.jsonl"
APPROVAL_ROOT = PROJECT_ROOT / ".local" / "approval"

#: 由 main() 填好，供回调使用。
_service: ApprovalService | None = None


def _append_log(record: dict) -> None:
    DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with DECISION_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def on_raw(data: dict) -> None:
    """把卡片动作的原始载荷落一份，便于核对平台真实字段。"""
    RAW_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RAW_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": _stamp(), "raw": data}, ensure_ascii=False) + "\n")
    action = (data.get("event") or data).get("action")
    print("RAW_ACTION " + json.dumps(action, ensure_ascii=False), flush=True)


def on_decision(context, decision) -> str | None:
    """把可信决定交给状态机。返回给审核人看的 toast 文案。"""
    base = {
        "at": _stamp(),
        "review_id": decision.review_id,
        "revision": decision.expected_revision,
        "content_digest": decision.content_digest,
        "action": decision.action,
        "feedback": decision.feedback,
        "provider_event_id": decision.provider_event_id,
        "operator_open_id": context.operator_open_id,
        "tenant_key": context.tenant_key,
        "chat_id": context.open_chat_id,
        "message_id": context.open_message_id,
    }

    assert _service is not None
    try:
        result = _service.apply_decision(context, decision)
    except ApprovalError as exc:
        record = {**base, "kind": "decision_rejected", "code": exc.code, "error": exc.message}
        _append_log(record)
        print("DECISION_REJECTED " + json.dumps(record, ensure_ascii=False), flush=True)
        return f"{exc.code}：{exc.message}"

    record = {
        **base,
        "kind": "decision_applied" if result.applied else "decision_replayed",
        "review_status": result.review.status,
        "job_id": result.publish_job.job_id if result.publish_job else None,
    }
    _append_log(record)
    print(
        ("DECISION " if result.applied else "DECISION_REPLAY ")
        + json.dumps(record, ensure_ascii=False),
        flush=True,
    )

    if not result.applied:
        return "这条操作已经处理过了，没有重复执行"
    if result.publish_job is not None:
        return f"已批准，发布任务 {result.publish_job.job_id} 已排队"
    if decision.action == "reject":
        return "已退回，等待改稿后重新送审"
    return "已取消审核"


def on_rejection(rejection) -> None:
    record = {
        "at": _stamp(),
        "kind": "rejected",
        "code": rejection.code,
        "message": rejection.message,
    }
    _append_log(record)
    print("REJECTED " + json.dumps(record, ensure_ascii=False), flush=True)


def main() -> int:
    global _service

    load_from_file(CRED_FILE)

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    chat_id = os.environ.get("FEISHU_REVIEW_CHAT_ID", "")
    reviewer = os.environ.get("FEISHU_REVIEWER_OPEN_ID", "")
    workspace = os.environ.get("FEISHU_WORKSPACE_ID", "cyber-sloth")

    missing = [
        name
        for name, value in (
            ("FEISHU_APP_ID", app_id),
            ("FEISHU_APP_SECRET", app_secret),
            ("FEISHU_REVIEW_CHAT_ID", chat_id),
            ("FEISHU_REVIEWER_OPEN_ID", reviewer),
        )
        if not value
    ]
    if missing:
        print(f"缺少配置：{', '.join(missing)}", file=sys.stderr)
        return 2

    _service = ApprovalService(APPROVAL_ROOT, workspace, {reviewer})

    extra = {e.strip() for e in os.environ.get("FEISHU_EXTRA_EVENTS", "").split(",") if e.strip()}

    listener = FeishuCardListener(
        app_id=app_id,
        app_secret=app_secret,
        workspace_id=workspace,
        tenant_key=os.environ.get("FEISHU_TENANT_KEY") or None,
        allowed_chat_ids={chat_id},
        reviewer_allowlist={reviewer},
        on_decision=on_decision,
        on_rejection=on_rejection,
        extra_event_types=extra,
        on_raw=on_raw,
    )

    print(f"监听启动 app_id={app_id}", flush=True)
    print(f"  工作区 workspace={workspace}", flush=True)
    print(f"  状态存储 {APPROVAL_ROOT}", flush=True)
    print(f"  审核会话 chat_id={chat_id}", flush=True)
    print(f"  审核人 allowlist={reviewer}", flush=True)
    print(f"  组织校验 tenant_key={os.environ.get('FEISHU_TENANT_KEY') or '（未配置，跳过）'}", flush=True)
    if extra:
        print(f"  额外事件（兜底注册）={sorted(extra)}", flush=True)
    print("等待卡片按钮动作…", flush=True)

    try:
        listener.start()
    except KeyboardInterrupt:
        print("已停止", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"长连接异常：{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
