"""领域模型。

字段与 manual/contracts/cyber-sloth.schema.json 的 ``Draft`` /
``ReviewRequest`` / ``PublishJob`` 对齐。这里是 Python 侧表示，
权威仍是共享 Schema。

不变量（BE-DATA-01）：
- 审核绑定的 workspace / draft / revision / digest 必须与草稿一致
- 只有 APPROVED 审核能关联发布任务
- 发布任务的账号必须等于 manifest 里的账号
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# --- 状态枚举 ---------------------------------------------------------------

DRAFT_DRAFT = "DRAFT"
DRAFT_IN_REVIEW = "IN_REVIEW"
DRAFT_APPROVED = "APPROVED"
DRAFT_REJECTED = "REJECTED"
DRAFT_CANCELED = "CANCELED"
DRAFT_EXPIRED = "EXPIRED"

REVIEW_PENDING = "PENDING"
REVIEW_APPROVED = "APPROVED"
REVIEW_REJECTED = "REJECTED"
REVIEW_CANCELED = "CANCELED"
REVIEW_EXPIRED = "EXPIRED"

JOB_QUEUED = "QUEUED"
JOB_PREPARING = "PREPARING"
JOB_SUBMITTING = "SUBMITTING"
JOB_SUBMITTED = "SUBMITTED"
JOB_PUBLISHED = "PUBLISHED"
JOB_BLOCKED = "BLOCKED"
JOB_FAILED = "FAILED"
JOB_RESULT_UNKNOWN = "RESULT_UNKNOWN"

REVIEW_TERMINAL = {REVIEW_APPROVED, REVIEW_REJECTED, REVIEW_CANCELED, REVIEW_EXPIRED}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_iso(text: str) -> datetime:
    return datetime.fromisoformat(text)


def compute_digest(manifest: dict) -> str:
    """manifest 的稳定摘要，绑定「审核的是哪一版内容」。"""
    material = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# --- 实体 -------------------------------------------------------------------


@dataclass
class Draft:
    workspace_id: str
    draft_id: str
    revision: int
    status: str
    manifest: dict
    content_digest: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Draft":
        return cls(**data)


@dataclass
class ReviewRequest:
    workspace_id: str
    review_id: str
    draft_id: str
    revision: int
    content_digest: str
    provider: str
    status: str
    delivery_status: str
    provider_message_id: str | None
    created_at: str
    expires_at: str
    decided_at: str | None = None
    reviewer_id: str | None = None
    feedback: str | None = None
    #: 已处理过的平台事件 ID，用于幂等重放（不属公共 Schema）。
    handled_events: list[str] = field(default_factory=list)
    #: 已产生的决定动作（"approve"/"reject"/"cancel"），用于判定相反动作。
    decided_action: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ReviewRequest":
        return cls(**data)


@dataclass
class PublishJob:
    workspace_id: str
    job_id: str
    review_id: str
    draft_id: str
    revision: int
    content_digest: str
    target_account_id: str
    status: str
    approved_at: str
    submit_deadline_at: str
    created_at: str
    updated_at: str
    platform_item_id: str | None = None
    platform_url: str | None = None
    last_error: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PublishJob":
        return cls(**data)


@dataclass
class DecisionResult:
    """apply_decision 的成功返回（对应 Schema 的 DecisionResult）。"""

    applied: bool
    review: ReviewRequest
    publish_job: PublishJob | None


@dataclass
class PublishObservation:
    """投稿适配器的可核对结果（对应 Schema 的 PublishObservation）。

    ``state`` 只允许这几个值，语义见 BE-STATE-02：

    - ``NOT_SUBMITTED``：明确没提交
    - ``SUBMITTED``：平台已受理，但未确认发布完成
    - ``PUBLISHED``：有充分证据已发布
    - ``RESULT_UNKNOWN``：**可能已受理**，无法确定；禁止再次提交
    - ``REJECTED``：平台明确拒绝
    """

    state: str
    platform_item_id: str | None = None
    platform_url: str | None = None
    detail: str = ""


OBSERVATION_STATES = {
    "NOT_SUBMITTED",
    "SUBMITTED",
    "PUBLISHED",
    "RESULT_UNKNOWN",
    "REJECTED",
}
