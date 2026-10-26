"""发布适配器的测试。

重点是「提交结果未知时不自动重发」这条：bili-cli 出现过平台已成功、
CLI 收尾失败的情况，适配器必须核对平台证据，而不是重发。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from content.model import ContentItem
from content.publish.bilibili import BilibiliPublisher


class FakePublisher(BilibiliPublisher):
    """用脚本化的返回值代替真实调用。"""

    def __init__(self, post_result, list_result):
        super().__init__(project_root=Path("."))
        self.post_result = post_result
        self.list_result = list_result
        self.calls: list[list[str]] = []

    def _run(self, args: list[str]) -> tuple[int, dict | None, str]:
        self.calls.append(args)
        if args[:2] == ["dynamic", "post"]:
            code, payload = self.post_result
            return code, payload, json.dumps(payload) if payload else ""
        if args[:2] == ["dynamic", "list"]:
            code, payload = self.list_result
            return code, payload, json.dumps(payload) if payload else ""
        return 1, None, ""


def make_item(**overrides) -> ContentItem:
    base = {
        "id": "c-001",
        "topic_id": "t-001",
        "title": "标题",
        "body": "正文内容",
        "images": [],
        "source_urls": [],
        "ai_declaration": "本文由 AI 起草，人工审核后发布。",
        "status": "approved",
    }
    base.update(overrides)
    return ContentItem(**base)


def test_publish_success_returns_ref():
    payload = {"ok": True, "data": {"id": "123", "url": "https://t.bilibili.com/123"}}
    pub = FakePublisher((0, payload), (0, {"ok": True, "data": {"items": []}}))
    result = pub.publish(make_item())
    assert result.ok
    assert result.platform_ref == "123"


def test_publish_builds_correct_arguments():
    payload = {"ok": True, "data": {"id": "1"}}
    pub = FakePublisher((0, payload), (0, {"ok": True, "data": {"items": []}}))
    item = make_item(
        images=["a.png", "b.png"],
        source_urls=["http://x/a", "http://x/b"],
        topic="AI",
        at_users=["某人"],
    )
    pub.publish(item)

    args = pub.calls[0]
    assert args[:3] == ["dynamic", "post", "正文内容"]
    assert args.count("--image") == 2
    assert "--topic" in args
    assert "--at" in args
    # 图片顺序必须与 images 一致
    image_positions = [args[i + 1] for i, a in enumerate(args) if a == "--image"]
    assert image_positions == ["a.png", "b.png"]


def test_cli_error_but_platform_has_it_is_reported_as_success():
    """CLI 收尾失败、平台实际已发——不得重发，报成功。"""
    post = (1, {"ok": False, "error": {"message": "PermissionError: ratelimit.tmp"}})
    listing = {
        "ok": True,
        "data": {"items": [{"id": "999", "text": "正文内容"}]},
    }
    pub = FakePublisher(post, (0, listing))
    result = pub.publish(make_item())

    assert result.ok
    assert result.platform_ref == "999"
    assert "未重发" in result.detail
    # 只调用了一次 post，绝不重试
    post_calls = [c for c in pub.calls if c[:2] == ["dynamic", "post"]]
    assert len(post_calls) == 1


def test_real_failure_is_reported_and_not_retried():
    post = (1, {"ok": False, "error": {"message": "rate_limited"}})
    listing = {"ok": True, "data": {"items": [{"id": "1", "text": "别的内容"}]}}
    pub = FakePublisher(post, (0, listing))
    result = pub.publish(make_item())

    assert not result.ok
    assert "rate_limited" in result.detail
    post_calls = [c for c in pub.calls if c[:2] == ["dynamic", "post"]]
    assert len(post_calls) == 1


def test_unapproved_content_is_blocked_before_any_call():
    post = (0, {"ok": True, "data": {"id": "1"}})
    pub = FakePublisher(post, (0, {"ok": True, "data": {"items": []}}))
    with pytest.raises(ValueError):
        pub.publish(make_item(status="draft"))
    assert pub.calls == []


def test_preview_makes_no_calls():
    pub = FakePublisher((0, {"ok": True, "data": {}}), (0, {"ok": True, "data": {}}))
    preview = pub.preview(make_item(images=["a.png"]))
    assert "1. a.png" in preview.render()
    assert pub.calls == []
