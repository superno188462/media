"""视频生产：分镜 → 逐场出图 → 合成 mp4。

与图文链路共享同一套外部组件：

- 出图：``content.imagegen``（豆包 Seedream）
- 配音：``scripts/tts.py``（豆包语音合成）
- 编码：``content.ffmpeg``（项目内 ffmpeg）

渲染层是可替换的：``Renderer`` 协议 + ``PlaywrightRenderer`` 实现。
换排版方案只改实现，不动分镜与合成。
"""

from .compose import ComposeError, ComposeResult, compose, extract_frame, extract_keyframes
from .renderer import BROWSERS_DIR, PlaywrightRenderer, Renderer, RendererError, ensure_browsers_path
from .scenes import Card, CardLine, Scene, Storyboard
from . import voice

__all__ = [
    "Scene",
    "Card",
    "CardLine",
    "Storyboard",
    "Renderer",
    "PlaywrightRenderer",
    "RendererError",
    "BROWSERS_DIR",
    "ensure_browsers_path",
    "compose",
    "ComposeResult",
    "ComposeError",
    "extract_frame",
    "extract_keyframes",
    "voice",
]
