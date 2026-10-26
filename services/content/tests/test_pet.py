"""角色游走、被拖走、分层合成的测试。

pet.py 是纯逻辑（不碰像素），composite.py 的时间轴计算也是纯函数，
所以大部分用例不需要 ffmpeg。
"""

from __future__ import annotations

import pytest

from content.video import composite as C
from content.video import pet as P


STAGE = P.Rect(0, 0, 1920, 1080)
WANDER = P.Rect(700, 100, 1120, 960)
PROTECTED = [P.Rect(90, 180, 880, 700), P.Rect(300, 900, 1320, 140)]
PET = (420, 420)


def planner(seed: int = 7, **over) -> P.PetPlanner:
    kwargs = dict(seed=seed, fps=30, stage=STAGE, pet_size=PET,
                  wander=WANDER, protected=PROTECTED)
    kwargs.update(over)
    return P.PetPlanner(**kwargs)


# ------------------------------------------------------------------ 矩形

def test_overlap_area_of_disjoint_rects_is_zero():
    assert P.Rect(0, 0, 10, 10).overlap_area(P.Rect(50, 50, 10, 10)) == 0


def test_overlap_area_computes_intersection():
    assert P.Rect(0, 0, 20, 20).overlap_area(P.Rect(10, 10, 20, 20)) == 100


def test_overlaps_ignores_touching_edges():
    """刚好贴边不算重叠，否则角色会一直在边界被拖。"""
    assert not P.Rect(0, 0, 10, 10).overlaps(P.Rect(10, 0, 10, 10))


def test_clamp_to_keeps_rect_inside():
    clamped = P.Rect(-50, -50, 100, 100).clamp_to(P.Rect(0, 0, 1920, 1080))
    assert (clamped.x, clamped.y) == (0, 0)


# ------------------------------------------------------------------ 游走

def test_same_seed_produces_same_path():
    a = planner(seed=42).frames(4000)
    b = planner(seed=42).frames(4000)
    assert [(f.x, f.y, f.dragging) for f in a] == [(f.x, f.y, f.dragging) for f in b]


def test_different_seeds_differ():
    a = planner(seed=1).frames(4000)
    b = planner(seed=2).frames(4000)
    assert [(f.x, f.y) for f in a] != [(f.x, f.y) for f in b]


def test_frame_count_matches_duration():
    frames = planner().frames(3000)
    assert len(frames) == 90  # 3 秒 × 30fps


def test_zero_duration_returns_nothing():
    assert planner().frames(0) == []


def test_pet_stays_within_wander_area():
    for frame in planner(seed=3).frames(20000):
        assert WANDER.x <= frame.x <= WANDER.right - PET[0]
        # y 允许浮动叠加，放宽一个浮动幅度
        assert WANDER.y - P.BOB_AMPLITUDE <= frame.y <= WANDER.bottom - PET[1] + P.BOB_AMPLITUDE


def test_pet_actually_moves():
    frames = planner(seed=5).frames(12000)
    xs = {f.x for f in frames}
    ys = {f.y for f in frames}
    assert len(xs) > 5 and len(ys) > 5


def test_tilt_is_small():
    for frame in planner(seed=5).frames(8000):
        assert abs(frame.angle) <= P.TILT_AMPLITUDE + 1e-6


# ------------------------------------------------------------------ 被拖走

def test_drag_triggers_when_deeply_overlapping():
    """角色整个压在卡片上时必然触发拖拽。"""
    inside = P.Rect(300, 300, 420, 420)  # 完全落在卡片区内
    assert planner(seed=1, wander=inside).frames(1000)[0].dragging is True


def test_light_grazing_does_not_trigger():
    """只有轻微重叠（低于阈值）时不拖。"""
    zone = P.Rect(0, 0, 400, 400)
    graze = P.Rect(380, 380, 420, 420)  # 只压上 20×20 = 400，约 0.2%
    p = planner(seed=1, wander=graze, protected=[zone])
    assert p.frames(800)[0].dragging is False


def test_drag_event_count_is_reported():
    frames = planner(seed=7).frames(36000)
    summary = planner(seed=7).summary(frames)
    assert summary["seed"] == 7
    assert summary["frames"] == len(frames)
    assert summary["drag_events"] >= 0
    assert 0 <= summary["drag_frame_ratio_pct"] <= 100


def test_escape_point_is_outside_protected():
    p = planner(seed=1)
    box = P.Rect(400, 400, 420, 420)  # 压在卡片上
    x, y = p._escape_point(box)
    assert not p._violates(P.Rect(int(x), int(y), *PET))


# ------------------------------------------------------------------ 时间轴

def test_scene_at_maps_time_to_scene():
    # 边界：0–1000 第 0 屏，1000–3000 第 1 屏，3000–6000 第 2 屏
    holds = [1000, 2000, 3000]
    assert C.scene_at(0, holds) == (0, 0)
    assert C.scene_at(1500, holds)[0] == 1
    assert C.scene_at(2500, holds)[0] == 1
    assert C.scene_at(3500, holds)[0] == 2
    # 超出总时长时归到最后一屏
    assert C.scene_at(99999, holds)[0] == 2


def test_blend_weight_zero_outside_transition():
    holds = [2000, 2000]
    assert C.blend_weight(500, holds, 300) == (0, 0, 0.0)


def test_blend_weight_rises_near_boundary():
    holds = [2000, 2000]
    _, upcoming, weight = C.blend_weight(1900, holds, 300)
    assert upcoming == 1
    assert 0 < weight <= 1


def test_blend_weight_is_zero_on_last_scene():
    holds = [2000, 2000]
    assert C.blend_weight(3900, holds, 300) == (1, 1, 0.0)


def test_blend_weight_without_transition_never_blends():
    holds = [2000, 2000]
    assert C.blend_weight(1950, holds, 0) == (0, 0, 0.0)


# ------------------------------------------------------------------ 合成守卫

def test_composite_rejects_length_mismatch(tmp_path):
    with pytest.raises(C.CompositeError):
        C.compose_layers([tmp_path / "a.png"], [1000, 2000], tmp_path / "o.mp4")


def test_composite_rejects_missing_background(tmp_path):
    with pytest.raises(C.CompositeError):
        C.compose_layers([tmp_path / "absent.png"], [1000], tmp_path / "o.mp4")


def test_composite_rejects_short_track(tmp_path):
    from PIL import Image

    bg = tmp_path / "bg.png"
    Image.new("RGB", (320, 180), (0, 0, 0)).save(bg)
    with pytest.raises(C.CompositeError):
        C.compose_layers([bg], [2000], tmp_path / "o.mp4", pet_frames=[], size=(320, 180))
