"""意图识别：**大模型为主，正则为辅**。

分工：

- **正则**：只做「明显的硬拒绝」——纯表情、广告、辱骂、占位。命中就直接不回，
  省下一次模型调用。这是**省钱的前置筛**，不承担语义判断。
- **大模型**：真正的意图识别。判断是不是提问、技术讨论、反馈，以及值不值得回。
- **兜底**：模型不可用时退回纯正则结果；此时 ``source`` 标成 ``regex-fallback``，
  让人能看出这次没用模型。

判定原则不变：**沉默是默认，回复是例外。拿不准就不回。**
"""

from __future__ import annotations

from dataclasses import dataclass

from .llm import LlmClient, LlmError
from .relevance import PRIORITY, Relevance, should_reply

VALID_CATEGORIES = {
    "question",
    "technical",
    "feedback",
    "mention",
    "supporter",
    "spam",
    "hostile",
    "noise",
    "empty",
    "unclear",
}

SYSTEM_PROMPT = """你是「内卷树懒」B站账号的评论意图识别器。这个账号由 AI 运营、人工审核。

任务：判断一条评论**是否值得回复**，以及属于什么类别。

判定原则：**沉默是默认，回复是例外。拿不准就判 should_reply=false。**
不回的成本远低于回错。

应当回复（按优先级）：
- question(10)：明确提问，有信息需求
- mention(9)：明确 @ 了本账号
- supporter(8)：充过电或带粉丝勋章（会额外告知）
- technical(6)：技术讨论、反馈问题、描述机制
- feedback(5)：内容反馈、选题建议、明确表达喜欢/收获

不回复：
- spam：广告、引流、加联系方式、代练刷单
- hostile：辱骂、挑衅、钓鱼
- noise：纯表情、沙发、打卡、无意义占位
- unclear：看不出明确意图（默认归到这里就不回）

只输出 JSON，不要多余文字：
{"should_reply": true|false, "category": "上面某个类别", "priority": 0-10, "reason": "一句话理由"}
"""


@dataclass
class Intent:
    """意图识别结果。``source`` 标明是否真的用了模型。"""

    should_reply: bool
    category: str
    priority: int
    reason: str
    source: str = "llm"

    def to_relevance(self) -> Relevance:
        return Relevance(
            should_reply=self.should_reply,
            category=self.category,
            priority=self.priority,
            rule=f"intent:{self.source}",
            reason=self.reason,
        )


#: 这些类别是硬拒绝，直接跳过模型调用。
HARD_REJECT_CATEGORIES = {"spam", "hostile", "noise", "empty"}


def _regex_first_pass(text: str, is_supporter: bool = False) -> Relevance:
    return should_reply(text, is_supporter=is_supporter)


def classify(
    text: str,
    llm: LlmClient | None = None,
    *,
    is_supporter: bool = False,
    author_name: str = "",
) -> Intent:
    """识别一条评论的意图。模型优先，正则兜底。"""
    content = (text or "").strip()

    # 1. 正则硬拒绝：明显的垃圾不必花模型的钱。
    first = _regex_first_pass(content, is_supporter=is_supporter)
    if not first.should_reply and first.category in HARD_REJECT_CATEGORIES:
        return Intent(False, first.category, 0, first.reason, source="regex")

    # 2. 没有模型就直接用正则结论（并如实标注）。
    if llm is None:
        return Intent(
            first.should_reply,
            first.category,
            first.priority,
            first.reason,
            source="regex-fallback",
        )

    # 3. 模型识别。
    user = (
        f"对方昵称：{author_name or '（未知）'}\n"
        f"是否充过电或带粉丝勋章：{'是' if is_supporter else '否'}\n"
        f"评论内容：\n{content}"
    )
    try:
        result = llm.chat_json(SYSTEM_PROMPT, user)
    except LlmError as exc:
        # 模型挂了不等于可以放行：退回正则结论，并标注来源。
        return Intent(
            first.should_reply,
            first.category,
            first.priority,
            f"模型识别失败，回退正则：{exc}；原判定：{first.reason}",
            source="regex-fallback",
        )

    should = bool(result.get("should_reply"))
    category = str(result.get("category", "")).strip().lower()
    reason = str(result.get("reason", "")).strip() or "模型未给理由"

    if category not in VALID_CATEGORIES:
        category = "unclear"
    if category in {"spam", "hostile", "noise", "empty", "unclear"}:
        should = False

    try:
        priority = int(result.get("priority", PRIORITY.get(category, 0)))
    except (TypeError, ValueError):
        priority = PRIORITY.get(category, 0)

    if not should:
        priority = 0

    return Intent(should, category, priority, reason, source="llm")
