"""视频投稿分支的测试。

只测纯函数与预览，**不调用 bili**（``upload video`` 没有 dry-run，
调用就等于真上传）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 脚本不在包里，按路径导入
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import publish_job as P  # noqa: E402


# ------------------------------------------------------------------ 判定

def test_is_video_by_manifest_key():
    assert P.is_video({"video": "a.mp4"}) is True
    assert P.is_video({"images": ["a.png"]}) is False
    assert P.is_video({}) is False


@pytest.mark.parametrize("value", ["private", "PRIVATE", "self"])
def test_is_private_accepts_variants(value):
    assert P.is_private({"visibility": value}) is True


@pytest.mark.parametrize("value", ["public", "", None])
def test_is_private_rejects_others(value):
    assert P.is_private({"visibility": value}) is False


# ------------------------------------------------------------------ 标签

def test_extract_tags_from_body_hashtags():
    assert P.extract_tags({"body": "正文 #AI #技术"}) == ["AI", "技术"]


def test_extract_tags_dedupes_in_order():
    assert P.extract_tags({"body": "#AI #AI #技术"}) == ["AI", "技术"]


def test_extract_tags_falls_back_when_none():
    assert P.extract_tags({"body": "没有标签"}) == P.FALLBACK_TAGS


def test_extract_tags_caps_at_ten():
    body = " ".join("#t%d" % i for i in range(20))
    tags = P.extract_tags({"body": body})
    assert len(tags) == P.MAX_TAGS


def test_explicit_tags_win_over_body():
    tags = P.extract_tags({"body": "#忽略", "tags": ["甲", "乙"]})
    assert tags == ["甲", "乙"]


def test_extract_tags_ignores_blank_entries():
    assert P.extract_tags({"body": "x", "tags": [" ", "真标签"]}) == ["真标签"]


# ------------------------------------------------------------------ 参数

def test_build_video_args_has_required_flags(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    args, body_file = P.build_video_args(
        str(video), "标题", ["AI", "技术"], "正文", private=False
    )
    try:
        assert args[0:3] == ["upload", "video", str(video)]
        assert "--title" in args and "标题" in args
        assert args.count("--tag") == 2
        assert "--ai-declare" in args
        assert "--private" not in args
        assert "--desc-file" in args
        assert Path(body_file).read_text(encoding="utf-8") == "正文"
    finally:
        body_file.unlink(missing_ok=True)


def test_build_video_args_adds_private(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    args, body_file = P.build_video_args(str(video), "t", ["AI"], "b", private=True)
    try:
        assert "--private" in args
    finally:
        body_file.unlink(missing_ok=True)


def test_build_video_args_adds_cover(tmp_path):
    video = tmp_path / "v.mp4"
    cover = tmp_path / "c.jpg"
    video.write_bytes(b"x")
    cover.write_bytes(b"x")
    args, body_file = P.build_video_args(
        str(video), "t", ["AI"], "b", private=False, cover=str(cover)
    )
    try:
        assert "--cover" in args and str(cover) in args
    finally:
        body_file.unlink(missing_ok=True)


# ------------------------------------------------------------------ 预览

def _manifest(tmp_path, **over):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 1024)
    base = {
        "content_type": "video",
        "video": str(video),
        "title": "标题",
        "body": "正文 #AI",
        "account_id": "bilibili:1",
    }
    base.update(over)
    return base


def test_preview_video_ok(tmp_path, capsys):
    assert P.preview_video(_manifest(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "视频投稿计划" in out
    assert "可以提交" in out
    assert "AI 声明" in out


def test_preview_video_rejects_missing_file(tmp_path, capsys):
    manifest = _manifest(tmp_path, video=str(tmp_path / "absent.mp4"))
    assert P.preview_video(manifest) == 1
    assert "视频文件不存在" in capsys.readouterr().out


def test_preview_video_rejects_long_title(tmp_path, capsys):
    manifest = _manifest(tmp_path, title="长" * 81)
    assert P.preview_video(manifest) == 1
    assert "标题超过" in capsys.readouterr().out


def test_preview_video_rejects_long_desc(tmp_path, capsys):
    manifest = _manifest(tmp_path, body="字" * 2001)
    assert P.preview_video(manifest) == 1
    assert "简介超过" in capsys.readouterr().out


def test_preview_never_calls_bili(tmp_path, monkeypatch):
    """预览必须纯展示：一旦调用 bili 就等于真上传。"""
    called: list[list[str]] = []
    monkeypatch.setattr(P, "run_bili", lambda args: called.append(args) or (0, None, ""))
    P.preview_video(_manifest(tmp_path))
    assert called == []
