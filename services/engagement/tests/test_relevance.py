"""第一层判定（该不该回）的契约测试。"""

from __future__ import annotations

import pytest

from engagement.relevance import (
    PRIORITY,
    REPLY_RULES,
    SKIP_RULES,
    describe_relevance_rules,
    should_reply,
)


# ------------------------------------------------------------------ 不回

@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "[笑哭]",
        "[笑哭][笑哭]",
        "！！！",
        "🙂🙂🙂",
    ],
)
def test_empty_or_emoji_only_is_not_replied(text):
    r = should_reply(text)
    assert r.should_reply is False
    assert r.category in ("empty", "noise")


@pytest.mark.parametrize(
    "text",
    [
        "加我微信领资料",
        "私信我，代练上分",
        "刷单兼职日结",
        "点击链接领优惠券",
    ],
)
def test_spam_is_not_replied(text):
    r = should_reply(text)
    assert r.should_reply is False
    assert r.category == "spam"


@pytest.mark.parametrize("text", ["傻逼吧", "滚", "垃圾东西", "举报你"])
def test_hostile_is_not_replied(text):
    r = should_reply(text)
    assert r.should_reply is False
    assert r.category == "hostile"


@pytest.mark.parametrize("text", ["沙发", "前排", "666", "哈哈哈哈", "打卡"])
def test_noise_is_not_replied(text):
    r = should_reply(text)
    assert r.should_reply is False
    assert r.category == "noise"


def test_unclear_is_not_replied_by_default():
    r = should_reply("嗯嗯是这样啊")
    assert r.should_reply is False
    assert r.category == "unclear"
    assert r.rule == "unmatched_default"


def test_spam_wins_over_question():
    """垃圾内容即使带问号也不回——先排除，再看意图。"""
    r = should_reply("加我微信怎么弄？")
    assert r.should_reply is False
    assert r.category == "spam"


# ------------------------------------------------------------------ 该回

@pytest.mark.parametrize(
    "text",
    [
        "这个怎么做的？",
        "请问用的什么模型",
        "能不能出个教程",
        "为什么我的跑不起来",
        "有没有配置文件",
    ],
)
def test_questions_are_replied(text):
    r = should_reply(text)
    assert r.should_reply is True
    assert r.category == "question"
    assert r.priority == PRIORITY["question"]


@pytest.mark.parametrize("text", ["报错了", "这个 bug 还在", "接口超时没人管", "部署一直失败"])
def test_technical_is_replied(text):
    r = should_reply(text)
    assert r.should_reply is True
    assert r.category == "technical"


@pytest.mark.parametrize("text", ["建议加个导出功能", "学到了，很有用"])
def test_feedback_is_replied(text):
    r = should_reply(text)
    assert r.should_reply is True
    assert r.category == "feedback"


def test_question_wins_over_technical():
    """带提问词的按 question 归类，优先级更高。"""
    r = should_reply("api 怎么配")
    assert r.should_reply is True
    assert r.category == "question"
    assert r.priority == PRIORITY["question"]


def test_mention_is_replied():
    r = should_reply("@内卷树懒 在吗")
    assert r.should_reply is True
    assert r.category == "mention"


def test_supporter_has_high_priority():
    r = should_reply("随便说说", is_supporter=True)
    assert r.should_reply is True
    assert r.category == "supporter"
    assert r.priority == PRIORITY["supporter"]


def test_mention_flag_is_respected():
    r = should_reply("随便说说", is_mentioned=True)
    assert r.should_reply is True
    assert r.category == "mention"


def test_supporter_beats_unclear_but_not_spam():
    """充电用户优先，但垃圾内容仍然不回。"""
    assert should_reply("嗯", is_supporter=True).should_reply is True
    assert should_reply("加我微信", is_supporter=True).should_reply is False


# ------------------------------------------------------------------ 性质

def test_priority_ordering_is_sane():
    assert PRIORITY["question"] > PRIORITY["technical"] > PRIORITY["feedback"]
    assert PRIORITY["unclear"] == 0


def test_deterministic():
    a = should_reply("这个怎么用？")
    b = should_reply("这个怎么用？")
    assert (a.should_reply, a.category, a.rule) == (b.should_reply, b.category, b.rule)


def test_rule_tables_are_nonempty_and_documented():
    assert len(SKIP_RULES) >= 3
    assert len(REPLY_RULES) >= 3
    rows = describe_relevance_rules()
    assert all("reason" in row for row in rows)


# --------------------------------------------------- 真实数据回归（重要）

REAL_TECH_COMMENT = (
    "这条是调试记录，先留着不删。\n\n"
    "我在测自动化发布链路，工具没处理好多行正文——换行被当成了命令分隔符，\n"
    "结果只发出了第一句，配图和后半段全丢了。"
)


def test_real_technical_comment_is_replied():
    """真实评论驱动：技术讨论不一定带「报错」，也可能只描述机制。

    这条最初被判成 unclear/不回，补了技术词之后应该回。
    """
    r = should_reply(REAL_TECH_COMMENT)
    assert r.should_reply is True
    assert r.category == "technical"
