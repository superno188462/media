"""内容校验。

三条硬规则，都来自项目的外部副作用约束，不靠临场自觉：

R1 未实现功能不得声称
    创作模型不能把还没做出来的东西说成已经上线。内容里若出现"已上线"
    "已开始运营"这类断言，而项目状态里没有对应实现，必须拦下。

R2 AI 声明不可省
    B 站的动态与评论没有平台级「含 AI 生成内容」开关（只有视频投稿有），
    所以 AI 参与只能靠正文自述。正文缺声明就拦下。

R3 图片顺序即契约
    ``images`` 的顺序就是发布顺序，且每张图都要有对应的来源记录。
    数量对不上就拦下——避免发布出去的图和台账对不上。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import ContentItem

#: R1：这些词出现时，正文就是在断言功能已实现。
#: 中文命中「已上线/已发布/已开始运营」，英文命中 done/shipped/live。
_CLAIM_PATTERNS = (
    re.compile(r"已(上线|发布|开通|开始运营|投入运营)"),
    re.compile(r"(正式开始|正式投入)(运营|使用)"),
    re.compile(r"\b(we (already )?(launched|shipped|went live))\b", re.I),
    re.compile(r"\b(now (is )?live|already live)\b", re.I),
)

#: R2：正文里出现这些说法时，视为已自带 AI 参与声明。
_AI_MARKERS = ("AI", "ai", "模型", "agent", "Agent", "自动生成", "机器")


@dataclass
class Violation:
    rule: str
    message: str
    hint: str = ""

    def __str__(self) -> str:
        base = f"[{self.rule}] {self.message}"
        return f"{base}\n    → {self.hint}" if self.hint else base


def check_r1_no_false_claims(item: ContentItem, implemented: list[str] | None = None) -> list[Violation]:
    """R1：正文不得声称未实现的功能已完成。

    ``implemented`` 是已实现功能的关键词表；为空时只检查断言词本身，
    有表时还会检查断言的对象是否真在表里。
    """
    violations: list[Violation] = []
    hits = [p.pattern for p in _CLAIM_PATTERNS if p.search(item.body)]
    if not hits:
        return violations

    if implemented:
        # 断言的对象在已实现列表里，就不算虚报。
        mentioned = [kw for kw in implemented if kw in item.body]
        if mentioned:
            return violations

    violations.append(
        Violation(
            rule="R1",
            message="正文声称了尚未实现的功能",
            hint=(
                "改成「打算/正在尝试/计划」，或先真正实现它。"
                "AGENTS.md：不把示例、候选插件或调查结果当作业务已实现。"
            ),
        )
    )
    return violations


def check_r2_ai_declaration(item: ContentItem) -> list[Violation]:
    """R2：动态与评论没有平台 AI 开关，正文必须自带 AI 参与声明。"""
    if item.ai_declaration:
        return []
    if any(marker in item.body for marker in _AI_MARKERS):
        return [
            Violation(
                rule="R2",
                message="正文提到 AI/模型参与，但未给出显式的 AI 声明",
                hint="填写 ai_declaration 字段，并确保正文里也有对应的说明文字。",
            )
        ]
    return [
        Violation(
            rule="R2",
            message="缺少 AI 参与声明",
            hint="动态与评论没有平台级 AI 开关，必须在正文自述 AI 参与。",
        )
    ]


def check_r3_image_order(item: ContentItem) -> list[Violation]:
    """R3：图片数量必须与来源记录一一对应，顺序即发布顺序。"""
    if len(item.images) != len(item.source_urls):
        return [
            Violation(
                rule="R3",
                message=(
                    f"图片数({len(item.images)})与来源记录数({len(item.source_urls)})不一致"
                ),
                hint="每张图都要有对应的来源说明，顺序必须一致。",
            )
        ]
    return []


def check_status(item: ContentItem) -> list[Violation]:
    """发布前必须处于 approved 状态——模型不能自己批准。"""
    if item.status != "approved":
        return [
            Violation(
                rule="GATE",
                message=f"内容状态为 {item.status}，未获批准不能发布",
                hint="创作模型不能自行批准，必须经人工审核后置为 approved。",
            )
        ]
    return []


def validate(item: ContentItem, implemented: list[str] | None = None) -> list[Violation]:
    """跑全部规则，返回全部违规项（空列表代表通过）。"""
    violations: list[Violation] = []
    violations += check_r1_no_false_claims(item, implemented)
    violations += check_r2_ai_declaration(item)
    violations += check_r3_image_order(item)
    violations += check_status(item)
    return violations


def assert_valid(item: ContentItem, implemented: list[str] | None = None) -> None:
    """有违规就抛异常。"""
    violations = validate(item, implemented)
    if violations:
        detail = "\n".join(str(v) for v in violations)
        raise ValueError(f"内容未通过校验:\n{detail}")
