"""生图后端适配器。"""

from .base import ImageGenerationError, ImageGenerator, ImageRequest, ImageResult

__all__ = [
    "ImageGenerator",
    "ImageRequest",
    "ImageResult",
    "ImageGenerationError",
]
