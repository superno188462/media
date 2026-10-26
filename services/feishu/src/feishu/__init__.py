"""内卷树懒飞书适配器。

只负责三件事：
1. 发送审核卡片（cards.py / sender.py）
2. 验证卡片动作来源并归一化为可信审核人上下文（events.py）
3. 通过长连接接收动作（listener.py）

**不负责**做决定，也不负责外发。那两件事属于受信入口
（applyDecision / executePublish），见 manual/specs/backend/approval-publishing.spec.md。
"""

from .cards import (
    ACTION_APPROVE,
    ACTION_CANCEL,
    ACTION_REJECT,
    ReviewDraftView,
    VideoInfo,
    build_review_card,
)
from .events import (
    DecisionRejection,
    ReviewDecision,
    VerifiedReviewerContext,
    normalize,
)
from .sender import DELIVERY_SENT, DELIVERY_UNKNOWN, DeliveryResult, FeishuReviewChannel, ReviewChannelError

__all__ = [
    "ReviewDraftView",
    "VideoInfo",
    "build_review_card",
    "ACTION_APPROVE",
    "ACTION_REJECT",
    "ACTION_CANCEL",
    "ReviewDecision",
    "VerifiedReviewerContext",
    "DecisionRejection",
    "normalize",
    "FeishuReviewChannel",
    "ReviewChannelError",
    "DeliveryResult",
    "DELIVERY_SENT",
    "DELIVERY_UNKNOWN",
]
