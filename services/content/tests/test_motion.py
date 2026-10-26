"""运镜、转场、版式、逐条出现的测试。

重点锁住 VP-RULE-01（时长守恒）：这是历史上真出过的 bug
（26.9 秒的片子只有 23.0 秒画面），必须有断言防止回归。
"""

from __future__ import annotations

import pytest

from content.video import layout as L
from content.video import motion as M
from content.video import scenes as S


# ------------------------------------------------------------------ 时长守恒

def test_segment_lengths_add_overlap_except_last():
    segs = M.plan_segments([3400, 5000, 4200], ["zoom_in"] * 3, 300)
    assert [s.length_ms for s in segs] == [3700, 5300, 4200]


def test_total_after_overlap_equals_sum_of_holds():
    holds = [3400, 5000, 4200, 2600]
    segs = M.plan_segments(holds, ["none"] * 4, 300)
    total = sum(s.length_ms for s in segs) - 300 * (len(holds) - 1)
    assert total == sum(holds)


def test_single_segment_gets_no_overlap():
    segs = M.plan_segments([2000], ["zoom_in"], 300)
    assert segs[0].length_ms == 2000


def test_zero_transition_keeps_every_length():
    segs = M.plan_segments([1000, 2000], ["none", "none"], 0)
    assert [s.length_ms for s in segs] == [1000, 2000]


def test_mismatched_lengths_rejected():
    with pytest.raises(M.MotionError):
        M.plan_segments([1000], ["none", "none"], 300)


def test_non_positive_hold_rejected():
    with pytest.raises(M.MotionError):
        M.plan_segments([0], ["none"], 300)


def test_unknown_motion_rejected():
    with pytest.raises(M.MotionError):
        M.plan_segments([1000], ["spin"], 300)


# ------------------------------------------------------------------ 滤镜图

def test_filter_has_one_zoompan_per_segment():
    segs = M.plan_segments([1000, 1000, 1000], ["none"] * 3, 300)
    filt, _ = M.build_filter(segs, 1920, 1080, 30, 300)
    assert filt.count("zoompan") == 3


def test_filter_has_n_minus_one_xfades():
    segs = M.plan_segments([1000, 1000, 1000], ["none"] * 3, 300)
    filt, _ = M.build_filter(segs, 1920, 1080, 30, 300)
    assert filt.count("xfade") == 2


def test_xfade_offsets_are_cumulative():
    holds = [3400, 5000, 4200]
    segs = M.plan_segments(holds, ["none"] * 3, 300)
    filt, label = M.build_filter(segs, 1920, 1080, 30, 300)
    import re

    offsets = re.findall(r"offset=([\d.]+)", filt)
    # 第一处 = 3.7-0.3=3.4；第二处 = 3.7+5.3-0.3-0.3=8.4
    assert offsets == ["3.400", "8.400"]
    assert label == "x2"


def test_single_segment_uses_plain_label():
    segs = M.plan_segments([2000], ["zoom_in"], 300)
    filt, label = M.build_filter(segs, 1920, 1080, 30, 300)
    assert label == "v0"
    assert "xfade" not in filt


def test_zero_transition_uses_concat_not_xfade():
    segs = M.plan_segments([1000, 1000], ["none", "none"], 0)
    filt, label = M.build_filter(segs, 1920, 1080, 30, 0)
    assert "concat=n=2" in filt
    assert "xfade" not in filt
    assert label == "out"


def test_transition_longer_than_segment_is_rejected():
    """转场比最短场景还长时，那一屏整段都在淡化，等于没有内容。"""
    with pytest.raises(M.MotionError):
        M.plan_segments([100, 100], ["none", "none"], 300)


def test_empty_segments_rejected():
    with pytest.raises(M.MotionError):
        M.build_filter([], 1920, 1080, 30, 300)


def test_frame_count_matches_segment_length():
    segs = M.plan_segments([1000], ["none"], 0)
    filt, _ = M.build_filter(segs, 1920, 1080, 30, 0)
    assert "d=30" in filt  # 1000ms @ 30fps


@pytest.mark.parametrize("motion", sorted(M.MOTIONS))
def test_every_motion_produces_valid_expression(motion):
    segs = M.plan_segments([1000], [motion], 0)
    filt, _ = M.build_filter(segs, 1920, 1080, 30, 0)
    assert "zoompan" in filt
    assert "z='" in filt


# ------------------------------------------------------------------ 版式默认

def test_default_motion_per_layout():
    assert L.default_motion("card") == M.MOTION_ZOOM_IN
    assert L.default_motion("headline") == M.MOTION_ZOOM_OUT
    assert L.default_motion("closeup") == M.MOTION_PAN_RIGHT
    assert L.default_motion("center_card") == M.MOTION_ZOOM_IN


