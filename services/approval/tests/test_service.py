"""状态机的契约测试。

覆盖 BE-STATE-01、BE-IF-02、BE-RULE-01/02/04/05 的关键分支。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from approval import ApprovalError, ApprovalService
from approval.models import (
    DRAFT_APPROVED,
    DRAFT_CANCELED,
    DRAFT_EXPIRED,
    DRAFT_IN_REVIEW,
    DRAFT_REJECTED,
    JOB_QUEUED,
    REVIEW_APPROVED,
    REVIEW_CANCELED,
    REVIEW_EXPIRED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
)

REVIEWER = "ou_reviewer"
OTHER = "ou_stranger"
WS = "ws-1"

MANIFEST = {
    "title": "标题",
    "body": "正文",
    "images": ["a.png"],
    "account_id": "bilibili:383714514",
}


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, delta: timedelta) -> None:
        self.moment += delta


class Ctx:
    def __init__(self, operator: str = REVIEWER, workspace: str = WS) -> None:
        self.workspace_id = workspace
        self.operator_open_id = operator


class Dec:
    def __init__(self, review, action="approve", feedback=None, event="evt-1",
                 revision=None, digest=None) -> None:
        self.provider_event_id = event
        self.review_id = review.review_id
        self.expected_revision = review.revision if revision is None else revision
        self.content_digest = review.content_digest if digest is None else digest
        self.action = action
        self.feedback = feedback


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc))


@pytest.fixture
def svc(tmp_path: Path, clock: Clock) -> ApprovalService:
    return ApprovalService(tmp_path, WS, {REVIEWER}, clock=clock)


@pytest.fixture
def pending(svc: ApprovalService):
    draft = svc.create_draft(dict(MANIFEST))
    return svc.request_review(draft.draft_id, provider_message_id="om_1")


# ------------------------------------------------------------------ 草稿/送审

def test_create_draft_starts_at_revision_one(svc):
    draft = svc.create_draft(dict(MANIFEST))
    assert draft.revision == 1
    assert draft.status == "DRAFT"


def test_create_draft_requires_account(svc):
    with pytest.raises(ApprovalError) as exc:
        svc.create_draft({"title": "x"})
    assert exc.value.code == "VALIDATION_ERROR"


def test_request_review_sets_both_to_pending(svc):
    draft = svc.create_draft(dict(MANIFEST))
    review = svc.request_review(draft.draft_id, provider_message_id="om_1")
    assert review.status == REVIEW_PENDING
    assert review.delivery_status == "SENT"
    assert svc.get_draft(draft.draft_id).status == DRAFT_IN_REVIEW


def test_request_review_is_idempotent_per_version(svc):
    draft = svc.create_draft(dict(MANIFEST))
    first = svc.request_review(draft.draft_id)
    second = svc.request_review(draft.draft_id)
    assert first.review_id == second.review_id


def test_revise_bumps_revision_and_cancels_old_review(svc):
    draft = svc.create_draft(dict(MANIFEST))
    review = svc.request_review(draft.draft_id)
    revised = svc.revise_draft(draft.draft_id)
    assert revised.revision == 2
    assert svc.get_review(review.review_id).status == REVIEW_CANCELED


# ------------------------------------------------------------------ 批准

def test_approve_creates_exactly_one_queued_job(svc, pending):
    result = svc.apply_decision(Ctx(), Dec(pending, "approve"))
    assert result.applied is True
    assert result.review.status == REVIEW_APPROVED
    assert svc.get_draft(pending.draft_id).status == DRAFT_APPROVED
    assert result.publish_job is not None
    assert result.publish_job.status == JOB_QUEUED
    assert result.publish_job.target_account_id == MANIFEST["account_id"]
    assert len(svc.list_jobs()) == 1


def test_approve_sets_submit_deadline_one_hour(svc, pending, clock):
    result = svc.apply_decision(Ctx(), Dec(pending, "approve"))
    approved = datetime.fromisoformat(result.review.decided_at)
    deadline = datetime.fromisoformat(result.publish_job.submit_deadline_at)
    assert deadline - approved == timedelta(hours=1)


def test_approve_ignores_feedback(svc, pending):
    result = svc.apply_decision(Ctx(), Dec(pending, "approve", feedback="随手写的"))
    assert result.review.feedback is None


# ------------------------------------------------------------------ 退回/取消

def test_reject_records_feedback_and_no_job(svc, pending):
    result = svc.apply_decision(Ctx(), Dec(pending, "reject", feedback="标题太长"))
    assert result.review.status == REVIEW_REJECTED
    assert result.review.feedback == "标题太长"
    assert result.publish_job is None
    assert svc.get_draft(pending.draft_id).status == DRAFT_REJECTED
    assert svc.list_jobs() == []


def test_reject_without_feedback_is_null(svc, pending):
    result = svc.apply_decision(Ctx(), Dec(pending, "reject"))
    assert result.review.feedback is None


def test_overlong_feedback_rejected_not_truncated(svc, pending):
    with pytest.raises(ApprovalError) as exc:
        svc.apply_decision(Ctx(), Dec(pending, "reject", feedback="字" * 501))
    assert exc.value.code == "VALIDATION_ERROR"
    # 状态没变，可以重试
    assert svc.get_review(pending.review_id).status == REVIEW_PENDING


def test_cancel_has_no_job_and_no_feedback(svc, pending):
    result = svc.apply_decision(Ctx(), Dec(pending, "cancel", feedback="写了也没用"))
    assert result.review.status == REVIEW_CANCELED
    assert result.review.feedback is None
    assert result.publish_job is None
    assert svc.get_draft(pending.draft_id).status == DRAFT_CANCELED


# ------------------------------------------------------------------ 幂等/重复

def test_same_event_replay_is_not_applied_twice(svc, pending):
    first = svc.apply_decision(Ctx(), Dec(pending, "approve", event="evt-A"))
    second = svc.apply_decision(Ctx(), Dec(pending, "approve", event="evt-A"))
    assert first.applied is True
    assert second.applied is False
    assert len(svc.list_jobs()) == 1


def test_same_action_new_event_is_not_applied_again(svc, pending):
    svc.apply_decision(Ctx(), Dec(pending, "approve", event="evt-A"))
    again = svc.apply_decision(Ctx(), Dec(pending, "approve", event="evt-B"))
    assert again.applied is False
    assert len(svc.list_jobs()) == 1


def test_opposite_action_after_terminal_is_rejected(svc, pending):
    svc.apply_decision(Ctx(), Dec(pending, "approve", event="evt-A"))
    with pytest.raises(ApprovalError) as exc:
        svc.apply_decision(Ctx(), Dec(pending, "reject", event="evt-B"))
    assert exc.value.code == "DECISION_ALREADY_TAKEN"


def test_old_card_after_revision_is_stale(svc):
    draft = svc.create_draft(dict(MANIFEST))
    old = svc.request_review(draft.draft_id)
    svc.revise_draft(draft.draft_id)
    with pytest.raises(ApprovalError) as exc:
        svc.apply_decision(Ctx(), Dec(old, "approve"))
    assert exc.value.code == "DECISION_ALREADY_TAKEN"


# ------------------------------------------------------------------ 版本/来源

def test_wrong_revision_is_stale(svc, pending):
    with pytest.raises(ApprovalError) as exc:
        svc.apply_decision(Ctx(), Dec(pending, "approve", revision=99))
    assert exc.value.code == "STALE_REVIEW"


def test_wrong_digest_is_stale(svc, pending):
    with pytest.raises(ApprovalError) as exc:
        svc.apply_decision(Ctx(), Dec(pending, "approve", digest="deadbeef"))
    assert exc.value.code == "STALE_REVIEW"


def test_non_reviewer_is_forbidden(svc, pending):
    with pytest.raises(ApprovalError) as exc:
        svc.apply_decision(Ctx(operator=OTHER), Dec(pending, "approve"))
    assert exc.value.code == "FORBIDDEN"


def test_other_workspace_sees_not_found(svc, pending):
    with pytest.raises(ApprovalError) as exc:
        svc.apply_decision(Ctx(workspace="ws-other"), Dec(pending, "approve"))
    assert exc.value.code == "NOT_FOUND"


def test_unknown_review_is_not_found(svc):
    class Fake:
        review_id = "rv-missing"
        provider_event_id = "e"
        expected_revision = 1
        content_digest = "d"
        action = "approve"
        feedback = None

    with pytest.raises(ApprovalError) as exc:
        svc.apply_decision(Ctx(), Fake())
    assert exc.value.code == "NOT_FOUND"


# ------------------------------------------------------------------ 过期

def test_review_expires_at_boundary(svc, pending, clock):
    clock.advance(timedelta(seconds=86400))
    with pytest.raises(ApprovalError) as exc:
        svc.apply_decision(Ctx(), Dec(pending, "approve"))
    assert exc.value.code == "REVIEW_EXPIRED"
    assert svc.get_review(pending.review_id).status == REVIEW_EXPIRED
    assert svc.get_draft(pending.draft_id).status == DRAFT_EXPIRED


def test_review_valid_one_second_before_expiry(svc, pending, clock):
    clock.advance(timedelta(seconds=86399))
    result = svc.apply_decision(Ctx(), Dec(pending, "approve"))
    assert result.applied is True


def test_expired_review_rejects_later_approval(svc, pending, clock):
    clock.advance(timedelta(seconds=86401))
    with pytest.raises(ApprovalError):
        svc.apply_decision(Ctx(), Dec(pending, "approve", event="e1"))
    with pytest.raises(ApprovalError) as exc:
        svc.apply_decision(Ctx(), Dec(pending, "approve", event="e2"))
    assert exc.value.code == "DECISION_ALREADY_TAKEN"


# ------------------------------------------------------------------ 持久化

def test_state_survives_new_service_instance(tmp_path, clock, pending):
    svc = ApprovalService(tmp_path, WS, {REVIEWER}, clock=clock)
    result = svc.apply_decision(Ctx(), Dec(pending, "approve"))

    reopened = ApprovalService(tmp_path, WS, {REVIEWER}, clock=clock)
    assert reopened.get_review(pending.review_id).status == REVIEW_APPROVED
    assert len(reopened.list_jobs()) == 1
    assert reopened.list_jobs()[0].job_id == result.publish_job.job_id


def test_corrupt_store_is_storage_unavailable(tmp_path, clock):
    root = tmp_path
    (root / f"{WS}.json").write_text("{not json", encoding="utf-8")
    svc = ApprovalService(root, WS, {REVIEWER}, clock=clock)
    with pytest.raises(ApprovalError) as exc:
        svc.create_draft(dict(MANIFEST))
    assert exc.value.code == "STORAGE_UNAVAILABLE"


def test_revise_with_new_manifest_changes_digest(svc):
    draft = svc.create_draft(dict(MANIFEST))
    old_digest = draft.content_digest
    new_manifest = dict(MANIFEST, title="改过的标题")
    revised = svc.revise_draft(draft.draft_id, new_manifest)
    assert revised.revision == 2
    assert revised.content_digest != old_digest
    assert revised.manifest["title"] == "改过的标题"


def test_revise_approved_draft_is_locked(svc, pending):
    svc.apply_decision(Ctx(), Dec(pending, "approve"))
    with pytest.raises(ApprovalError) as exc:
        svc.revise_draft(pending.draft_id, dict(MANIFEST, title="想改"))
    assert exc.value.code == "DRAFT_LOCKED"


def test_mark_delivery_updates_message_id(svc, pending):
    updated = svc.mark_delivery(pending.review_id, "om_new", "SENT")
    assert updated.provider_message_id == "om_new"
    assert svc.get_review(pending.review_id).provider_message_id == "om_new"


# --------------------------------------------------------- 图片数量（契约 1–9）

def test_zero_images_is_rejected(svc):
    with pytest.raises(ApprovalError) as exc:
        svc.create_draft(dict(MANIFEST, images=[]))
    assert exc.value.code == "VALIDATION_ERROR"
    assert "1" in exc.value.message


def test_missing_images_is_rejected(svc):
    m = {k: v for k, v in MANIFEST.items() if k != "images"}
    with pytest.raises(ApprovalError) as exc:
        svc.create_draft(m)
    assert exc.value.code == "VALIDATION_ERROR"


def test_ten_images_is_rejected(svc):
    with pytest.raises(ApprovalError) as exc:
        svc.create_draft(dict(MANIFEST, images=[f"{i}.png" for i in range(10)]))
    assert exc.value.code == "VALIDATION_ERROR"
    assert "9" in exc.value.message


def test_nine_images_is_accepted(svc):
    draft = svc.create_draft(dict(MANIFEST, images=[f"{i}.png" for i in range(9)]))
    assert len(draft.manifest["images"]) == 9


def test_duplicate_images_is_rejected(svc):
    with pytest.raises(ApprovalError) as exc:
        svc.create_draft(dict(MANIFEST, images=["a.png", "a.png"]))
    assert exc.value.code == "VALIDATION_ERROR"


def test_revise_validates_new_manifest(svc):
    draft = svc.create_draft(dict(MANIFEST))
    with pytest.raises(ApprovalError) as exc:
        svc.revise_draft(draft.draft_id, dict(MANIFEST, images=["x.png"] * 10))
    assert exc.value.code == "VALIDATION_ERROR"


# ------------------------------------------------------------ execute_publish

from approval.models import PublishObservation  # noqa: E402


def approved_job(svc):
    draft = svc.create_draft(dict(MANIFEST))
    review = svc.request_review(draft.draft_id)
    result = svc.apply_decision(Ctx(), Dec(review, "approve"))
    return draft, review, result.publish_job


def test_execute_publish_success(svc):
    _, _, job = approved_job(svc)
    observed = PublishObservation(
        state="PUBLISHED", platform_item_id="1263392852390445065",
        platform_url="https://t.bilibili.com/1263392852390445065",
    )
    done = svc.execute_publish(job.job_id, lambda manifest: observed)
    assert done.status == "PUBLISHED"
    assert done.platform_item_id == "1263392852390445065"
    assert done.platform_url.startswith("https://")


def test_execute_publish_unknown_state_is_not_retried(svc):
    _, _, job = approved_job(svc)
    done = svc.execute_publish(
        job.job_id, lambda m: PublishObservation(state="RESULT_UNKNOWN", detail="超时")
    )
    assert done.status == "RESULT_UNKNOWN"
    assert done.last_error["code"] == "RESULT_UNKNOWN"
    # 再次执行应被拒绝，不允许自动重发
    with pytest.raises(ApprovalError) as exc:
        svc.execute_publish(job.job_id, lambda m: PublishObservation(state="PUBLISHED"))
    assert exc.value.code == "JOB_NOT_RESUMABLE"


def test_execute_publish_exception_becomes_unknown(svc):
    _, _, job = approved_job(svc)

    def boom(manifest):
        raise RuntimeError("网络断了")

    done = svc.execute_publish(job.job_id, boom)
    assert done.status == "RESULT_UNKNOWN"
    assert svc.list_jobs()[0].status == "RESULT_UNKNOWN"


def test_execute_publish_rejected_by_platform(svc):
    _, _, job = approved_job(svc)
    done = svc.execute_publish(
        job.job_id, lambda m: PublishObservation(state="REJECTED", detail="风控")
    )
    assert done.status == "FAILED"


def test_execute_publish_after_deadline_fails(svc, pending, clock):
    result = svc.apply_decision(Ctx(), Dec(pending, "approve"))
    job = result.publish_job
    clock.advance(timedelta(hours=2))
    with pytest.raises(ApprovalError) as exc:
        svc.execute_publish(job.job_id, lambda m: PublishObservation(state="PUBLISHED"))
    assert exc.value.code == "APPROVAL_EXPIRED"
    assert svc.list_jobs()[0].status == "FAILED"


def test_execute_publish_detects_content_change(svc):
    draft, _, job = approved_job(svc)
    # 绕过服务直接改存储里的 manifest，模拟内容被换掉
    data = svc.store.load()
    data["drafts"][draft.draft_id]["manifest"]["title"] = "偷偷改掉"
    svc.store.save(data)
    with pytest.raises(ApprovalError) as exc:
        svc.execute_publish(job.job_id, lambda m: PublishObservation(state="PUBLISHED"))
    assert exc.value.code == "ASSET_CHANGED"


def test_execute_publish_requires_queued(svc):
    _, _, job = approved_job(svc)
    svc.execute_publish(job.job_id, lambda m: PublishObservation(state="PUBLISHED"))
    with pytest.raises(ApprovalError) as exc:
        svc.execute_publish(job.job_id, lambda m: PublishObservation(state="PUBLISHED"))
    assert exc.value.code == "JOB_NOT_RESUMABLE"


def test_not_submitted_becomes_blocked_not_terminal(svc):
    _, _, job = approved_job(svc)
    done = svc.execute_publish(
        job.job_id, lambda m: PublishObservation(state="NOT_SUBMITTED", detail="本地限流")
    )
    assert done.status == "BLOCKED"


def test_blocked_job_can_resume_with_same_approval(svc):
    _, _, job = approved_job(svc)
    svc.execute_publish(job.job_id, lambda m: PublishObservation(state="NOT_SUBMITTED"))
    resumed = svc.resume_publish(job.job_id)
    assert resumed.status == "QUEUED"
    assert resumed.review_id == job.review_id
    done = svc.execute_publish(job.job_id, lambda m: PublishObservation(state="PUBLISHED"))
    assert done.status == "PUBLISHED"
    assert len(svc.list_jobs()) == 1


def test_result_unknown_cannot_resume(svc):
    _, _, job = approved_job(svc)
    svc.execute_publish(job.job_id, lambda m: PublishObservation(state="RESULT_UNKNOWN"))
    with pytest.raises(ApprovalError) as exc:
        svc.resume_publish(job.job_id)
    assert exc.value.code == "JOB_NOT_RESUMABLE"


def test_resume_after_deadline_expires(svc, clock):
    _, _, job = approved_job(svc)
    svc.execute_publish(job.job_id, lambda m: PublishObservation(state="NOT_SUBMITTED"))
    clock.advance(timedelta(hours=2))
    with pytest.raises(ApprovalError) as exc:
        svc.resume_publish(job.job_id)
    assert exc.value.code == "APPROVAL_EXPIRED"
