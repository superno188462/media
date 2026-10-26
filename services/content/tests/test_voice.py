"""配音规划与音轨拼接的测试。

规划部分用假的合成/探测函数，不联网；
音轨拼接用真实 ffmpeg，缺失时跳过。
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from content import ffmpeg as F
from content.video import scenes as S
from content.video import voice as V

_TMP_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "pytest-voice"


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


def _png(path: Path) -> Path:
    from PIL import Image

    Image.new("RGB", (320, 180), (20, 40, 80)).save(path)
    return path


def _board(tmp_path: Path, holds=(0, 0, 1200)) -> S.Storyboard:
    pose = tmp_path / "pose.png"
    if not pose.exists():
        _png(pose)
    return S.Storyboard(
        scenes=[
            S.Scene(hold_ms=holds[0], caption="第一句话", pose="main"),
            S.Scene(hold_ms=holds[1], caption="第二句话", pose="main"),
            S.Scene(hold_ms=holds[2], outro="完", outro_sub="下期见", pose="main"),
        ],
        assets={"main": str(pose)},
    )


# ------------------------------------------------------------------ 台词

def test_scene_text_uses_caption(tmp_path):
    board = _board(tmp_path)
    assert V.scene_text(board.scenes[0]) == "第一句话"


def test_scene_text_joins_outro_parts(tmp_path):
    board = _board(tmp_path)
    assert V.scene_text(board.scenes[2]) == "完。下期见"


def test_scene_text_empty_without_dialogue(tmp_path):
    board = _board(tmp_path)
    assert V.scene_text(S.Scene(hold_ms=1000, pose="main")) == ""


# ------------------------------------------------------------------ 规划

def test_plan_uses_audio_duration(tmp_path, work):
    board = _board(tmp_path)
    calls: list[str] = []

    def fake_synth(text, path):
        calls.append(text)
        Path(path).write_bytes(b"fake")
        return Path(path)

    # 按文件名里的序号返回语音时长：001=2000, 002=800, 003=1500
    durations = {"001": 2000, "002": 800, "003": 1500}

    def fake_probe(path):
        stem = Path(path).stem  # voice_001
        return durations[stem.split("_")[-1]]

    voices = V.plan(
        board, work,
        gap_ms=400,
        synthesize_fn=fake_synth,
        probe_fn=fake_probe,
    )

    assert calls == ["第一句话", "第二句话", "完。下期见"]
    assert len(voices) == 3
    # 第一场：语音 2000 + 400 留白
    assert voices[0].audio_ms == 2000
    assert voices[0].hold_ms == 2400
    # 第二场：语音 800 + 400
    assert voices[1].hold_ms == 1200
    # 第三场：手写 1200 比语音 1500 短 → 取语音 + 400
    assert voices[2].hold_ms == 1900


def test_plan_keeps_longer_manual_hold(tmp_path, work):
    board = _board(tmp_path, holds=(5000, 100, 100))

    def fake_synth(text, path):
        Path(path).write_bytes(b"fake")
        return Path(path)

    voices = V.plan(
        board, work, gap_ms=100,
        synthesize_fn=fake_synth,
        probe_fn=lambda p: 500,
    )
    # 手写 5000 比语音 500 长 → 保留 5000 + 100
    assert voices[0].hold_ms == 5100


def test_plan_keeps_scene_without_dialogue(tmp_path, work):
    pose = tmp_path / "pose.png"
    _png(pose)
    board = S.Storyboard(
        scenes=[S.Scene(hold_ms=1500, pose="main")],
        assets={"main": str(pose)},
    )

    def fake_synth(text, path):  # 不该被调用
        raise AssertionError("没有台词的镜头不应合成语音")

    voices = V.plan(board, work, synthesize_fn=fake_synth, probe_fn=lambda p: 0)
    assert voices[0].hold_ms == 1500
    assert voices[0].audio is None


def test_plan_raises_when_probe_fails(tmp_path, work):
    board = _board(tmp_path)

    def fake_synth(text, path):
        Path(path).write_bytes(b"fake")
        return Path(path)

    with pytest.raises(V.tts_tool.TtsError):
        V.plan(board, work, synthesize_fn=fake_synth, probe_fn=lambda p: None)


# ------------------------------------------------------------------ 音轨

@pytest.mark.skipif(not HAVE_FFMPEG, reason="本机没有 ffmpeg")
def test_build_track_concatenates_with_gaps(tmp_path, work):
    board = _board(tmp_path)

    def fake_synth(text, path):
        # 每段 1 秒真静音，让 ffmpeg 能处理
        F.run(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
               "-t", "1", str(path)])
        return Path(path)

    voices = V.plan(board, work / "voice", gap_ms=300,
                    synthesize_fn=fake_synth,
                    probe_fn=lambda p: F.probe_duration_ms(Path(p)))
    track = V.build_track(voices, work / "voice" / "track.mp3",
                          gap_ms=300, work_dir=work / "voice")

    assert track.is_file()
    total = sum(v.hold_ms for v in voices)
    measured = F.probe_duration_ms(track)
    assert measured is not None
    # 允许编码误差
    assert abs(measured - total) < 600
