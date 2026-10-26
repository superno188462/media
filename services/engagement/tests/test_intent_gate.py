"""意图识别与门禁的测试（用假模型，不联网）。"""

from __future__ import annotations

import pytest

from engagement.gate import (
    DECISION_APPROVE,
    DECISION_DENY,
    DECISION_ESCALATE,
    check,
)
from engagement.intent import classify
from engagement.llm import LlmError


class FakeLlm:
    """按预设返回，并记录被调用的次数。"""

    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload or {}
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def chat_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return self.payload


# ============================================================ 意图识别

def test_obvious_spam_skips_llm():
    """明显的垃圾不花模型的钱。"""
    llm = FakeLlm({"should_reply": True, "category": "question"})
    intent = classify("加我微信领资料", llm)
    assert intent.should_reply is False
    assert intent.source == "regex"
    assert llm.calls == []


def test_emoji_only_skips_llm():
    llm = FakeLlm({"should_reply": True})
    intent = classify("[笑哭][笑哭]", llm)
    assert intent.should_reply is False
    assert llm.calls == []


def test_llm_decides_ambiguous_comment():
    llm = FakeLlm(
        {"should_reply": True, "category": "technical", "priority": 6,
         "reason": "描述了具体的技术机制"}
    )
    intent = classify("我在测自动化发布链路，换行被当成命令分隔符", llm)
    assert intent.should_reply is True
    assert intent.category == "technical"
    assert intent.source == "llm"
    assert len(llm.calls) == 1


def test_llm_can_reject_what_regex_would_accept():
    """正则可能把某句话当提问，但模型判断不值得回。"""
    llm = FakeLlm(
        {"should_reply": False, "category": "unclear", "reason": "只是随口一问，无信息需求"}
    )
    intent = classify("这个怎么弄？", llm)
    assert intent.should_reply is False
    assert intent.source == "llm"


def test_llm_failure_falls_back_to_regex_and_is_marked():
    llm = FakeLlm(error=LlmError("boom"))
    intent = classify("这个怎么做的？", llm)
    assert intent.source == "regex-fallback"
    assert intent.should_reply is True  # 正则认为该回
    assert "回退正则" in intent.reason


def test_no_llm_uses_regex_and_is_marked():
    intent = classify("这个怎么做的？", None)
    assert intent.source == "regex-fallback"
    assert intent.should_reply is True


def test_invalid_category_is_normalized():
    llm = FakeLlm({"should_reply": True, "category": "什么鬼", "priority": 9})
    intent = classify("随便说点", llm)
    assert intent.category == "unclear"
    assert intent.should_reply is False  # unclear 一律不回


def test_negative_category_forces_no_reply():
    llm = FakeLlm({"should_reply": True, "category": "noise", "priority": 9})
    intent = classify("随便", llm)
    assert intent.should_reply is False
    assert intent.priority == 0


def test_priority_zeroed_when_not_replied():
    llm = FakeLlm({"should_reply": False, "category": "feedback", "priority": 5})
    intent = classify("嗯", llm)
    assert intent.priority == 0


# ============================================================ 门禁

GOOD_REPLY = "谢谢记录。根因是多行正文走命令行被换行截断，已改成用文件传正文。"


def test_gate_approve():
    llm = FakeLlm({"decision": "approve", "risk": "low", "reasons": []})
    d = check("原评论内容", GOOD_REPLY, llm)
    assert d.decision == DECISION_APPROVE
    assert d.allows_send is True


def test_gate_deny_blocks_send():
    llm = FakeLlm({"decision": "deny", "risk": "high", "reasons": ["包含时间承诺"]})
    d = check("原评论", "下周就上线", llm)
    assert d.decision == DECISION_DENY
    assert d.allows_send is False
    assert "包含时间承诺" in d.reasons


def test_gate_escalate_blocks_send():
    llm = FakeLlm({"decision": "escalate", "risk": "medium", "reasons": ["涉及立场"]})
    d = check("原评论", GOOD_REPLY, llm)
    assert d.allows_send is False


def test_gate_without_llm_fails_closed():
    d = check("原评论", GOOD_REPLY, None)
    assert d.allows_send is False
    assert d.source == "no-llm"


def test_gate_llm_error_fails_closed():
    llm = FakeLlm(error=LlmError("timeout"))
    d = check("原评论", GOOD_REPLY, llm)
    assert d.allows_send is False
    assert d.source == "llm-error"


def test_gate_invalid_decision_fails_closed():
    llm = FakeLlm({"decision": "maybe", "risk": "low"})
    d = check("原评论", GOOD_REPLY, llm)
    assert d.allows_send is False
    assert d.source == "invalid"


def test_gate_empty_reply_fails_closed():
    llm = FakeLlm({"decision": "approve"})
    d = check("原评论", "   ", llm)
    assert d.allows_send is False
    assert d.source == "precheck"
    assert llm.calls == []


def test_gate_does_not_see_drafting_rationale():
    """门禁只收到原评论与待发回复，避免为自己的措辞辩护。"""
    llm = FakeLlm({"decision": "approve", "risk": "low", "reasons": []})
    check("对方说：报错了", GOOD_REPLY, llm, author_name="某人")
    system, user = llm.calls[0]
    assert "对方的原评论" in user
    assert "我们准备发出的回复" in user
    assert "某人" in user


def test_gate_normalizes_string_reasons():
    llm = FakeLlm({"decision": "deny", "risk": "high", "reasons": "单条理由"})
    d = check("原评论", GOOD_REPLY, llm)
    assert d.reasons == ["单条理由"]
