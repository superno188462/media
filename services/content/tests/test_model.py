"""状态机与持久化的测试。"""

from __future__ import annotations

import pytest

from content.model import ContentItem


def make_item(**overrides) -> ContentItem:
    base = {
        "id": "c-001",
        "topic_id": "t-001",
        "title": "标题",
        "body": "正文",
    }
    base.update(overrides)
    return ContentItem(**base)


def test_draft_can_go_to_pending_review():
    item = make_item(status="draft")
    item.transition_to("pending_review")
    assert item.status == "pending_review"


def test_draft_cannot_go_straight_to_published():
    item = make_item(status="draft")
    with pytest.raises(ValueError):
        item.transition_to("published")


def test_pending_review_can_be_rejected_back_to_draft():
    item = make_item(status="pending_review")
    item.transition_to("draft")
    assert item.status == "draft"


def test_published_is_terminal():
    item = make_item(status="published")
    with pytest.raises(ValueError):
        item.transition_to("failed")


def test_save_and_load_roundtrip(tmp_path):
    item = make_item(images=["a.png"], source_urls=["http://x/a"], status="approved")
    path = tmp_path / "nested" / "item.json"
    item.save(path)

    loaded = ContentItem.load(path)
    assert loaded.to_dict() == item.to_dict()


def test_load_ignores_unknown_fields(tmp_path):
    path = tmp_path / "item.json"
    path.write_text(
        '{"id":"c-1","topic_id":"t-1","title":"t","body":"b","future_field":123}',
        encoding="utf-8",
    )
    loaded = ContentItem.load(path)
    assert loaded.id == "c-1"
