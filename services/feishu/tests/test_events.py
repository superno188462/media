"""来源验证与归一化的契约测试（对应 CT-06）。

这些断言锁住 BE-IF-02 与 BE-RULE-08：
伪签名/错组织/错消息/非审核人 一律不建立授权。
"""

from __future__ import annotations

import pytest

from feishu.events import normalize

TENANT = "tenant_ok"
CHAT = "oc_review_chat"
REVIEWER = "ou_reviewer"
WS = "ws-1"


def payload(
    *,
    open_id: str = REVIEWER,
    tenant_key: str = TENANT,
    chat_id: str = CHAT,
    message_id: str = "om_msg",
    action: str = "approve",
    review_id: str = "rev-1",
    revision: str = "2",
    digest: str = "abc123",
    with_operator: bool = True,
) -> dict:
    data = {
        "action": {
            "value": {
                "action": action,
                "review_id": review_id,
                "revision": revision,
                "content_digest": digest,
            }
        },
        "context": {
            "open_message_id": message_id,
            "open_chat_id": chat_id,
            "preview_token": "pv",
        },
    }
    if with_operator:
        data["operator"] = {
            "tenant_key": tenant_key,
            "user_id": "u-1",
            "open_id": open_id,
        }
    return data


def run(p: dict, **overrides):
    kwargs = {
        "workspace_id": WS,
        "expected_tenant_key": TENANT,
        "allowed_chat_ids": {CHAT},
        "reviewer_allowlist": {REVIEWER},
        "provider_event_id": "evt-1",
    }
    kwargs.update(overrides)
    return normalize(p, **kwargs)


# ------------------------------------------------------------------ 正常路径

def test_valid_approval_is_normalized():
    ctx, decision, rejection = run(payload())
    assert rejection is None
    assert ctx is not None and decision is not None
    assert ctx.operator_open_id == REVIEWER
    assert ctx.tenant_key == TENANT
    assert ctx.open_chat_id == CHAT
    assert decision.action == "approve"
    assert decision.review_id == "rev-1"
    assert decision.expected_revision == 2
    assert decision.content_digest == "abc123"


def test_reject_action_is_recognized():
    _, decision, rejection = run(payload(action="reject"))
    assert rejection is None
    assert decision.action == "reject"


def test_cancel_action_is_recognized():
    _, decision, rejection = run(payload(action="cancel"))
    assert rejection is None
    assert decision.action == "cancel"


# ------------------------------------------------------------------ 来源验证

def test_missing_operator_is_unauthorized():
    _, _, rejection = run(payload(with_operator=False))
    assert rejection.code == "UNAUTHORIZED"


def test_wrong_tenant_is_unauthorized():
    _, _, rejection = run(payload(tenant_key="tenant_other"))
    assert rejection.code == "UNAUTHORIZED"


def test_wrong_chat_is_forbidden():
    _, _, rejection = run(payload(chat_id="oc_somewhere_else"))
    assert rejection.code == "FORBIDDEN"


def test_non_reviewer_is_forbidden():
    _, _, rejection = run(payload(open_id="ou_stranger"))
    assert rejection.code == "FORBIDDEN"


def test_unknown_action_is_unauthorized():
    _, _, rejection = run(payload(action="delete_everything"))
    assert rejection.code == "UNAUTHORIZED"


def test_missing_review_id_is_stale_review():
    _, _, rejection = run(payload(review_id=""))
    assert rejection.code == "STALE_REVIEW"


def test_bad_revision_is_stale_review():
    _, _, rejection = run(payload(revision="not-a-number"))
    assert rejection.code == "STALE_REVIEW"


def test_missing_digest_is_stale_review():
    _, _, rejection = run(payload(digest=""))
    assert rejection.code == "STALE_REVIEW"


def test_tenant_check_skipped_when_not_configured():
    """未配置组织时不做组织比对，但审核人白名单仍生效。"""
    _, _, rejection = run(payload(tenant_key="other"), expected_tenant_key=None)
    assert rejection is None
    _, _, rejection2 = run(payload(open_id="ou_x"), expected_tenant_key=None)
    assert rejection2.code == "FORBIDDEN"


def test_rejection_carries_no_trusted_context():
    ctx, decision, rejection = run(payload(open_id="ou_stranger"))
    assert ctx is None
    assert decision is None
    assert rejection is not None


# ------------------------------------------------------- 退回意见 feedback

def with_feedback(text: str | None, *, action: str = "reject", from_input: bool = False) -> dict:
    p = payload(action=action)
    if text is not None:
        if from_input:
            p["action"]["input_value"] = text
        else:
            p["action"]["form_value"] = {"feedback": text}
    return p


def test_reject_with_feedback_is_captured():
    _, decision, rejection = run(with_feedback("标题太长，改短一点"))
    assert rejection is None
    assert decision.action == "reject"
    assert decision.feedback == "标题太长，改短一点"


def test_reject_without_feedback_is_null():
    _, decision, rejection = run(with_feedback(None))
    assert rejection is None
    assert decision.feedback is None


def test_reject_with_blank_feedback_is_null():
    _, decision, _ = run(with_feedback("   \n  "))
    assert decision.feedback is None


def test_feedback_is_trimmed():
    _, decision, _ = run(with_feedback("  改短一点  "))
    assert decision.feedback == "改短一点"


def test_feedback_from_standalone_input():
    _, decision, rejection = run(with_feedback("用 input_value 传的", from_input=True))
    assert rejection is None
    assert decision.feedback == "用 input_value 传的"


def test_form_value_wins_over_input_value():
    p = with_feedback("来自表单")
    p["action"]["input_value"] = "来自单输入框"
    _, decision, _ = run(p)
    assert decision.feedback == "来自表单"


def test_approve_ignores_feedback():
    """契约：批准与取消的 feedback 必须为 null。"""
    _, decision, _ = run(with_feedback("顺手写了点字", action="approve"))
    assert decision.action == "approve"
    assert decision.feedback is None


def test_cancel_ignores_feedback():
    _, decision, _ = run(with_feedback("也写了点字", action="cancel"))
    assert decision.feedback is None


def test_overlong_feedback_is_rejected_not_truncated():
    _, decision, rejection = run(with_feedback("字" * 501))
    assert decision is None
    assert rejection.code == "VALIDATION_ERROR"


def test_feedback_at_limit_is_accepted():
    _, decision, rejection = run(with_feedback("字" * 500))
    assert rejection is None
    assert decision.feedback is not None
    assert len(decision.feedback) == 500
