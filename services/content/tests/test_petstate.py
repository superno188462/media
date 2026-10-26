"""动作状态机的测试。

状态机的职责是产出「逐帧该播哪个动作」，所以它的输出必须：
- 帧数与时长一致
- 从 idle 开始
- 被拖走的帧强制变成 grab
- 同种子可复现、不同种子有差异
"""

from __future__ import annotations

import pytest

from content.video import petstate as S


def specs(**over) -> dict[str, S.ActionSpec]:
    raw = {
        "idle": {"weight": 5.0, "duration": [3000, 7000]},
        "wave": {"weight": 1.5, "duration": [2000, 3500]},
        "eat": {"weight": 1.2, "duration": [4000, 7000]},
    }
    raw.update(over)
    return S.parse_specs(raw)


# ------------------------------------------------------------------ 配置解析

def test_parse_defaults_when_empty():
    parsed = S.parse_specs(None)
    assert "idle" in parsed


def test_parse_rejects_missing_idle():
    with pytest.raises(S.ActionError):
        S.parse_specs({"wave": {"weight": 1, "duration": [1000, 2000]}})


def test_parse_rejects_non_positive_weight():
    with pytest.raises(S.ActionError):
        S.parse_specs({"idle": {"weight": 0, "duration": [1000, 2000]}})


def test_parse_rejects_inverted_duration():
    with pytest.raises(S.ActionError):
        S.parse_specs({"idle": {"weight": 1, "duration": [5000, 1000]}})


def test_parse_rejects_wrong_duration_arity():
    with pytest.raises(S.ActionError):
        S.parse_specs({"idle": {"weight": 1, "duration": [1000]}})


def test_parse_applies_default_duration():
    parsed = S.parse_specs({"idle": {"weight": 1}})
    assert parsed["idle"].duration_ms[0] > 0


# ------------------------------------------------------------------ 规划

def test_plan_length_matches_duration():
    plan = S.plan_actions(4000, fps=30, specs=specs(), seed=1)
    assert len(plan.actions) == 120


def test_plan_starts_with_idle():
    plan = S.plan_actions(6000, fps=30, specs=specs(), seed=1)
    assert plan.actions[0] == "idle"


def test_plan_empty_duration():
    plan = S.plan_actions(0, fps=30, specs=specs(), seed=1)
    assert plan.actions == []


def test_plan_is_deterministic_for_same_seed():
    a = S.plan_actions(20000, fps=30, specs=specs(), seed=42).actions
    b = S.plan_actions(20000, fps=30, specs=specs(), seed=42).actions
    assert a == b


def test_plan_differs_across_seeds():
    a = S.plan_actions(30000, fps=30, specs=specs(), seed=1).actions
    b = S.plan_actions(30000, fps=30, specs=specs(), seed=9).actions
    assert a != b


def test_plan_only_uses_available_actions():
    plan = S.plan_actions(
        30000, fps=30, specs=specs(), seed=3, available={"idle", "wave"}
    )
    assert set(plan.actions) <= {"idle", "wave"}


def test_plan_falls_back_to_idle_when_idle_is_only_available():
    plan = S.plan_actions(
        10000, fps=30, specs=specs(), seed=3, available={"idle"}
    )
    assert set(plan.actions) == {"idle"}


def test_drag_frames_become_grab():
    # 5000ms @30fps = 150 帧；前 60 帧正常，中间 30 帧被拖，后面 60 帧恢复
    flags = [False] * 60 + [True] * 30 + [False] * 60
    plan = S.plan_actions(
        5000, fps=30, specs=specs(), seed=2, drag_flags=flags
    )
    assert len(plan.actions) == 150
    assert plan.actions[59] != S.GRAB_ACTION
    assert plan.actions[60] == S.GRAB_ACTION
    assert plan.actions[89] == S.GRAB_ACTION
    assert plan.actions[90] != S.GRAB_ACTION


def test_drag_flags_length_mismatch_rejected():
    with pytest.raises(S.ActionError):
        S.plan_actions(
            4000, fps=30, specs=specs(), seed=2, drag_flags=[True]
        )


def test_summary_percentages_sum_to_about_100():
    plan = S.plan_actions(30000, fps=30, specs=specs(), seed=5)
    total = sum(plan.summary()["actions"].values())
    assert 99.0 <= total <= 101.0


def test_action_at_frame_clamps():
    plan = S.plan_actions(1000, fps=30, specs=specs(), seed=1)
    assert plan.action_at_frame(99999) == plan.actions[-1]
