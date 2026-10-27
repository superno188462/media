"""帧源与宠物配置的测试。

帧源是"动作素材"的抽象：flipbook（生图逐帧）/ static（兜底）/ video（预留）。
配置决定用哪一种，因此这两块都必须能在不跑 ffmpeg 的前提下测。
"""

from __future__ import annotations

import json

import pytest

from content.video import petclip as P
from content.video import petconfig as C


def make_frames(count: int, size: tuple[int, int] = (40, 60)):
    from PIL import Image

    return [
        Image.new("RGBA", size, (index * 20 % 255, 80, 120, 255)) for index in range(count)
    ]


# ------------------------------------------------------------------ 翻页动画

def test_flipbook_cycles_frames():
    clip = P.FlipbookClip(frames=make_frames(3), fps=10, crossfade=0.0)
    first = clip.frame_at(0).getpixel((0, 0))
    later = clip.frame_at(300).getpixel((0, 0))  # 回到第 0 帧
    second = clip.frame_at(100).getpixel((0, 0))
    assert first == later
    assert first != second


def test_flipbook_single_frame_is_static():
    clip = P.FlipbookClip(frames=make_frames(1), fps=10)
    assert clip.frame_at(0) is clip.frame_at(5000)


def test_flipbook_crossfade_blends_between_frames():
    clip = P.FlipbookClip(frames=make_frames(2), fps=10, crossfade=0.5)
    # 单帧 100ms；在 90ms（淡化中段）应得到混合色，不是纯色
    blended = clip.frame_at(90).getpixel((0, 0))
    assert blended not in {clip.frames[0].getpixel((0, 0)), clip.frames[1].getpixel((0, 0))}


def test_flipbook_rejects_empty():
    with pytest.raises(P.ClipError):
        P.FlipbookClip(frames=[])


def test_flipbook_rejects_bad_fps():
    with pytest.raises(P.ClipError):
        P.FlipbookClip(frames=make_frames(2), fps=0)


def test_flipbook_rejects_bad_crossfade():
    with pytest.raises(P.ClipError):
        P.FlipbookClip(frames=make_frames(2), crossfade=1.0)


def test_flipbook_load_sorts_by_name(tmp_path):
    from PIL import Image

    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(tmp_path / "02.png")
    Image.new("RGBA", (10, 10), (0, 255, 0, 255)).save(tmp_path / "00.png")
    Image.new("RGBA", (10, 10), (0, 0, 255, 255)).save(tmp_path / "01.png")
    clip = P.FlipbookClip.load(tmp_path, crossfade=0.0, fps=10)
    assert clip.frame_at(0).getpixel((0, 0))[0] == 0     # 00.png 是绿色
    assert clip.frame_at(100).getpixel((0, 0))[2] == 255  # 01.png 是蓝色


def test_flipbook_load_rejects_empty_dir(tmp_path):
    with pytest.raises(P.ClipError):
        P.FlipbookClip.load(tmp_path)


def test_flipbook_load_rejects_mixed_sizes(tmp_path):
    from PIL import Image

    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(tmp_path / "00.png")
    Image.new("RGBA", (20, 10), (0, 255, 0, 255)).save(tmp_path / "01.png")
    with pytest.raises(P.ClipError):
        P.FlipbookClip.load(tmp_path)


def test_flipbook_load_resizes_to_target_height(tmp_path):
    from PIL import Image

    Image.new("RGBA", (100, 200), (255, 0, 0, 255)).save(tmp_path / "00.png")
    clip = P.FlipbookClip.load(tmp_path, height=100)
    assert clip.frames[0].height == 100


# ------------------------------------------------------------------ 其它帧源

def test_static_clip_always_returns_same_image(tmp_path):
    from PIL import Image

    path = tmp_path / "a.png"
    Image.new("RGBA", (30, 40), (10, 20, 30, 255)).save(path)
    clip = P.StaticClip.load(path)
    assert clip.frame_count == 1
    assert clip.frame_at(0) is clip.frame_at(99999)


