"""发送前门禁（GATE）。

**结构强制**：``reply`` 之前必须拿到 ``GateDecision(allows_send=True)``，
没有就拒绝发送。这不是"建议"，是代码路径上过不去的关卡。

设计约束：

1. **独立判断**：门禁只看「对方原评论」和「我们待发的回复」，
   **不给它起草时的理由**——避免模型为自己的措辞找借口。
2. **fail closed**：门禁调用失败、返回不合法，一律 deny，绝不放行。
3. **可审计**：决定、风险、理由全部落盘。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LlmClient, LlmError

DECISION_APPROVE = "approve"
DECISION_DENY = "deny"
DECISION_ESCALATE = "escalate"

_VALID_DECISIONS = {DECISION_APPROVE, DECISION_DENY, DECISION_ESCALATE}
_VALID_RISKS = {"low", "medium", "high"}

SYSTEM_PROMPT = """你是「内卷树懒」B站账号的发送前门禁。这是一个由 AI 运营、人工审核的账号。

你的唯一职责：判断下面这条**待发的评论回复**是否可以安全发出。
你只看两样东西：对方的原评论、我们准备发出的回复。

务必从严。宁可拦下让人工看，也不要放过会伤害账号的内容。

按下面清单逐项检查，每命中一条就记一条理由：

1. 是否冒充真人经历或情感（"我当年也是…"这种口吻）
2. 是否包含承诺、时间点、金额、数量（"下周上线"、"免费"、"3 天"）
3. 是否包含未经核实的事实断言
4. 是否包含链接、联系方式、隐私信息
5. 是否涉及争议、负面、对立话题
6. 语气是否得体，是否可能被截图断章取义
7. 是否与账号定位一致（AI 运营、过程公开、不装人）
8. 是否与对方原评论相关（答非所问也算不合格）

判定：
- "approve"：全部通过，可以发
- "escalate"：本身没大问题，但值得人工确认（例如涉及账号立场、话题敏感）
- "deny"：明确不能发

只输出 JSON，不要多余文字：
{"decision": "approve|deny|escalate", "risk": "low|medium|high", "reasons": ["..."]}
"""


@dataclass
class GateDecision:
    decision: str
    risk: str
    reasons: list[str] = field(default_factory=list)
    source: str = "llm"

    @property
    def allows_send(self) -> bool:
        return self.decision == DECISION_APPROVE

    def describe(self) -> str:
        return f"门禁={self.decision} 风险={self.risk} 理由={'；'.join(self.reasons) or '无'}"


def _deny(reason: str, risk: str = "high", source: str = "gate") -> GateDecision:
    return GateDecision(DECISION_DENY, risk, [reason], source=source)


def check(
    source_text: str,
    reply_text: str,
    llm: LlmClient | None,
    *,
    author_name: str = "",
) -> GateDecision:
    """发送前门禁。**门禁不可用即拒绝**。"""
    if llm is None:
        return _deny("门禁不可用（未配置模型），按 fail-closed 拒绝发送", source="no-llm")

    reply = (reply_text or "").strip()
    if not reply:
        return _deny("待发回复为空", source="precheck")

    user = (
        f"对方昵称：{author_name or '（未知）'}\n"
        f"对方的原评论：\n{source_text or '（未提供）'}\n\n"
        f"我们准备发出的回复：\n{reply}"
    )

    try:
        result = llm.chat_json(SYSTEM_PROMPT, user)
    except LlmError as exc:
        return _deny(f"门禁调用失败：{exc}", source="llm-error")

    decision = str(result.get("decision", "")).strip().lower()
    risk = str(result.get("risk", "")).strip().lower()
    reasons = result.get("reasons")

    if decision not in _VALID_DECISIONS:
        return _deny(f"门禁返回非法决定：{decision or '空'}", source="invalid")
    if risk not in _VALID_RISKS:
        risk = "high" if decision != DECISION_APPROVE else "low"

    if isinstance(reasons, str):
        reasons = [reasons]
    if not isinstance(reasons, list):
        reasons = []
    reasons = [str(r).strip() for r in reasons if str(r).strip()]

    return GateDecision(decision, risk, reasons, source="llm")
