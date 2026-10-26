"""审核卡片构建的契约测试。"""

from __future__ import annotations

from feishu.cards import (
    ACTION_APPROVE,
    ACTION_CANCEL,
    ACTION_REJECT,
    ReviewDraftView,
    VideoInfo,
    build_review_card,
)


def view(**overrides) -> ReviewDraftView:
    base = {
        "review_id": "rev-1",
        "draft_id": "d-1",
        "revision": 3,
        "content_digest": "deadbeefcafe0123",
        "title": "测试标题",
        "body": "正文第一段。\n正文第二段。",
        "image_keys": ["img_v2_key_a"],
    }
    base.update(overrides)
    return ReviewDraftView(**base)


def _actions(card: dict) -> dict[str, dict]:
    """递归找所有按钮（它们现在在 form 里）。"""
    found: dict[str, dict] = {}

    def walk(elements: list) -> None:
        for element in elements:
            if element.get("tag") == "button":
                found[element["value"]["action"]] = element
            children = element.get("elements") or element.get("actions")
            if isinstance(children, list):
                walk(children)

    walk(card["elements"])
    return found


def test_card_has_all_three_actions():
    actions = _actions(build_review_card(view()))
    assert set(actions) == {ACTION_APPROVE, ACTION_REJECT, ACTION_CANCEL}


def test_card_carries_full_body():
    card = build_review_card(view())
    texts = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    assert any("正文第一段。" in t for t in texts)


def test_card_binds_revision_and_digest():
    actions = _actions(build_review_card(view()))
    value = actions[ACTION_APPROVE]["value"]
    assert value["review_id"] == "rev-1"
    assert value["revision"] == "3"
    assert value["content_digest"] == "deadbeefcafe0123"


def test_card_includes_images():
    card = build_review_card(view(image_keys=["img_v2_a", "img_v2_b"]))
    imgs = [e for e in card["elements"] if e.get("tag") == "img"]
    assert len(imgs) == 2
    assert imgs[0]["img_key"] == "img_v2_a"
    assert imgs[1]["img_key"] == "img_v2_b"


def test_card_without_images_has_no_img_element():
    card = build_review_card(view(image_keys=[]))
    assert [e for e in card["elements"] if e.get("tag") == "img"] == []


def test_card_shows_target_account():
    card = build_review_card(view(target_account_label="内卷树懒"))
    texts = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    assert any("内卷树懒" in t for t in texts)


def test_card_is_json_serializable():
    import json

    json.dumps(build_review_card(view()))


def test_card_has_feedback_input():
    """退回意见输入框。"""
    card = build_review_card(view())
    inputs: list[dict] = []

    def walk(elements: list) -> None:
        for element in elements:
            if element.get("tag") == "input":
                inputs.append(element)
            children = element.get("elements") or element.get("actions")
            if isinstance(children, list):
                walk(children)

    walk(card["elements"])
    assert len(inputs) == 1
    assert inputs[0]["name"] == "feedback"
    assert inputs[0]["max_length"] == 500


def test_buttons_submit_form_so_feedback_is_sent():
    actions = _actions(build_review_card(view()))
    for button in actions.values():
        assert button["action_type"] == "form_submit"


# ------------------------------------------------------------------ 视频卡片

def video_view(**over) -> ReviewDraftView:
    base = {
        "review_id": "rv-v1",
        "draft_id": "d-v1",
        "revision": 1,
        "content_digest": "cafe1234",
        "title": "第一条视频",
        "body": "完整正文都在这里。",
        "image_keys": [],
        "video": VideoInfo(
            duration_ms=26900, width=1920, height=1080,
            byte_size=1614807, keyframe_keys=["img_k1", "img_k2", "img_k3"],
        ),
    }
    base.update(over)
    return ReviewDraftView(**base)


def test_video_card_header_differs():
    card = build_review_card(video_view())
    assert card["header"]["title"]["content"] == "视频待审核"
    assert card["header"]["template"] == "purple"


def test_video_card_has_no_image_block():
    card = build_review_card(video_view(image_keys=["should_be_ignored"]))
    keys = [e.get("img_key") for e in card["elements"] if e.get("tag") == "img"]
    assert keys == ["img_k1", "img_k2", "img_k3"]


def test_video_card_shows_metadata():
    card = build_review_card(video_view())
    texts = " ".join(
        e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"
    )
    assert "0:26" in texts
    assert "1920×1080" in texts
    assert "1.5 MB" in texts


def test_video_card_explains_no_playback_when_no_preview():
    card = build_review_card(video_view())
    notes = [
        "".join(el.get("content", "") for el in e.get("elements", []))
        for e in card["elements"] if e.get("tag") == "note"
    ]
    assert any("无法播放视频" in n for n in notes)


def test_video_card_links_preview_when_available():
    view = video_view()
    view.video.preview_url = "https://example.com/v/1"
    card = build_review_card(view)
    texts = " ".join(
        e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"
    )
    assert "https://example.com/v/1" in texts
    assert "查看完整视频" in texts


def test_video_card_keeps_full_body():
    card = build_review_card(video_view())
    texts = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    assert any("完整正文都在这里" in t for t in texts)


def test_video_card_still_has_three_actions_and_input():
    card = build_review_card(video_view())
    actions = _actions(card)
    assert set(actions) == {ACTION_APPROVE, ACTION_REJECT, ACTION_CANCEL}
    inputs = []

    def walk(elements):
        for e in elements:
            if e.get("tag") == "input":
                inputs.append(e)
            children = e.get("elements") or e.get("actions")
            if isinstance(children, list):
                walk(children)

    walk(card["elements"])
    assert inputs and inputs[0]["name"] == "feedback"


def test_video_info_duration_and_size_format():
    info = VideoInfo(duration_ms=65000, width=1, height=1, byte_size=1048576, keyframe_keys=[])
    assert info.duration_text == "1:05"
    assert info.size_text == "1.0 MB"


def test_video_card_notes_in_chat_video():
    view = video_view()
    view.video.video_message_id = "om_abc"
    card = build_review_card(view)
    notes = [
        "".join(el.get("content", "") for el in e.get("elements", []))
        for e in card["elements"] if e.get("tag") == "note"
    ]
    assert any("上一条消息" in n for n in notes)
    assert not any("需在审核机上确认" in n for n in notes)


def test_preview_url_wins_over_chat_note():
    view = video_view()
    view.video.video_message_id = "om_abc"
    view.video.preview_url = "https://example.com/v"
    card = build_review_card(view)
    texts = " ".join(
        e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"
    )
    assert "https://example.com/v" in texts
