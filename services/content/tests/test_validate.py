"""内容校验规则的契约测试。

这些测试锁住 R1/R2/R3 和审核闸门的行为。规则变了要先改契约，
不能改测试来迁就实现。
"""

from __future__ import annotations

import pytest

from content.model import ContentItem
from content.validate import (
    check_r1_no_false_claims,
    check_r2_ai_declaration,
    check_r3_image_order,
    check_status,
    validate,
)


def make_item(**overrides) -> ContentItem:
    base = {
        "id": "c-001",
        "topic_id": "t-001",
        "title": "标题",
        "body": "一段普通的话。",
        "images": [],
        "source_urls": [],
        "ai_declaration": "本文由 AI 起草，人工审核后发布。",
        "status": "approved",
    }
    base.update(overrides)
    return ContentItem(**base)


# --------------------------------------------------------------------- R1

def test_r1_flags_claim_of_unimplemented_feature():
    item = make_item(body="我们的自动化投稿功能已上线，跑起来很稳。")
    violations = check_r1_no_false_claims(item)
    assert len(violations) == 1
    assert violations[0].rule == "R1"


def test_r1_allows_planned_wording():
    item = make_item(body="打算做一个由 AI 运营的账号，先把想法放出来。")
    assert check_r1_no_false_claims(item) == []


def test_r1_allows_claim_when_feature_is_implemented():
    item = make_item(body="自动投稿功能已上线，跑起来很稳。")
    assert check_r1_no_false_claims(item, implemented=["自动投稿"]) == []


def test_r1_still_flags_when_claimed_feature_not_in_list():
    item = make_item(body="自动投稿功能已上线。")
    violations = check_r1_no_false_claims(item, implemented=["视频转码"])
    assert len(violations) == 1


# --------------------------------------------------------------------- R2

def test_r2_requires_ai_declaration():
    item = make_item(ai_declaration=None, body="一段普通的话。")
    violations = check_r2_ai_declaration(item)
    assert len(violations) == 1
    assert violations[0].rule == "R2"


def test_r2_flags_ai_mention_without_declaration():
    item = make_item(ai_declaration=None, body="这条内容由 AI 起草。")
    assert check_r2_ai_declaration(item)[0].rule == "R2"


def test_r2_accepts_explicit_declaration():
    item = make_item(ai_declaration="本文由 AI 起草，人工审核后发布。")
    assert check_r2_ai_declaration(item) == []


# --------------------------------------------------------------------- R3

def test_r3_requires_matching_source_count():
    item = make_item(images=["a.png", "b.png"], source_urls=["http://x/a"])
    violations = check_r3_image_order(item)
    assert len(violations) == 1
    assert violations[0].rule == "R3"


def test_r3_accepts_matching_counts():
    item = make_item(images=["a.png", "b.png"], source_urls=["http://x/a", "http://x/b"])
    assert check_r3_image_order(item) == []


# ------------------------------------------------------------------- 闸门

def test_unapproved_content_cannot_pass_gate():
    item = make_item(status="draft")
    violations = check_status(item)
    assert len(violations) == 1
    assert violations[0].rule == "GATE"


def test_approved_content_passes_gate():
    item = make_item(status="approved")
    assert check_status(item) == []


def test_validate_returns_all_violations():
    item = make_item(
        body="功能已上线，这段由 AI 起草。",
        images=["a.png"],
        source_urls=[],
        ai_declaration=None,
        status="draft",
    )
    rules = {v.rule for v in validate(item)}
    assert rules == {"R1", "R2", "R3", "GATE"}


def test_valid_item_has_no_violations():
    assert validate(make_item()) == []
