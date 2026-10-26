"""审核与发布任务状态机。

对应 manual/specs/backend/approval-publishing.spec.md 的 BE-IF-01 / BE-IF-02
与 BE-STATE-01。这里是应用服务层：**不依赖飞书或抖音 SDK**，
外部平台通过适配器转换后调用它。

关键不变量：
- 未经可信审核批准不得创建发布任务（BE-RULE-01）
- 一份有效审核只对应一个逻辑发布任务（BE-RULE-04）
- 决定已落盘才对外可见（BE-DATA-02）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from . import errors as E
from .models import (
    DRAFT_APPROVED,
    DRAFT_CANCELED,
    DRAFT_DRAFT,
    DRAFT_EXPIRED,
    DRAFT_IN_REVIEW,
    DRAFT_REJECTED,
    JOB_FAILED,
    JOB_BLOCKED,
    JOB_PREPARING,
    JOB_PUBLISHED,
    JOB_QUEUED,
    JOB_RESULT_UNKNOWN,
    JOB_SUBMITTED,
    JOB_SUBMITTING,
    OBSERVATION_STATES,
    REVIEW_APPROVED,
    REVIEW_CANCELED,
    REVIEW_EXPIRED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    REVIEW_TERMINAL,
    DecisionResult,
    Draft,
    PublishJob,
    PublishObservation,
    ReviewRequest,
    compute_digest,
    from_iso,
    now_utc,
    to_iso,
)
from .store import Store

#: BE-NFR-01：审核有效期与批准后的首次提交期限。
REVIEW_TTL = timedelta(seconds=86400)
SUBMIT_WINDOW = timedelta(hours=1)

#: 契约上限（ReviewDecision.feedback.maxLength）。
FEEDBACK_MAX_LEN = 500

#: 契约 PublicationManifest.assets 的 minItems / maxItems。
#: B 站动态同样限制最多 9 张图，两边一致。
MIN_IMAGES = 1
MAX_IMAGES = 9

ACTIONS = ("approve", "reject", "cancel")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ApprovalService:
    """单工作区的审核服务。"""

    def __init__(
        self,
        root: Path,
        workspace_id: str,
        reviewer_allowlist: set[str],
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self.workspace_id = workspace_id
        self.reviewers = set(reviewer_allowlist)
        self.clock = clock
        self.store = Store(root, workspace_id)

    def _now(self) -> datetime:
        return self.clock()

    # -------------------------------------------------------------- 草稿

    def _validate_manifest(self, manifest: dict) -> None:
        """契约级校验：账号必填；图文 1–9 张图，视频恰好 1 个文件。"""
        if not manifest.get("account_id"):
            raise E.ApprovalError(
                E.VALIDATION_ERROR,
                "manifest 缺少 account_id",
                hint="发布目标账号必须写进 manifest，批准后才能核对一致性。",
            )

        content_type = manifest.get("content_type", "image_text")

        if content_type == "video":
            # 视频分支：必须有文件，且不能混入图片列表（契约里 assets 恰好 1 项）。
            video = manifest.get("video")
            if not isinstance(video, str) or not video:
                raise E.ApprovalError(
                    E.VALIDATION_ERROR,
                    "视频类型必须提供 video 文件路径",
                    hint="manifest.video 指向 mp4；render_video.py 的输出即可。",
                )
            if not Path(video).is_file():
                raise E.ApprovalError(
                    E.VALIDATION_ERROR,
                    f"视频文件不存在：{video}",
                    hint="先渲染出 mp4 再送审。",
                )
            if manifest.get("images"):
                raise E.ApprovalError(
                    E.VALIDATION_ERROR,
                    "视频类型不应同时带 images",
                    hint="契约规定视频的 assets 恰好 1 项。",
                )
            return

        if content_type != "image_text":
            raise E.ApprovalError(
                E.VALIDATION_ERROR,
                f"未知 content_type：{content_type}",
                hint="只接受 image_text 或 video（见 CHANGE-002）。",
            )

        images = manifest.get("images")
        if images is None:
            raise E.ApprovalError(
                E.VALIDATION_ERROR,
                "manifest 缺少 images",
                hint="契约要求至少 1 张图（assets.minItems=1）。",
            )
        if not isinstance(images, list):
            raise E.ApprovalError(E.VALIDATION_ERROR, "images 必须是数组")
        if not MIN_IMAGES <= len(images) <= MAX_IMAGES:
            raise E.ApprovalError(
                E.VALIDATION_ERROR,
                f"图片数量 {len(images)} 张，契约要求 {MIN_IMAGES}–{MAX_IMAGES} 张",
                hint="B 站动态同样最多 9 张；纯文字动态不在首期契约内。",
            )
        if len(set(images)) != len(images):
            raise E.ApprovalError(
                E.VALIDATION_ERROR,
                "图片有重复项",
                hint="契约要求同一素材不可重复出现。",
            )

    def create_draft(self, manifest: dict) -> Draft:
        """建立第一版草稿。不送审、不通知。"""
        if not isinstance(manifest, dict) or not manifest:
            raise E.ApprovalError(E.VALIDATION_ERROR, "manifest 不能为空")
        self._validate_manifest(manifest)

        now = to_iso(self._now())
        draft = Draft(
            workspace_id=self.workspace_id,
            draft_id=_new_id("draft"),
            revision=1,
            status=DRAFT_DRAFT,
            manifest=manifest,
            content_digest=compute_digest(manifest),
            created_at=now,
            updated_at=now,
        )
        data = self.store.load()
        data["drafts"][draft.draft_id] = draft.to_dict()
        self.store.save(data)
        return draft

    def revise_draft(self, draft_id: str, manifest: dict | None = None) -> Draft:
        """建立下一版草稿；已批准的版本不可改（DRAFT_LOCKED）。

        ``manifest`` 给定时替换内容并重算摘要；否则沿用原内容（仅升版本）。
        """
        data = self.store.load()
        raw = data["drafts"].get(draft_id)
        if raw is None:
            raise E.ApprovalError(E.NOT_FOUND, f"草稿不存在：{draft_id}")

        draft = Draft.from_dict(raw)
        if draft.status == DRAFT_APPROVED:
            raise E.ApprovalError(
                E.DRAFT_LOCKED,
                "该版本已批准，不能改稿",
                hint="如需不同内容，另建草稿并重新送审。",
            )

        if manifest is not None:
            self._validate_manifest(manifest)
            draft.manifest = manifest

        # 旧版本还在待审时，先把它作废（旧卡片随后点击会得到 STALE_REVIEW）。
        for review_raw in data["reviews"].values():
            if review_raw.get("draft_id") == draft_id and review_raw.get("status") == REVIEW_PENDING:
                review_raw["status"] = REVIEW_CANCELED
                review_raw["decided_at"] = to_iso(self._now())
                review_raw["decided_action"] = "cancel"

        now = to_iso(self._now())
        draft.revision += 1
        draft.status = DRAFT_DRAFT
        draft.content_digest = compute_digest(draft.manifest)
        draft.updated_at = now
        data["drafts"][draft_id] = draft.to_dict()
        self.store.save(data)
        return draft

    # -------------------------------------------------------------- 送审

    def request_review(
        self,
        draft_id: str,
        provider_message_id: str | None = None,
        review_id: str | None = None,
    ) -> ReviewRequest:
        """把当前版本置为待审，建立 PENDING 审核。"""
        data = self.store.load()
        raw = data["drafts"].get(draft_id)
        if raw is None:
            raise E.ApprovalError(E.NOT_FOUND, f"草稿不存在：{draft_id}")
        draft = Draft.from_dict(raw)

        if draft.status == DRAFT_APPROVED:
            raise E.ApprovalError(E.DRAFT_LOCKED, "已批准的版本不能重新送审")

        # 同版本重复送审：返回已有审核，不产生第二个逻辑审核（BE-STATE-01）。
        for review in self.store.reviews(data).values():
            if (
                review.draft_id == draft_id
                and review.revision == draft.revision
                and review.status in (REVIEW_PENDING, REVIEW_APPROVED)
            ):
                return review

        now = self._now()
        review = ReviewRequest(
            workspace_id=self.workspace_id,
            review_id=review_id or _new_id("rv"),
            draft_id=draft_id,
            revision=draft.revision,
            content_digest=draft.content_digest,
            provider="feishu",
            status=REVIEW_PENDING,
            delivery_status="SENT" if provider_message_id else "QUEUED",
            provider_message_id=provider_message_id,
            created_at=to_iso(now),
            expires_at=to_iso(now + REVIEW_TTL),
        )
        draft.status = DRAFT_IN_REVIEW
        draft.updated_at = to_iso(now)

        data["reviews"][review.review_id] = review.to_dict()
        data["drafts"][draft_id] = draft.to_dict()
        self.store.save(data)
        return review

    # -------------------------------------------------------------- 决定

    def apply_decision(self, context, decision) -> DecisionResult:
        """应用一个**已验证来源**的审核决定。

        ``context`` 需有 ``workspace_id`` / ``operator_open_id``；
        ``decision`` 需有 ``provider_event_id`` / ``review_id`` /
        ``expected_revision`` / ``content_digest`` / ``action`` / ``feedback``。
        两者都由适配器从平台事件构造，不接受模型自报身份。
        """
        if decision.action not in ACTIONS:
            raise E.ApprovalError(E.VALIDATION_ERROR, f"未知动作：{decision.action}")

        data = self.store.load()
        raw = data["reviews"].get(decision.review_id)
        if raw is None:
            raise E.ApprovalError(E.NOT_FOUND, f"审核不存在：{decision.review_id}")

        review = ReviewRequest.from_dict(raw)
        if review.workspace_id != context.workspace_id:
            # 不暴露其他工作区的存在。
            raise E.ApprovalError(E.NOT_FOUND, f"审核不存在：{decision.review_id}")

        if context.operator_open_id not in self.reviewers:
            raise E.ApprovalError(
                E.FORBIDDEN, "操作者不在审核人白名单", hint="只有授权审核人能批准或退回。"
            )

        # --- 幂等：同一平台事件重放，返回既有结果 ---
        if decision.provider_event_id in review.handled_events:
            return DecisionResult(
                applied=False,
                review=review,
                publish_job=self._job_for(data, review.review_id),
            )

        # --- 终态：重复相同决定返回既有；相反决定拒绝 ---
        if review.status in REVIEW_TERMINAL:
            if review.decided_action == decision.action:
                return DecisionResult(
                    applied=False,
                    review=review,
                    publish_job=self._job_for(data, review.review_id),
                )
            raise E.ApprovalError(
                E.DECISION_ALREADY_TAKEN,
                f"该审核已是终态（{review.status}），不能再做 {decision.action}",
                hint="如需不同结果，另建版本重新送审。",
            )

        if review.status != REVIEW_PENDING:
            raise E.ApprovalError(E.STALE_REVIEW, f"审核状态不是待审：{review.status}")

        # --- 版本与摘要绑定 ---
        if (
            int(decision.expected_revision) != review.revision
            or decision.content_digest != review.content_digest
        ):
            raise E.ApprovalError(
                E.STALE_REVIEW,
                "卡片绑定的版本或摘要与当前审核不符",
                hint="使用当前版本的卡片；旧卡片已失效。",
            )

        # --- 过期（边界 now >= expires_at） ---
        now = self._now()
        if now >= from_iso(review.expires_at):
            review.status = REVIEW_EXPIRED
            review.decided_at = to_iso(now)
            draft = Draft.from_dict(data["drafts"][review.draft_id])
            draft.status = DRAFT_EXPIRED
            draft.updated_at = to_iso(now)
            data["reviews"][review.review_id] = review.to_dict()
            data["drafts"][draft.draft_id] = draft.to_dict()
            self.store.save(data)
            raise E.ApprovalError(
                E.REVIEW_EXPIRED,
                "审核已过期",
                hint="重新建版本送审。",
            )

        # --- 退回意见 ---
        feedback: str | None = None
        if decision.action == "reject":
            raw_feedback = getattr(decision, "feedback", None)
            if isinstance(raw_feedback, str) and raw_feedback.strip():
                text = raw_feedback.strip()
                if len(text) > FEEDBACK_MAX_LEN:
                    raise E.ApprovalError(
                        E.VALIDATION_ERROR,
                        f"退回意见过长：{len(text)} 字，上限 {FEEDBACK_MAX_LEN} 字",
                        hint="按契约不静默截断。",
                    )
                feedback = text

        # --- 落状态 ---
        stamp = to_iso(now)
        draft = Draft.from_dict(data["drafts"][review.draft_id])
        review.decided_at = stamp
        review.reviewer_id = context.operator_open_id
        review.decided_action = decision.action
        review.feedback = feedback
        review.handled_events.append(decision.provider_event_id)

        job: PublishJob | None = None
        if decision.action == "approve":
            review.status = REVIEW_APPROVED
            draft.status = DRAFT_APPROVED
            job = PublishJob(
                workspace_id=self.workspace_id,
                job_id=_new_id("job"),
                review_id=review.review_id,
                draft_id=draft.draft_id,
                revision=draft.revision,
                content_digest=draft.content_digest,
                target_account_id=draft.manifest["account_id"],
                status=JOB_QUEUED,
                approved_at=stamp,
                submit_deadline_at=to_iso(now + SUBMIT_WINDOW),
                created_at=stamp,
                updated_at=stamp,
            )
            data["jobs"][job.job_id] = job.to_dict()
        elif decision.action == "reject":
            review.status = REVIEW_REJECTED
            draft.status = DRAFT_REJECTED
        else:  # cancel
            review.status = REVIEW_CANCELED
            draft.status = DRAFT_CANCELED

        draft.updated_at = stamp
        data["reviews"][review.review_id] = review.to_dict()
        data["drafts"][draft.draft_id] = draft.to_dict()
        self.store.save(data)

        return DecisionResult(applied=True, review=review, publish_job=job)

    # -------------------------------------------------------------- 执行发布

    def execute_publish(self, job_id: str, publisher) -> PublishJob:
        """执行一个 QUEUED 发布任务。

        ``publisher`` 是 ``Callable[[dict], PublishObservation]``，接收 manifest，
        返回可核对结果。**只有受信执行器可以调用本方法**（BE-IF-03），
        不通过任何模型可见工具直接授予权限。

        顺序严格按 BE-STATE-02：``SUBMITTING`` 必须先落盘，才允许调用平台。
        """
        data = self.store.load()
        raw = data["jobs"].get(job_id)
        if raw is None:
            raise E.ApprovalError(E.NOT_FOUND, f"发布任务不存在：{job_id}")
        job = PublishJob.from_dict(raw)

        if job.status != JOB_QUEUED:
            raise E.ApprovalError(
                E.JOB_NOT_RESUMABLE,
                f"任务状态是 {job.status}，只有 QUEUED 能执行",
                hint="BLOCKED 需要显式 resume；终态不能重跑。",
            )

        now = self._now()

        # 批准后首次提交有时限（BE-NFR-01）。
        if now >= from_iso(job.submit_deadline_at):
            job.status = JOB_FAILED
            job.updated_at = to_iso(now)
            job.last_error = {"code": E.APPROVAL_EXPIRED, "message": "已超过提交期限"}
            data["jobs"][job_id] = job.to_dict()
            self.store.save(data)
            raise E.ApprovalError(
                E.APPROVAL_EXPIRED,
                "已超过批准后的提交期限",
                hint="需重新送审获得新的批准。",
            )

        draft_raw = data["drafts"].get(job.draft_id)
        if draft_raw is None:
            raise E.ApprovalError(E.NOT_FOUND, f"草稿不存在：{job.draft_id}")
        draft = Draft.from_dict(draft_raw)

        # 发布前必须核对内容没被换掉（BE-RULE-07 原样发布）。
        if compute_digest(draft.manifest) != job.content_digest:
            job.status = JOB_FAILED
            job.updated_at = to_iso(now)
            job.last_error = {"code": E.ASSET_CHANGED, "message": "草稿内容与批准版本不一致"}
            data["jobs"][job_id] = job.to_dict()
            self.store.save(data)
            raise E.ApprovalError(
                E.ASSET_CHANGED,
                "草稿内容已变化，与批准时的摘要不符",
                hint="重新送审；不能发布未经审核的内容。",
            )

        # PREPARING
        job.status = JOB_PREPARING
        job.updated_at = to_iso(now)
        data["jobs"][job_id] = job.to_dict()
        self.store.save(data)

        # SUBMITTING 必须先落盘，之后才允许真正提交。
        job.status = JOB_SUBMITTING
        job.updated_at = to_iso(self._now())
        data["jobs"][job_id] = job.to_dict()
        self.store.save(data)

        try:
            observation = publisher(draft.manifest)
        except Exception as exc:  # noqa: BLE001
            # 提交后异常：是否被受理未知，按 RESULT_UNKNOWN 处理，禁止自动重试。
            observation = PublishObservation(
                state="RESULT_UNKNOWN",
                detail=f"提交过程异常：{type(exc).__name__}: {exc}",
            )

        if observation.state not in OBSERVATION_STATES:
            observation = PublishObservation(
                state="RESULT_UNKNOWN",
                detail=f"适配器返回非法状态：{observation.state}",
            )

        mapping = {
            "PUBLISHED": JOB_PUBLISHED,
            "SUBMITTED": JOB_SUBMITTED,
            "RESULT_UNKNOWN": JOB_RESULT_UNKNOWN,
            "REJECTED": JOB_FAILED,
            # 明确未提交且可恢复 → BLOCKED，而不是终态 FAILED（BE-STATE-02）。
            # 这样本地限流、缺图之类的问题不会白白消耗一次批准。
            "NOT_SUBMITTED": JOB_BLOCKED,
        }
        job.status = mapping[observation.state]
        job.platform_item_id = observation.platform_item_id
        job.platform_url = observation.platform_url
        job.updated_at = to_iso(self._now())
        if observation.state in ("REJECTED", "NOT_SUBMITTED"):
            job.last_error = {"code": "PUBLISH_FAILED", "message": observation.detail}
        elif observation.state == "RESULT_UNKNOWN":
            job.last_error = {"code": "RESULT_UNKNOWN", "message": observation.detail}
        else:
            job.last_error = None

        data["jobs"][job_id] = job.to_dict()
        self.store.save(data)
        return job

    def resume_publish(self, job_id: str) -> PublishJob:
        """把安全的 BLOCKED 任务放回 QUEUED，沿用同一次批准（BE-STATE-02）。

        只有 BLOCKED 可恢复：它表示「已证明未提交」。``RESULT_UNKNOWN``
        绝不能走这里——那可能已经被平台受理。
        """
        data = self.store.load()
        raw = data["jobs"].get(job_id)
        if raw is None:
            raise E.ApprovalError(E.NOT_FOUND, f"发布任务不存在：{job_id}")
        job = PublishJob.from_dict(raw)

        if job.status != JOB_BLOCKED:
            raise E.ApprovalError(
                E.JOB_NOT_RESUMABLE,
                f"任务状态是 {job.status}，只有 BLOCKED 能恢复",
                hint="RESULT_UNKNOWN 与终态都不能重发。",
            )

        now = self._now()
        if now >= from_iso(job.submit_deadline_at):
            job.status = JOB_FAILED
            job.updated_at = to_iso(now)
            job.last_error = {"code": E.APPROVAL_EXPIRED, "message": "已超过提交期限"}
            data["jobs"][job_id] = job.to_dict()
            self.store.save(data)
            raise E.ApprovalError(E.APPROVAL_EXPIRED, "已超过提交期限，需重新送审")

        job.status = JOB_QUEUED
        job.updated_at = to_iso(now)
        job.last_error = None
        data["jobs"][job_id] = job.to_dict()
        self.store.save(data)
        return job

    # -------------------------------------------------------------- 查询

    def mark_delivery(
        self, review_id: str, provider_message_id: str | None, delivery_status: str = "SENT"
    ) -> ReviewRequest:
        """发送完成后回填卡片消息 ID 与投递状态。"""
        data = self.store.load()
        raw = data["reviews"].get(review_id)
        if raw is None:
            raise E.ApprovalError(E.NOT_FOUND, f"审核不存在：{review_id}")
        review = ReviewRequest.from_dict(raw)
        review.provider_message_id = provider_message_id
        review.delivery_status = delivery_status
        data["reviews"][review_id] = review.to_dict()
        self.store.save(data)
        return review

    def get_draft(self, draft_id: str) -> Draft:
        data = self.store.load()
        raw = data["drafts"].get(draft_id)
        if raw is None:
            raise E.ApprovalError(E.NOT_FOUND, f"草稿不存在：{draft_id}")
        return Draft.from_dict(raw)

    def get_review(self, review_id: str) -> ReviewRequest:
        data = self.store.load()
        raw = data["reviews"].get(review_id)
        if raw is None:
            raise E.ApprovalError(E.NOT_FOUND, f"审核不存在：{review_id}")
        return ReviewRequest.from_dict(raw)

    def list_jobs(self) -> list[PublishJob]:
        return list(self.store.jobs(self.store.load()).values())

    @staticmethod
    def _job_for(data: dict, review_id: str) -> PublishJob | None:
        for raw in data["jobs"].values():
            if raw.get("review_id") == review_id:
                return PublishJob.from_dict(raw)
        return None
