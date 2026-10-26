"""ffmpeg 定位与探测的测试。

两点约定：

1. 不假设二进制一定存在：缺失时相应用例跳过，测试在任何机器上都能跑。
2. **临时文件放在 ``services/content/.runtime/``**。实测 ffmpeg 作为子进程
   无法写入 ``.local/``（Permission denied），而工作区其他位置可以；
   ``services/**/.runtime/`` 已在 .gitignore 中覆盖。
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from content import ffmpeg as F

#: 测试临时目录：内容服务的运行区，已 gitignore。
_TMP_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "pytest-tmp"


@pytest.fixture
def work() -> Path:
    """工作区内的临时目录，供 ffmpeg 真正写文件。"""
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    directory = _TMP_ROOT / uuid.uuid4().hex[:12]
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _real_ffmpeg() -> Path | None:
    try:
        return F.find()
    except F.FfmpegNotFound:
        return None


HAVE_FFMPEG = _real_ffmpeg() is not None


# ------------------------------------------------------------------ 定位

def test_env_override_wins(monkeypatch, tmp_path):
    fake = tmp_path / "ffmpeg.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("FFMPEG", str(fake))
    assert F.find() == fake


def test_env_override_missing_file_fails_loud(monkeypatch, tmp_path):
    monkeypatch.setenv("FFMPEG", str(tmp_path / "nope.exe"))
    with pytest.raises(F.FfmpegNotFound) as exc:
        F.find()
    assert "不存在" in str(exc.value)


def test_empty_env_is_ignored(monkeypatch):
    monkeypatch.setenv("FFMPEG", "   ")
    try:
        F.find()
    except F.FfmpegNotFound:
        pytest.skip("本机没有可用的 ffmpeg")


def test_error_message_names_the_three_options(monkeypatch, tmp_path):
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.setattr(F, "_RUNTIME_DIR", tmp_path / "absent")
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(F.FfmpegNotFound) as exc:
        F.find()
    message = str(exc.value)
    assert "FFMPEG" in message
    assert ".runtime/ffmpeg" in message
    assert "apt-get" in message  # 容器里的做法也写进了提示


def test_available_reflects_presence(monkeypatch, tmp_path):
    monkeypatch.setenv("FFMPEG", str(tmp_path / "nope.exe"))
    assert F.available() is False


# ------------------------------------------------------------------ 探测

@pytest.mark.skipif(not HAVE_FFMPEG, reason="本机没有 ffmpeg")
def test_probe_audio(work):
    out = work / "silence.mp3"
    result = F.run(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "1", str(out)])
    assert out.exists(), result.stderr[-400:]

    info = F.probe(out)
    assert info["has_audio"] is True
    assert info["has_video"] is False
    assert info["sample_rate"] == 24000
    assert info["duration_ms"] is not None
    assert 900 <= info["duration_ms"] <= 1200


@pytest.mark.skipif(not HAVE_FFMPEG, reason="本机没有 ffmpeg")
def test_probe_duration_returns_int(work):
    out = work / "s.wav"
    F.run(["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "2", str(out)])
    duration = F.probe_duration_ms(out)
    assert duration is not None
    assert 1900 <= duration <= 2200


@pytest.mark.skipif(not HAVE_FFMPEG, reason="本机没有 ffmpeg")
def test_probe_missing_file_returns_empty_fields(work):
    info = F.probe(work / "absent.mp3")
    assert info["duration_ms"] is None
    assert info["has_audio"] is False
    assert info["has_video"] is False


def test_probe_duration_without_ffmpeg_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("FFMPEG", str(tmp_path / "nope.exe"))
    assert F.probe_duration_ms(tmp_path / "x.mp3") is None
