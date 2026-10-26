"""生图能力的接口定义。

外部生图服务都是可替换的：换后端不应该动业务代码。
所以这里只定协议，具体实现放在 volcengine.py / comfyui.py 等适配器里。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ImageRequest:
    """一次生图请求。"""

    prompt: str
    negative_prompt: str = ""
    #: 目标尺寸。Seedream 支持 "1K" / "2K" / "4K" 或 "宽x高"。
    size: str = "1K"
    seed: int | None = None
    #: 参考图路径（如需保持角色一致性）。
    reference_images: list[Path] | None = None


@dataclass
class ImageResult:
    """一次生图的结果。"""

    paths: list[Path]
    model: str
    #: 原始响应摘要，用于留痕。
    usage: dict | None = None

    def __post_init__(self) -> None:
        if not self.paths:
            raise ValueError("生图结果为空")


class ImageGenerator(Protocol):
    """生图后端的统一接口。"""

    name: str

    def generate(self, request: ImageRequest, out_dir: Path) -> ImageResult:
        """生成图片并落盘到 out_dir，返回本地路径。"""
        ...


class ImageGenerationError(RuntimeError):
    """生图失败。"""
