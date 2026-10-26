"""风险判定策略的契约测试。

规则必须是确定性的：同一输入永远同一结论，审计才能复现。
"""

from __future__ import annotations

import pytest

from engagement.models import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    ROUTE_BATCH,
    ROUTE_BLOCK,
    ROUTE_DIRECT,
    ROUTE_SINGLE,
    ReplyCandidate,
)
from engagement.policy import MAX_DIRECT_LEN, assess


def cand(reply: str, **kw) -> ReplyCandidate:
    return ReplyCandidate(
        event_id="evt-1",
        oid="413402056",
        rpid=318247075745,
        comment_type="draw",
        reply_text=reply,
        **kw,
    )


# ------------------------------------------------------------------ 直发

def test_thanks_goes_direct():
    a = assess(cand("谢谢支持！"))
    assert a.route == ROUTE_DIRECT
    assert a.risk == RISK_LOW
    assert a.rule.startswith("template:")


def test_ack_fixed_goes_direct():
    a = assess(cand("这个问题已修复，见新的那条。"))
    assert a.route == ROUTE_DIRECT


def test_confirmation_goes_direct():
    # 今天真实发的那条：技术澄清
    a = assess(cand(
        "谢谢记录。根因确认了：多行正文走命令行传参时，换行被当成命令分隔符，"
        "只执行了第一行，后半段文字和 --image 参数一起被丢弃。"
    ))
    assert a.route == ROUTE_DIRECT


def test_short_factual_agreement_goes_direct():
    a = assess(cand("是的，就是这个问题。"))
    assert a.route == ROUTE_DIRECT


# ------------------------------------------------------------------ 高风险

def test_link_goes_single():
    a = assess(cand("详情看这里 https://example.com/x"))
    assert a.route == ROUTE_SINGLE
    assert a.risk == RISK_HIGH
    assert a.rule == "contact_or_link"


def test_wechat_invite_goes_single():
    a = assess(cand("加我微信聊"))
    assert a.route == ROUTE_SINGLE


def test_commitment_goes_single():
    a = assess(cand("下周就上线这个功能"))
    assert a.route == ROUTE_SINGLE
    assert a.rule == "commitment"


def test_money_promise_goes_single():
    a = assess(cand("保证退款"))
    assert a.route == ROUTE_SINGLE


def test_controversy_goes_single():
    a = assess(cand("你这是割韭菜吧"))
    assert a.route == ROUTE_SINGLE
    assert a.rule == "controversy"


def test_privacy_goes_single():
    a = assess(cand("把手机号发我"))
    assert a.route == ROUTE_SINGLE
    assert a.rule == "privacy"


def test_risk_beats_template():
    """含风险词时，即使命中模板也必须升级——安全模板不能洗白风险。"""
    a = assess(cand("谢谢，我们保证下周上线"))
    assert a.route == ROUTE_SINGLE
    assert a.risk == RISK_HIGH


# ------------------------------------------------------------------ 中风险

def test_stance_goes_batch():
    a = assess(cand("我们会认真处理这个反馈"))
    assert a.route == ROUTE_BATCH
    assert a.risk == RISK_MEDIUM
    assert a.rule == "stance"


def test_numbers_go_batch():
    a = assess(cand("这个功能大概需要 3 天"))
    assert a.route == ROUTE_BATCH
    assert a.rule in ("commitment", "money_or_number")


def test_unmatched_goes_batch_by_default():
    a = assess(cand("今天天气不错啊哈哈哈"))
    assert a.route == ROUTE_BATCH
    assert a.rule == "unmatched_default"


# ------------------------------------------------------------------ 拦截

def test_empty_reply_is_blocked():
    a = assess(cand("   "))
    assert a.route == ROUTE_BLOCK


def test_template_but_too_long_goes_batch():
    long_reply = "谢谢支持。" + "补充说明。" * 60
    assert len(long_reply) > MAX_DIRECT_LEN
    a = assess(cand(long_reply))
    assert a.route == ROUTE_BATCH
    assert a.rule == "template_too_long"


# ------------------------------------------------------------------ 性质

@pytest.mark.parametrize(
    "text",
    ["谢谢", "我们会处理", "加我微信", "下周上线", "", "随便说点什么"],
)
def test_assessment_is_deterministic(text):
    first = assess(cand(text))
    second = assess(cand(text))
    assert (first.risk, first.route, first.rule) == (second.risk, second.route, second.rule)


def test_needs_human_flag_matches_route():
    assert assess(cand("谢谢")).needs_human is False
    assert assess(cand("加我微信")).needs_human is True
    assert assess(cand("")).needs_human is True  # block 也需要人
