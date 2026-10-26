"""视频模块的测试。

不依赖 Playwright 与 ffmpeg 的部分全部覆盖；依赖二进制的用例缺失时跳过。
临时文件写在 ``services/content/.runtime/``（ffmpeg 无法写 .local）。
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from content import ffmpeg as F
from content.video import scenes as S
from content.video import template as T
from content.video.compose import ComposeError, _write_concat, compose

_TMP_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "pytest-video"


@pytest.fixture
def work() -> Path:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    directory = _TMP_ROOT / uuid.uuid4().hex[:12]
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _real_ffmpeg() -> bool:
    try:
        F.find()
        return True
    except F.FfmpegNotFound:
        return False


HAVE_FFMPEG = _real_ffmpeg()


def _png(path: Path, color: tuple[int, int, int] = (30, 60, 120)) -> Path:
    from PIL import Image

    Image.new("RGB", (640, 360), color).save(path)
    return path


def storyboard(tmp_path: Path, **over) -> S.Storyboard:
    pose = tmp_path / "pose.png"
    if not pose.exists():
        _png(pose)
    base = dict(
        scenes=[
            S.Scene(hold_ms=2000, caption="第一句", pose="main", badge="Day 0"),
            S.Scene(hold_ms=1500, caption="第二句", pose="main"),
        ],
        assets={"main": str(pose)},
    )
    base.update(over)
    return S.Storyboard(**base)


# ------------------------------------------------------------------ 分镜

def test_storyboard_roundtrip(tmp_path):
    board = storyboard(tmp_path)
    path = tmp_path / "s.json"
    board.save(path)

    loaded = S.Storyboard.load(path)
    assert len(loaded.scenes) == 2
    assert loaded.scenes[0].caption == "第一句"
    assert loaded.total_ms == 3500
    assert loaded.assets == board.assets


def test_scene_allows_zero_hold_meaning_from_audio():
    """hold_ms=0 表示「由配音决定」，是合法值。"""
    scene = S.Scene(hold_ms=0, caption="有台词")
    assert scene.has_dialogue is True


def test_scene_rejects_negative_hold():
    with pytest.raises(ValueError):
        S.Scene(hold_ms=-1)


def test_validate_flags_zero_hold_without_dialogue(tmp_path):
    board = storyboard(tmp_path)
    board.scenes.append(S.Scene(hold_ms=0, pose="main"))
    assert any("无法由配音推算" in p for p in board.validate())


def test_cardline_rejects_unknown_state():
    with pytest.raises(ValueError):
        S.CardLine(text="x", state="weird")


def test_validate_flags_missing_pose_asset(tmp_path):
    board = storyboard(tmp_path)
    board.scenes.append(S.Scene(hold_ms=1000, pose="nope"))
    problems = board.validate()
    assert any("未定义的立绘" in p for p in problems)


def test_validate_flags_missing_file(tmp_path):
    board = storyboard(tmp_path, assets={"main": str(tmp_path / "absent.png")})
    problems = board.validate()
    assert any("文件不存在" in p for p in problems)


def test_validate_flags_empty_storyboard():
    assert S.Storyboard(scenes=[]).validate() == ["没有任何镜头"]


def test_validate_flags_scene_without_visual(tmp_path):
    board = storyboard(tmp_path)
    board.scenes.append(S.Scene(hold_ms=1000))
    assert any("既没有立绘" in p for p in board.validate())


def test_validate_flags_over_ten_minutes(tmp_path):
    board = storyboard(tmp_path)
    board.scenes.append(S.Scene(hold_ms=600_001, pose="main"))
    assert any("超过契约上限" in p for p in board.validate())


def test_validate_passes_for_good_storyboard(tmp_path):
    assert storyboard(tmp_path).validate() == []


def test_from_dict_parses_card(tmp_path):
    data = storyboard(tmp_path).to_dict()
    data["scenes"][0]["card"] = {
        "title": "三条规矩",
        "lines": [
            {"text": "日更打卡", "state": "active", "index": "1"},
            {"text": "第三条", "state": "pending"},
        ],
    }
    loaded = S.Storyboard.from_dict(data)
    card = loaded.scenes[0].card
    assert card is not None
    assert card.title == "三条规矩"
    assert card.lines[0].state == "active"
    assert card.lines[1].state == "pending"


# ------------------------------------------------------------------ 模板

def test_html_contains_caption_and_badge(tmp_path):
    board = storyboard(tmp_path)
    html = T.render_html(board, board.scenes[0])
    assert "第一句" in html
    assert "Day 0" in html
    assert board.brand in html
    assert board.disclaimer in html


def test_html_embeds_pose_as_data_uri(tmp_path):
    board = storyboard(tmp_path)
    html = T.render_html(board, board.scenes[0])
    assert "data:image/png;base64," in html


def test_html_renders_card_states(tmp_path):
    board = storyboard(tmp_path)
    scene = S.Scene(
        hold_ms=1000, pose="main",
        card=S.Card(title="规矩", lines=[
            S.CardLine(text="一", state="done", index="1"),
            S.CardLine(text="二", state="active", index="2"),
            S.CardLine(text="三", state="pending", index="3"),
        ]),
    )
    html = T.render_html(board, scene)
    assert 'class="line done"' in html
    assert 'class="line active"' in html
    assert 'class="line pending"' in html


def test_html_escapes_user_text(tmp_path):
    board = storyboard(tmp_path)
    scene = S.Scene(hold_ms=1000, pose="main", caption="<script>alert(1)</script>")
    html = T.render_html(board, scene)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_outro_replaces_caption(tmp_path):
    board = storyboard(tmp_path)
    scene = S.Scene(hold_ms=1000, pose="main", caption="不该出现",
                    outro="Day 0 完", outro_sub="下期见")
    html = T.render_html(board, scene)
    assert "Day 0 完" in html
    assert "下期见" in html
    assert "不该出现" not in html


def test_title_block_renders(tmp_path):
    board = storyboard(tmp_path)
    scene = S.Scene(hold_ms=1000, pose="main",
                    title_block={"title": "来自深海的", "main": "树懒", "sub": "AI"})
    html = T.render_html(board, scene)
    assert "来自深海的" in html and "树懒" in html and "title-block" in html


# ------------------------------------------------------------------ 合成

def test_concat_file_lists_every_frame_with_duration(work):
    frames = [_png(work / "a.png"), _png(work / "b.png")]
    target = work / "concat.txt"
    _write_concat(frames, [2000, 1500], target)
    text = target.read_text(encoding="utf-8")
    assert "duration 2.000" in text
    assert "duration 1.500" in text
    # 末尾补一次末帧、时长给单帧：不补会丢掉最后一段 duration，
    # 实测 26.9 秒的片子只有 23.0 秒画面。
    assert text.count(frames[-1].name) == 2
    assert "duration 0.0333" in text


def test_concat_rejects_mismatched_lengths(work):
    frames = [_png(work / "a.png")]
    with pytest.raises(ComposeError):
        _write_concat(frames, [1000, 2000], work / "c.txt")


def test_compose_rejects_empty_frames(work):
    with pytest.raises(ComposeError):
        compose([], [], work / "out.mp4")


def test_compose_rejects_missing_frame(work):
    with pytest.raises(ComposeError):
        compose([work / "absent.png"], [1000], work / "out.mp4")


@pytest.mark.skipif(not HAVE_FFMPEG, reason="本机没有 ffmpeg")
def test_compose_makes_video(work):
    frames = [_png(work / "a.png"), _png(work / "b.png", (120, 30, 30))]
    result = compose(frames, [1000, 1000], work / "out.mp4", work_dir=work)
    assert result.path.is_file()
    assert result.bytes > 0
    assert result.frames == 2
    assert result.has_audio is False
    assert 1800 <= (result.duration_ms or 0) <= 2600


@pytest.mark.skipif(not HAVE_FFMPEG, reason="本机没有 ffmpeg")
def test_compose_total_duration_matches_holds(work):
    """回归：concat 丢末帧时长会让画面比音轨短。"""
    f = _png(work / "a.png")
    holds = [1500, 2000, 2500, 3000, 3500]
    result = compose([f] * 5, holds, work / "out.mp4", work_dir=work)
    assert abs((result.duration_ms or 0) - sum(holds)) < 200


@pytest.mark.skipif(not HAVE_FFMPEG, reason="本机没有 ffmpeg")
def test_compose_with_audio(work):
    frames = [_png(work / "a.png")]
    audio = work / "a.mp3"
    F.run(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "1", str(audio)])
    result = compose(frames, [1000], work / "out.mp4", audio=audio, work_dir=work)
    assert result.has_audio is True
