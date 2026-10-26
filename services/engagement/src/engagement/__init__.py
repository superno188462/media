"""内卷树懒互动分流。

对评论回复做**确定性风险判定**，按路由分发：
低风险直发、其余进入待确认。每次判定与执行都留可审计记录。

当前实现只覆盖 `direct` 路由的自动发送；`batch` / `single` / `block`
只记录「被拦下」，卡片通道尚未实现。
"""

from .audit import AuditLog
from .bili import BiliClient, SendResult
from .collect import (
    RawComment,
    Triaged,
    WatermarkStore,
    fetch_new,
    summarize,
    triage,
)
from .relevance import (
    PRIORITY,
    REPLY_RULES,
    REPLY_NO,
    REPLY_YES,
    SKIP_RULES,
    Relevance,
    describe_relevance_rules,
    should_reply,
)
from .models import (
    ROUTE_BATCH,
    ROUTE_BLOCK,
    ROUTE_DIRECT,
    ROUTE_LABEL,
    ROUTE_SINGLE,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    Assessment,
    AuditRecord,
    ReplyCandidate,
    make_record,
)
from .policy import MAX_DIRECT_LEN, RULES, SAFE_TEMPLATES, assess, describe_rules

__all__ = [
    "AuditLog",
    "BiliClient",
    "SendResult",
    "ReplyCandidate",
    "Assessment",
    "AuditRecord",
    "make_record",
    "assess",
    "describe_rules",
    "RULES",
    "SAFE_TEMPLATES",
    "MAX_DIRECT_LEN",
    "ROUTE_DIRECT",
    "ROUTE_BATCH",
    "ROUTE_SINGLE",
    "ROUTE_BLOCK",
    "ROUTE_LABEL",
    "RISK_LOW",
    "RISK_MEDIUM",
    "RISK_HIGH",
    # 第一层：该不该回
    "Relevance",
    "should_reply",
    "describe_relevance_rules",
    "SKIP_RULES",
    "REPLY_RULES",
    "PRIORITY",
    "REPLY_YES",
    "REPLY_NO",
    # 采集
    "RawComment",
    "Triaged",
    "WatermarkStore",
    "fetch_new",
    "triage",
    "summarize",
]
