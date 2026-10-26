"""第一层判定：这条评论**该不该回**。

和 `policy.assess()` 的区别：

- `relevance.should_reply()` 决定 **要不要回**（本模块）
- `policy.assess()` 决定 **怎么发**（直发/批量/单条）

顺序必须是先判要不要回，再判怎么发。否则会给垃圾评论分配审核资源。

设计原则：**沉默是默认，回复是例外。** 拿不准就不回——
不回的成本远低于回错。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- 该不该回 ---------------------------------------------------------------

REPLY_NO = "no"
REPLY_YES = "yes"

#: 优先级分值。数值越大越先处理。
PRIORITY = {
    "question": 10,
    "mention": 9,
    "supporter": 8,
    "technical": 6,
    "feedback": 5,
    "unclear": 0,
}


@dataclass(frozen=True)
class Relevance:
    """一条评论的相关性判定。"""

    should_reply: bool
    category: str
    priority: int
    rule: str
    reason: str


@dataclass(frozen=True)
class _Rule:
    name: str
    pattern: re.Pattern[str]
    category: str
    should_reply: bool
    reason: str


def _r(name: str, pattern: str, category: str, yes: bool, reason: str) -> _Rule:
    return _Rule(name, re.compile(pattern, re.IGNORECASE), category, yes, reason)


#: 先判「不回」——这些即使像提问也不值得回。
SKIP_RULES: tuple[_Rule, ...] = (
    _r(
        "spam",
        r"加\s*(我|下)?\s*[vV微]|微信|wechat|weixin|私信我|代练|刷单|兼职|日结|"
        r"引流|买粉|涨粉|互关|点击链接|复制口令|优惠券|返利|投资|理财|博彩",
        "spam",
        False,
        "广告或引流内容，回复等于帮它曝光",
    ),
    _r(
        "hostile",
        r"傻[逼比]|蠢|弱智|脑残|滚|去死|恶心|垃圾东西|"
        r"举报你|骗子死|割韭菜的东西",
        "hostile",
        False,
        "辱骂或明显挑衅，回复会被当作给流量",
    ),
    _r(
        "noise",
        r"^(沙发|前排|打卡|路过|签到|666+|1{3,}|哈{3,}|啊{3,}|"
        r"第[一1]|来了|围观)[！!。.~～\s]*$",
        "noise",
        False,
        "无信息量的占位评论",
    ),
)


def _is_emoji_or_punct_only(text: str) -> bool:
    """只有表情和标点时返回 True。

    标准库 ``re`` 不支持 ``\\p{...}``，所以改用「剥掉表情标记与非单词字符
    后还剩什么」来判断。
    """
    stripped = re.sub(r"\[[^\]]{1,8}\]", "", text)  # B 站表情写法：[笑哭]
    stripped = re.sub(r"[\W_]", "", stripped, flags=re.UNICODE)  # 标点、emoji、空白
    return stripped == ""

#: 再判「该回」——按优先级从高到低。
REPLY_RULES: tuple[_Rule, ...] = (
    _r(
        "question",
        r"[?？]|怎么|为什么|为啥|什么|如何|能不能|可不可以|请问|求教|求个|"
        r"哪[个里]|是不是|有没有|多少|多久",
        "question",
        True,
        "提问，有明确的信息需求",
    ),
    _r(
        "mention",
        r"@内卷树懒|@\S*树懒",
        "mention",
        True,
        "明确 @ 了本账号",
    ),
    _r(
        "technical",
        r"[Bb]ug|报错|错误|异常|崩溃|失败|不显示|没反应|配置|参数|代码|"
        r"教程|脚本|接口|api|prompt|提示词|工作流|部署|"
        # 下面这组来自真实评论：技术讨论未必带「报错」，也可能只描述机制。
        r"调试|链路|命令行|换行|截断|传参|自动化|日志|渲染|编码|依赖|终端|工具链",
        "technical",
        True,
        "技术讨论或被反馈问题",
    ),
    _r(
        "feedback",
        r"建议|希望|想要|期待|能不能加|求出|许愿|下期|做什么|"
        r"很喜欢|太好用|有用|学到了",
        "feedback",
        True,
        "内容反馈或选题建议",
    ),
)


def should_reply(
    text: str,
    *,
    is_supporter: bool = False,
    is_mentioned: bool = False,
) -> Relevance:
    """判定一条评论该不该回，以及优先级。

    ``is_supporter``（充电/粉丝勋章）与 ``is_mentioned``（被 @）
    由平台数据提供，优先级高于文本规则。
    """
    content = (text or "").strip()

    if not content:
        return Relevance(False, "empty", 0, "empty", "空评论")

    if _is_emoji_or_punct_only(content):
        return Relevance(False, "noise", 0, "emoji_only", "只有表情或标点，没有可回的内容")

    # 1. 先排除：垃圾、辱骂、无信息量。
    for rule in SKIP_RULES:
        if rule.pattern.search(content):
            return Relevance(
                False, rule.category, 0, rule.name, rule.reason
            )

    # 2. 充电/粉丝优先于文本判断。
    if is_supporter:
        return Relevance(True, "supporter", PRIORITY["supporter"], "supporter", "充过电或带粉丝勋章")

    if is_mentioned:
        return Relevance(True, "mention", PRIORITY["mention"], "mention", "明确 @ 了本账号")

    # 3. 文本规则。
    for rule in REPLY_RULES:
        if rule.pattern.search(content):
            return Relevance(
                True, rule.category, PRIORITY.get(rule.category, 1), rule.name, rule.reason
            )

    # 4. 兜底：看不懂就不回。
    return Relevance(
        False,
        "unclear",
        0,
        "unmatched_default",
        "未识别出明确意图，按不回处理（沉默成本低于回错）",
    )


def describe_relevance_rules() -> list[dict]:
    rows: list[dict] = []
    for rule in SKIP_RULES:
        rows.append({"rule": rule.name, "reply": False, "category": rule.category, "reason": rule.reason})
    for rule in REPLY_RULES:
        rows.append(
            {
                "rule": rule.name,
                "reply": True,
                "category": rule.category,
                "priority": PRIORITY.get(rule.category, 1),
                "reason": rule.reason,
            }
        )
    rows.append({"rule": "unmatched_default", "reply": False, "category": "unclear", "reason": "看不懂就不回"})
    return rows
