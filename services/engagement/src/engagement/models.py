"""互动分流的领域模型。

核心思想：不是「所有回复都送审」，而是先判风险再决定路由。
判定必须**可复现、可审计**——每条决定都要能回答「为什么走了这条路」。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# --- 风险等级 ---------------------------------------------------------------

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

# --- 路由 -------------------------------------------------------------------

#: 直接发（低风险，只留日志）
ROUTE_DIRECT = "direct"
#: 合并成批量卡片待确认
ROUTE_BATCH = "batch"
#: 单条卡片，立即人工决定
ROUTE_SINGLE = "single"
#: 拒绝自动处理，必须人工写
ROUTE_BLOCK = "block"

ROUTE_LABEL = {
    ROUTE_DIRECT: "直接发送",
    ROUTE_BATCH: "批量待确认",
    ROUTE_SINGLE: "单条待确认",
    ROUTE_BLOCK: "须人工处理",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ReplyCandidate:
    """一条待发出的评论回复。"""

    #: 平台事件/评论的唯一标识，用于幂等与审计
    event_id: str
    #: 评论区所在对象（动态 oid / 视频 BV）
    oid: str
    #: 被回复的评论 ID
    rpid: int
    #: 评论区类型：draw / dynamic / video / article
    comment_type: str
    #: 对方昵称与 UID（仅用于审计，不外发）
    author_name: str = ""
    author_mid: str = ""
    #: 对方的原评论内容
    source_text: str = ""
    #: 我们拟发出的回复内容
    reply_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Assessment:
    """一次风险判定。``rule`` 与 ``reason`` 是审计的关键。"""

    risk: str
    route: str
    rule: str
    reason: str

    @property
    def needs_human(self) -> bool:
        return self.route != ROUTE_DIRECT

    def describe(self) -> str:
        return (
            f"风险={self.risk} 路由={ROUTE_LABEL.get(self.route, self.route)} "
            f"规则={self.rule} 理由={self.reason}"
        )


@dataclass
class AuditRecord:
    """判定与结果的落盘记录。"""

    at: str
    event_id: str
    oid: str
    rpid: int
    comment_type: str
    author_name: str
    author_mid: str
    source_text: str
    reply_text: str
    risk: str
    route: str
    rule: str
    reason: str
    #: 实际执行结果：sent / held / blocked / failed
    outcome: str
    detail: str = ""
    platform_rpid: int | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def make_record(
    candidate: ReplyCandidate,
    assessment: Assessment,
    outcome: str,
    detail: str = "",
    platform_rpid: int | None = None,
) -> AuditRecord:
    return AuditRecord(
        at=now_utc(),
        event_id=candidate.event_id,
        oid=candidate.oid,
        rpid=candidate.rpid,
        comment_type=candidate.comment_type,
        author_name=candidate.author_name,
        author_mid=candidate.author_mid,
        source_text=candidate.source_text,
        reply_text=candidate.reply_text,
        risk=assessment.risk,
        route=assessment.route,
        rule=assessment.rule,
        reason=assessment.reason,
        outcome=outcome,
        detail=detail,
        platform_rpid=platform_rpid,
    )
