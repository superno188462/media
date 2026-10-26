"""风险判定策略。

**全部是确定性规则**，不依赖模型主观判断——这样同一个输入永远得到同一个
结论，审计时能复现。规则表就是「你事先批准的那张表」的代码化。

设计原则：**拿不准就升级，不是拿不准就放行。**
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    ROUTE_BATCH,
    ROUTE_BLOCK,
    ROUTE_DIRECT,
    ROUTE_SINGLE,
    Assessment,
    ReplyCandidate,
)


@dataclass(frozen=True)
class Rule:
    """一条判定规则。按列表顺序匹配，先命中先返回。"""

    name: str
    pattern: re.Pattern[str]
    risk: str
    route: str
    reason: str


def _r(name: str, pattern: str, risk: str, route: str, reason: str) -> Rule:
    return Rule(name, re.compile(pattern, re.IGNORECASE), risk, route, reason)


#: 规则按严重程度从高到低排列。**顺序即优先级**。
RULES: tuple[Rule, ...] = (
    _r(
        "contact_or_link",
        r"https?://|www\.|加我|私聊|微信|weixin|wechat|\bqq\b|联系方式|群号",
        RISK_HIGH,
        ROUTE_SINGLE,
        "包含链接或站外联系方式，可能被判定为导流",
    ),
    _r(
        "commitment",
        r"承诺|保证|一定|肯定|包[证票]|负责到底|"
        r"下周|明天|后天|本周|月底|年内|\d+\s*(天|小时|分钟|周|个月)内|"
        r"上线|发布|退款|返现|免费|抽奖|福利|优惠",
        RISK_HIGH,
        ROUTE_SINGLE,
        "涉及时间、承诺或利益相关表述，需人工确认",
    ),
    _r(
        "controversy",
        r"骗|假的|造假|垃圾|割韭菜|智商税|举报|投诉|维权|起诉|抄袭|洗稿|"
        r"退钱|差评|恶心|恶心人",
        RISK_HIGH,
        ROUTE_SINGLE,
        "涉及争议或负面评价，公开回应需谨慎",
    ),
    _r(
        "privacy",
        r"身份证|手机号|住址|真实姓名|银行卡|密码|验证码|地址是",
        RISK_HIGH,
        ROUTE_SINGLE,
        "可能涉及个人隐私信息",
    ),
    _r(
        "stance",
        r"我们会|我方|本公司|官方立场|正式回应|说法是|声明|"
        r"不代表|仅代表|个人观点",
        RISK_MEDIUM,
        ROUTE_BATCH,
        "包含立场或代表账号发言的表述",
    ),
    _r(
        "money_or_number",
        r"\d+\s*(元|块|万|千|个|条|次|人|天|小时|分钟|周|个月|年)|"
        r"价格|收费|付费|打赏|投币换",
        RISK_MEDIUM,
        ROUTE_BATCH,
        "包含具体数字或金额，需核对准确性",
    ),
)

#: 命中这些模板且没有任何风险词时，视为低风险可直接发。
SAFE_TEMPLATES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("thanks", re.compile(r"^(谢谢|感谢|多谢|谢啦|收到|好的|了解|明白)", re.IGNORECASE)),
    ("ack_fixed", re.compile(r"(已修复|已经修复|已改好|已确认|确认了|已更正)")),
    ("fact_reply", re.compile(r"^(是的|对的|没错|确实|正解|对，|是同一条)")),
)

#: 判定为直发时，回复长度上限。太长的内容不适合模板化直发。
MAX_DIRECT_LEN = 200


def assess(candidate: ReplyCandidate) -> Assessment:
    """判定一条回复该怎么走。"""
    reply = (candidate.reply_text or "").strip()

    if not reply:
        return Assessment(
            risk=RISK_HIGH,
            route=ROUTE_BLOCK,
            rule="empty_reply",
            reason="回复内容为空",
        )

    # 1. 风险词优先：命中即升级，命中越靠前越严重。
    for rule in RULES:
        match = rule.pattern.search(reply)
        if match:
            return Assessment(
                risk=rule.risk,
                route=rule.route,
                rule=rule.name,
                reason=f"{rule.reason}（命中「{match.group(0)}」）",
            )

    # 2. 无风险词，再看是否命中安全模板。
    for name, pattern in SAFE_TEMPLATES:
        if pattern.search(reply):
            if len(reply) > MAX_DIRECT_LEN:
                return Assessment(
                    risk=RISK_MEDIUM,
                    route=ROUTE_BATCH,
                    rule="template_too_long",
                    reason=f"命中模板 {name} 但内容过长（{len(reply)} 字），不适合直发",
                )
            return Assessment(
                risk=RISK_LOW,
                route=ROUTE_DIRECT,
                rule=f"template:{name}",
                reason="命中预批准模板且无风险词",
            )

    # 3. 都没命中：不直发，但也不必单条打断——进批量待确认。
    return Assessment(
        risk=RISK_MEDIUM,
        route=ROUTE_BATCH,
        rule="unmatched_default",
        reason="未命中安全模板，按批量待确认处理（不确定不放行）",
    )


def describe_rules() -> list[dict]:
    """把规则表导出成可读形式，便于写进文档或卡片说明。"""
    rows = [
        {
            "rule": rule.name,
            "risk": rule.risk,
            "route": rule.route,
            "reason": rule.reason,
        }
        for rule in RULES
    ]
    rows.append(
        {
            "rule": "template:*",
            "risk": RISK_LOW,
            "route": ROUTE_DIRECT,
            "reason": "命中预批准模板且无风险词",
        }
    )
    rows.append(
        {
            "rule": "unmatched_default",
            "risk": RISK_MEDIUM,
            "route": ROUTE_BATCH,
            "reason": "未命中模板，批量待确认",
        }
    )
    return rows
