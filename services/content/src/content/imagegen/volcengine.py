"""火山方舟（豆包 Seedream）生图适配器。

注意 Base URL：Agent Plan 个人版的 key 走的是 ``/api/plan/v3``，
和 ModelArk 的 ``/api/v3`` 不是同一个入口。用错会得到 401。

凭据从环境变量 ``VOLC_API_KEY`` 读取，不写进代码或文档。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .base import ImageGenerationError, ImageRequest, ImageResult

#: Agent Plan 个人版专用入口。
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/plan/v3"

DEFAULT_MODEL = "doubao-seedream-5-0-pro"


class VolcengineImageGenerator:
    """豆包 Seedream 生图。"""

    name = "volcengine-seedream"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 180,
    ) -> None:
        self.api_key = api_key or os.environ.get("VOLC_API_KEY", "")
        if not self.api_key:
            raise ImageGenerationError(
                "缺少 VOLC_API_KEY：请把它写进 .local/dsh/.credentials.yaml 或环境变量。"
            )
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def generate(self, request: ImageRequest, out_dir: Path) -> ImageResult:
        payload: dict = {
            "model": self.model,
            "prompt": request.prompt,
            "size": request.size,
            "response_format": "url",
            "watermark": False,
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            payload["seed"] = request.seed

        url = f"{self.base_url}/images/generations"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ImageGenerationError(
                f"生图接口返回 {exc.code}: {detail}\n"
                f"若为 401，请确认 Base URL 是 {self.base_url}（Agent Plan 专用），"
                f"而不是 /api/v3。"
            ) from exc
        except urllib.error.URLError as exc:
            raise ImageGenerationError(f"网络错误: {exc.reason}") from exc

        items = body.get("data") or []
        if not items:
            raise ImageGenerationError(f"接口未返回图片: {body}")

        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for index, item in enumerate(items):
            img_url = item.get("url")
            if not img_url:
                continue
            suffix = ".png" if img_url.lower().split("?")[0].endswith(".png") else ".jpg"
            target = out_dir / f"seedream_{index}{suffix}"
            with urllib.request.urlopen(img_url, timeout=self.timeout) as img_resp:
                target.write_bytes(img_resp.read())
            paths.append(target)

        if not paths:
            raise ImageGenerationError(f"接口未返回可下载的图片: {body}")

        return ImageResult(
            paths=paths,
            model=body.get("model", self.model),
            usage=body.get("usage"),
        )
