"""渲染器的测试。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from content.render import MAX_EDGE, RenderOptions, render_post


def _make_image(path: Path, size=(800, 600), color=(200, 180, 160)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def test_renders_title_and_body(tmp_path):
    out = render_post(
        title="测试标题",
        body="这是正文第一行。\n这是正文第二行。",
        images=[],
        out_path=tmp_path / "out.jpg",
    )
    assert out.exists()
    with Image.open(out) as im:
        assert im.width > 0 and im.height > 0


def test_renders_with_images(tmp_path):
    img = _make_image(tmp_path / "a.png")
    out = render_post(
        title="带图标题",
        body="正文",
        images=[img],
        out_path=tmp_path / "out.jpg",
    )
    with Image.open(out) as im:
        # 高度必须大于只有文字时的高度，说明图被排进去了。
        assert im.height > 600


def test_output_edge_within_limit(tmp_path):
    img = _make_image(tmp_path / "big.png", size=(2400, 1800))
    out = render_post(
        title="大图",
        body="正文",
        images=[img],
        out_path=tmp_path / "out.jpg",
    )
    with Image.open(out) as im:
        assert max(im.size) <= MAX_EDGE


def test_custom_width(tmp_path):
    out = render_post(
        title="T",
        body="B",
        images=[],
        out_path=tmp_path / "out.jpg",
        options=RenderOptions(width=800),
    )
    with Image.open(out) as im:
        assert im.width == 800


def test_long_body_wraps_instead_of_overflowing(tmp_path):
    long_text = "很长的中文内容" * 40
    out = render_post(
        title="换行测试",
        body=long_text,
        images=[],
        out_path=tmp_path / "out.jpg",
        options=RenderOptions(width=640),
    )
    with Image.open(out) as im:
        assert im.height > 640  # 文本被折行堆叠，而不是被截断
