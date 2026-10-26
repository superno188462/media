"""采集层测试：水位线增量 + 漏斗。"""

from __future__ import annotations

from engagement.collect import (
    RawComment,
    WatermarkStore,
    fetch_new,
    summarize,
    triage,
)


class FakeClient:
    """按页返回预设评论。"""

    def __init__(self, pages: dict[int, list[dict]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, int, bool]] = []

    def list_comments(self, oid, comment_type="draw", page=1, unreplied=True):
        self.calls.append((oid, page, unreplied))
        return self.pages.get(page, []), {}


def item(rpid: int, content: str, mid: str = "1") -> dict:
    return {
        "rpid": rpid,
        "content": content,
        "user": {"mid": mid, "name": f"u{mid}"},
        "time": "2026-10-26T18:00:00+08:00",
        "like": 0,
        "reply_count": 0,
    }


# ---------------------------------------------------------------- 水位线

def test_watermark_persists(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    assert store.get("413402056", "draw") == 0
    store.set("413402056", "draw", 100, "t")
    assert store.get("413402056", "draw") == 100


def test_watermark_never_goes_backwards(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    store.set("o", "draw", 200)
    store.set("o", "draw", 100)
    assert store.get("o", "draw") == 200


def test_watermark_survives_bad_json(tmp_path):
    path = tmp_path / "wm.json"
    path.write_text("{oops", encoding="utf-8")
    assert WatermarkStore(path).get("o", "draw") == 0


# ---------------------------------------------------------------- 漏斗

def test_triage_filters_and_sorts():
    comments = [
        RawComment(1, "o", "1", "a", "谢谢", "t"),
        RawComment(2, "o", "2", "b", "这个怎么做的？", "t"),
        RawComment(3, "o", "3", "c", "[笑哭]", "t"),
        RawComment(4, "o", "4", "d", "加我微信", "t"),
        RawComment(5, "o", "5", "e", "报错了", "t"),
        RawComment(6, "o", "6", "f", "建议加个导出", "t"),
    ]
    results = triage(comments, limit=10)
    accepted = [t for t in results if t.accepted]
    # question(10) > technical(6) > feedback(5)
    assert [t.comment.rpid for t in accepted] == [2, 5, 6]
    rejected = {t.comment.rpid for t in results if not t.accepted}
    assert rejected == {1, 3, 4}


def test_triage_limit_caps_accepted():
    comments = [RawComment(i, "o", str(i), f"u{i}", "怎么弄？", "t") for i in range(1, 21)]
    results = triage(comments, limit=3)
    assert len([t for t in results if t.accepted]) == 3


def test_triage_excludes_self():
    comments = [RawComment(1, "o", "999", "me", "这个怎么弄？", "t")]
    results = triage(comments, limit=10, self_mid="999")
    assert results[0].accepted is False
    assert results[0].relevance.rule == "self"


def test_summarize_counts_rejections():
    comments = [
        RawComment(1, "o", "1", "a", "怎么弄？", "t"),
        RawComment(2, "o", "2", "b", "[笑哭]", "t"),
        RawComment(3, "o", "3", "c", "加我微信", "t"),
    ]
    stats = summarize(triage(comments))
    assert stats["total"] == 3
    assert stats["accepted"] == 1
    assert stats["rejected"] == 2
    assert "spam" in str(stats["rejected_by_rule"]) or "emoji_only" in str(stats["rejected_by_rule"])


# ---------------------------------------------------------------- 增量

def test_fetch_new_only_returns_after_watermark(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    store.set("o", "draw", 50)
    client = FakeClient({1: [item(40, "旧的"), item(60, "新的怎么弄？")]})

    results, stats = fetch_new(client, "o", "draw", store)
    texts = [t.comment.content for t in results]
    assert "新的怎么弄？" in texts
    assert "旧的" not in texts
    assert stats["watermark_before"] == 50
    assert stats["watermark_after"] == 60


def test_fetch_new_advances_watermark_even_when_rejected(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    client = FakeClient({1: [item(10, "[笑哭]"), item(20, "加我微信")]})
    fetch_new(client, "o", "draw", store)
    # 被拒的也推进水位，避免下次重复检查
    assert store.get("o", "draw") == 20


def test_fetch_new_respects_page_limit(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    pages = {p: [item(p * 100 + i, "怎么弄？") for i in range(20)] for p in (1, 2, 3)}
    client = FakeClient(pages)
    _, stats = fetch_new(client, "o", "draw", store, max_pages=2)
    assert stats["pages_read"] == 2
    assert len(client.calls) == 2


def test_fetch_new_stops_on_short_page(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    client = FakeClient({1: [item(1, "怎么弄？")], 2: [item(2, "怎么弄？")]})
    _, stats = fetch_new(client, "o", "draw", store, max_pages=5)
    assert stats["pages_read"] == 1  # 不足一页即视为最后一页


def test_fetch_new_uses_unreplied_by_default(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    client = FakeClient({1: [item(1, "怎么弄？")]})
    fetch_new(client, "o", "draw", store)
    assert client.calls[0][2] is True


def test_fetch_new_reports_client_error(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")

    class Broken:
        def list_comments(self, *a, **kw):
            return [], {"error": "rate_limited"}

    _, stats = fetch_new(Broken(), "o", "draw", store)
    assert "errors" in stats
    assert stats["total"] == 0


# ---------------------------------------------------------------- 楼中楼

class NestedClient:
    """根评论 + 楼中楼。"""

    def __init__(self, roots: list[dict], replies: dict[int, list[dict]]) -> None:
        self.roots = roots
        self.replies = replies
        self.calls: list[tuple[str, int]] = []

    def list_comments(self, oid, comment_type="draw", page=1, unreplied=True):
        return (self.roots if page == 1 else []), {}

    def list_replies(self, oid, rpid, comment_type="draw", page=1, size=20):
        self.calls.append(("replies", rpid))
        return self.replies.get(rpid, []), {}


def nested_item(rpid: int, content: str, root: int, parent: int | None = None) -> dict:
    return {
        "rpid": rpid, "content": content,
        "user": {"mid": "9", "name": "n"},
        "time": "t", "root": root, "parent": parent or root,
    }


def root_item(rpid: int, content: str, reply_count: int) -> dict:
    return {
        "rpid": rpid, "content": content,
        "user": {"mid": "1", "name": "u"},
        "time": "t", "reply_count": reply_count,
    }


def test_nested_replies_are_collected(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    client = NestedClient(
        roots=[root_item(100, "根评论", reply_count=5)],
        replies={100: [nested_item(200, "楼中楼提问？", root=100)]},
    )
    results, stats = fetch_new(client, "o", "draw", store)
    contents = [t.comment.content for t in results]
    assert "楼中楼提问？" in contents
    assert stats["nested_found"] == 1
    assert stats["nested_roots_checked"] == 1


def test_nested_flag_parsed():
    c = RawComment.from_api(nested_item(200, "x", root=100, parent=150), "o")
    assert c.is_nested is True
    assert c.root == 100
    assert c.parent == 150


def test_root_comment_is_not_nested():
    c = RawComment.from_api(root_item(100, "x", 0), "o")
    assert c.is_nested is False


def test_nested_can_be_disabled(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    client = NestedClient(
        roots=[root_item(100, "根评论", reply_count=5)],
        replies={100: [nested_item(200, "楼中楼提问？", root=100)]},
    )
    _, stats = fetch_new(client, "o", "draw", store, include_nested=False)
    assert stats["nested_found"] == 0
    assert client.calls == []


def test_nested_roots_are_capped(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    roots = [root_item(100 + i, "根", reply_count=2) for i in range(10)]
    client = NestedClient(roots=roots, replies={})
    _, stats = fetch_new(client, "o", "draw", store, max_nested_roots=3)
    assert stats["nested_roots_checked"] == 3
    assert len(client.calls) == 3


def test_nested_reply_advances_watermark(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    client = NestedClient(
        roots=[root_item(100, "根", reply_count=1)],
        replies={100: [nested_item(300, "新的楼中楼", root=100)]},
    )
    _, stats = fetch_new(client, "o", "draw", store)
    assert stats["watermark_after"] == 300
    assert store.get("o", "draw") == 300


def test_nested_root_backfilled_when_api_omits_it(tmp_path):
    store = WatermarkStore(tmp_path / "wm.json")
    item = {k: v for k, v in nested_item(200, "x", root=100).items() if k != "root"}
    client = NestedClient(roots=[root_item(100, "根", reply_count=1)], replies={100: [item]})
    results, _ = fetch_new(client, "o", "draw", store)
    nested = [t for t in results if t.comment.is_nested]
    assert nested and nested[0].comment.root == 100
