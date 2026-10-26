"""错误契约。

错误码取自 manual/specs/backend/approval-publishing.spec.md 的 BE-ERR-01。
只保留本服务会产生的那些。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApprovalError(Exception):
    """领域异常。``code`` 是稳定错误码，``hint`` 给人看下一步。"""

    code: str
    message: str
    hint: str = ""

    def __str__(self) -> str:
        base = f"[{self.code}] {self.message}"
        return f"{base}\n    → {self.hint}" if self.hint else base


# --- BE-ERR-01 用到的错误码 -------------------------------------------------

VALIDATION_ERROR = "VALIDATION_ERROR"
UNAUTHORIZED = "UNAUTHORIZED"
FORBIDDEN = "FORBIDDEN"
NOT_FOUND = "NOT_FOUND"
STALE_REVIEW = "STALE_REVIEW"
REVIEW_EXPIRED = "REVIEW_EXPIRED"
DECISION_ALREADY_TAKEN = "DECISION_ALREADY_TAKEN"
DRAFT_LOCKED = "DRAFT_LOCKED"
STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
ASSET_CHANGED = "ASSET_CHANGED"
APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
JOB_NOT_RESUMABLE = "JOB_NOT_RESUMABLE"
