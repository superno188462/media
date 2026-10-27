"""Seedance 视频生成与视频帧源的测试。

不联网：只测参数组装、校验与本地帧处理。
真实调用需要花钱，不能放在自动化测试里。
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from content.video import petclip as P
from content.video import seedance as S


# ------------------------------------------------------------------ 参数组装

def test_build_content_text_only():
    content = S.build_content("一只树懒在呼吸")
    assert content[0]["type"] == "text"
    assert len(content) == 1


def test_build_content_first_frame_uses_data_uri(tmp_path):
    from PIL import Image

    image = tmp_path / "a.png"
    Image.new("RGB", (8, 8), (200, 180, 150)).save(image)
    content = S.build_content("test", first_frame=image)
    assert content[1]["role"] == "first_frame"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_build_content_reference_images_append_in_order(tmp_path):
    from PIL import Image

    first = tmp_path / "1.png"
    second = tmp_path / "2.png"
    Image.new("RGB", (4, 4), (0, 0, 0)).save(first)
    Image.new("RGB", (4, 4), (255, 255, 255)).save(second)
    content = S.build_content("t", reference_images=[first, second])
    assert [c["role"] for c in content[1:]] == ["reference_image", "reference_image"]


def test_to_data_uri_uses_jpeg_mime_for_jpg(tmp_path):
    from PIL import Image

    image = tmp_path / "a.jpg"
    Image.new("RGB", (4, 4), (1, 1, 1)).save(image)
    assert S.to_data_uri(image).startswith("data:image/jpeg;base64,")


# ------------------------------------------------------------------ 校验

def test_duration_range_enforced():
    with pytest.raises(S.SeedanceError):
        S.create_task("x", duration=2)


def test_ratio_whitelist():
    with pytest.raises(S.SeedanceError):
        S.create_task("x", ratio="2:1")


def test_resolution_whitelist():
    with pytest.raises(S.SeedanceError):
        S.create_task("x", resolution="8k")


def test_empty_prompt_rejected():
    with pytest.raises(S.SeedanceError):
        S.create_task("   ")


def test_missing_key_is_reported(monkeypatch):
    monkeypatch.setenv("VOLC_VIDEO_API_KEY", "")
    monkeypatch.setattr(S, "_CRED_FILE", S.Path("不存在.yaml"))
    with pytest.raises(S.SeedanceError):
        S.create_task("x")


def test_short_model_name_maps_to_id():
    assert S.MODELS["seedance-2.5"] == "doubao-seedance-2-5-260628"


# ------------------------------------------------------------------ 任务状态

def test_task_done_flags():
    assert S.Task("1", "succeeded", "http://x").ok is True
    assert S.Task("1", "failed").done is True
    assert S.Task("1", "running").done is False
    assert S.Task("1", "succeeded").ok is False  # 没有 url


# ------------------------------------------------------------------ 视频帧源

#: ffmpeg 写不了 %TEMP%，测试产物必须放工作区
_TMP_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "pytest-seedance"


@pytest.fixture
def work() -> Path:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    directory = _TMP_ROOT / uuid.uuid4().hex[:12]
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@pytest.mark.skipif(
    not __import__("content.ffmpeg", fromlist=["x"]).available(),
    reason="本机没有 ffmpeg",
)
def test_video_clip_extracts_frames(work):
    from content import ffmpeg as F
    from PIL import Image, ImageDraw

    tmp_path = work
    # 造一段 1 秒的纯色视频
    frame = tmp_path / "src.png"
    img = Image.new("RGB", (320, 400), (200, 180, 150))
    ImageDraw.Draw(img).rectangle([60, 80, 260, 320], fill=(120, 80, 40))
    img.save(frame)
    video = tmp_path / "clip.mp4"
    result = F.run([
        "-loop", "1", "-i", str(frame), "-t", "1", "-r", "10",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
    ])
    if not video.exists():
        pytest.skip(f"生成测试视频失败：{(result.stderr or '')[-200:]}")

    clip = P.VideoClip.load(video, fps=5, height=200)
    assert clip.frame_count >= 4
    assert clip.frames[0].height == 200
    assert clip.frames[0].mode == "RGBA"


def test_video_clip_rejects_missing_file(tmp_path):
    with pytest.raises(P.ClipError):
        P.VideoClip.load(tmp_path / "absent.mp4")