def test_video_clip_rejects_missing_file(tmp_path):
    """视频帧源已实现（Seedance 可用后接通）；文件缺失要明确报错。"""
    with pytest.raises(P.ClipError) as exc:
        P.VideoClip.load(tmp_path / "a.mp4")
    assert "视频不存在" in str(exc.value)


def test_build_clip_dispatch(tmp_path):
    from PIL import Image

    Image.new("RGBA", (10, 10), (1, 2, 3, 255)).save(tmp_path / "00.png")
    assert isinstance(P.build_clip("flipbook", directory=tmp_path), P.FlipbookClip)
    assert isinstance(
        P.build_clip("static", path=tmp_path / "00.png"), P.StaticClip
    )


def test_build_clip_rejects_unknown_source():
    with pytest.raises(P.ClipError):
        P.build_clip("hologram")


def test_build_clip_requires_target():
    with pytest.raises(P.ClipError):
        P.build_clip("flipbook")


# ------------------------------------------------------------------ 配置

def test_config_defaults_are_flipbook():
    config = C.PetConfig(clips={"idle": "x"})
    assert config.enabled is True
    assert config.source == P.SOURCE_FLIPBOOK
    assert config.size == 420


def test_bare_default_config_is_invalid():
    """没有 idle 帧的 flipbook 配置必须直接失败，不能跑到合成时才炸。"""
    with pytest.raises(C.ConfigError):
        C.PetConfig()


def test_config_requires_idle_for_flipbook():
    with pytest.raises(C.ConfigError):
        C.PetConfig(clips={})


def test_config_allows_missing_idle_when_disabled():
    assert C.PetConfig(enabled=False, clips={}).enabled is False


def test_config_rejects_unknown_source():
    with pytest.raises(C.ConfigError):
        C.PetConfig(source="hologram", clips={"idle": "x"})


def test_config_rejects_bad_size():
    with pytest.raises(C.ConfigError):
        C.PetConfig(size=10, clips={"idle": "x"})


def test_config_rejects_bad_trigger_ratio():
    with pytest.raises(C.ConfigError):
        C.PetConfig(trigger_ratio=0, clips={"idle": "x"})


def test_config_resolves_relative_clip_paths(tmp_path):
    config_path = tmp_path / "pet.json"
    config_path.write_text(
        json.dumps({"pet": {"source": "flipbook", "clips": {"idle": "frames"}}}),
        encoding="utf-8",
    )
    config = C.PetConfig.load(config_path)
    assert config.clips["idle"].endswith("frames")
    assert str(tmp_path) in config.clips["idle"]


def test_config_load_rejects_missing_file(tmp_path):
    with pytest.raises(C.ConfigError):
        C.PetConfig.load(tmp_path / "absent.json")


def test_config_load_rejects_bad_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(C.ConfigError):
        C.PetConfig.load(path)


def test_config_to_dict_roundtrip():
    original = C.PetConfig(clips={"idle": "a"}, size=500, seed=7)
    again = C.PetConfig.from_dict({"pet": original.to_dict()})
    assert again.size == 500
    assert again.seed == 7


def test_config_wander_rect_is_normalized():
    config = C.PetConfig(clips={"idle": "a"}, wander_area=(0.5, 0.1, 0.4, 0.8))
    rect = config.wander_rect(1000, 500)
    assert (rect.x, rect.y, rect.w, rect.h) == (500, 50, 400, 400)


def test_config_protected_rects():
    config = C.PetConfig(clips={"idle": "a"}, protected_zones=[(1, 2, 3, 4)])
    rects = config.protected_rects()
    assert (rects[0].x, rects[0].y, rects[0].w, rects[0].h) == (1, 2, 3, 4)


def test_config_build_clip_falls_back_to_idle(tmp_path):
    from PIL import Image

    frames = tmp_path / "frames"
    frames.mkdir()
    Image.new("RGBA", (10, 10), (0, 0, 0, 255)).save(frames / "00.png")
    config = C.PetConfig(clips={"idle": str(frames)})
    assert isinstance(config.build_clip("wave"), P.FlipbookClip)