def test_explicit_motion_wins():
    scene = S.Scene(hold_ms=1000, pose="main", motion="none")
    assert L.resolve_motion(scene) == "none"


def test_transition_defaults_to_fade():
    assert L.resolve_transition(S.Scene(hold_ms=1000)) == "fade"
    assert L.resolve_transition(S.Scene(hold_ms=1000, transition="none")) == "none"


def test_scene_rejects_unknown_layout():
    with pytest.raises(ValueError):
        S.Scene(hold_ms=1000, layout="fancy")


# ------------------------------------------------------------------ 逐条出现

def _board(tmp_path, **scene_over):
    pose = tmp_path / "p.png"
    if not pose.exists():
        from PIL import Image

        Image.new("RGB", (64, 64), (0, 0, 0)).save(pose)
    card = S.Card(title="清单", lines=[
        S.CardLine(text="一", index="1"),
        S.CardLine(text="二", index="2"),
        S.CardLine(text="三", index="3"),
    ])
    over = dict(hold_ms=6000, pose="main", card=card)
    over.update(scene_over)
    return S.Storyboard(scenes=[S.Scene(**over)], assets={"main": str(pose)})


def test_reveal_splits_into_one_scene_per_step(tmp_path):
    board = L.expand_card_reveal(_board(tmp_path, card_reveal=[1, 2, 3]))
    assert len(board.scenes) == 3
    assert [s.visible_lines for s in board.scenes] == [1, 2, 3]


def test_reveal_preserves_total_duration(tmp_path):
    original = _board(tmp_path, card_reveal=[1, 2, 3])
    total_before = sum(s.hold_ms for s in original.scenes)
    expanded = L.expand_card_reveal(original)
    assert sum(s.hold_ms for s in expanded.scenes) == total_before


def test_reveal_remainder_goes_to_last_step(tmp_path):
    board = L.expand_card_reveal(_board(tmp_path, hold_ms=1000, card_reveal=[1, 2, 3]))
    assert [s.hold_ms for s in board.scenes] == [333, 333, 334]


def test_reveal_keeps_full_card_rows(tmp_path):
    """不裁剪行数：裁了卡片会变矮，逐条出现时整块在跳。"""
    board = L.expand_card_reveal(_board(tmp_path, card_reveal=[1]))
    assert len(board.scenes[0].card.lines) == 3


def test_reveal_cleared_after_expansion(tmp_path):
    board = L.expand_card_reveal(_board(tmp_path, card_reveal=[1, 2]))
    assert all(s.card_reveal is None for s in board.scenes)


def test_no_reveal_leaves_scene_untouched(tmp_path):
    board = L.expand_card_reveal(_board(tmp_path))
    assert len(board.scenes) == 1
    assert board.scenes[0].visible_lines is None


def test_reveal_requires_card():
    with pytest.raises(ValueError):
        S.Scene(hold_ms=1000, card_reveal=[1])


def test_reveal_rejects_empty_list():
    card = S.Card(title="t", lines=[S.CardLine(text="a")])
    with pytest.raises(ValueError):
        S.Scene(hold_ms=1000, card=card, card_reveal=[])


# ------------------------------------------------------------------ 反单调检查

def test_audit_flags_single_layout(tmp_path):
    board = S.Storyboard(scenes=[
        S.Scene(hold_ms=2000, pose="main", layout="card"),
        S.Scene(hold_ms=2000, pose="main", layout="card"),
    ], assets={})
    assert any("版式" in note for note in L.audit(board))


def test_audit_flags_long_run_of_same_layout(tmp_path):
    board = S.Storyboard(scenes=[
        S.Scene(hold_ms=1000, pose="main", layout="card"),
        S.Scene(hold_ms=1000, pose="main", layout="card"),
        S.Scene(hold_ms=1000, pose="main", layout="card"),
        S.Scene(hold_ms=1000, pose="main", layout="card"),
        S.Scene(hold_ms=1000, pose="main", layout="headline"),
    ], assets={})
    assert any("连续" in note for note in L.audit(board))


def test_audit_flags_single_pose_for_long_video():
    board = S.Storyboard(scenes=[
        S.Scene(hold_ms=15000, pose="main", layout="card"),
        S.Scene(hold_ms=15000, pose="main", layout="headline"),
    ], assets={})
    assert any("姿势" in note for note in L.audit(board))


def test_audit_passes_for_varied_board():
    board = S.Storyboard(scenes=[
        S.Scene(hold_ms=5000, pose="main", layout="card"),
        S.Scene(hold_ms=5000, pose="point", layout="headline"),
        S.Scene(hold_ms=5000, pose="sleepy", layout="center_card"),
    ], assets={})
    assert L.audit(board) == []
