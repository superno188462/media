"""用 Playwright 把 HTML 截成图。

为什么用 Playwright 自带的 Chromium 而不是系统浏览器：
**容器里没有系统浏览器**。Playwright 的浏览器是版本化下载，
Windows 与 Linux 同一套 API，``playwright install chromium`` 即可复现。

字体：容器需要中文字体（Debian/Ubuntu 装 ``fonts-noto-cjk``），
否则中文会变成方框。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from .scenes import Scene, Storyboard
from .template import render_html

#: 项目内的浏览器缓存目录。Playwright 默认装在用户目录（%LOCALAPPDATA%），
#: 那在容器里不存在；放在服务运行区更适合打包。
#: content/video/renderer.py -> services/content
_SERVICE_ROOT = Path(__file__).resolve().parents[3]
BROWSERS_DIR = _SERVICE_ROOT / ".runtime" / "ms-playwright"


def ensure_browsers_path() -> None:
    """若项目内有浏览器缓存且未显式指定，就指向它。

    容器里通常由 ``playwright install --with-deps chromium`` 装到默认位置，
    此时不设置本变量即可。
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    if BROWSERS_DIR.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)


class RendererError(RuntimeError):
    """渲染失败。"""


class Renderer(Protocol):
    """渲染层接口。换实现（Pillow/HTML）不影响上层。"""

    def render(self, storyboard: Storyboard, scene: Scene, out_path: Path) -> Path: ...


class PlaywrightRenderer:
    """用 Chromium 截图的渲染器。

    浏览器实例复用：一次启动，渲染所有场次，最后关闭。
    """

    def __init__(self, *, device_scale: float = 1.0, timeout_ms: int = 30_000) -> None:
        self.device_scale = device_scale
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._page = None

    # ------------------------------------------------------------ 生命周期

    def __enter__(self) -> "PlaywrightRenderer":
        ensure_browsers_path()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 取决于运行环境
            raise RendererError(
                "缺少 playwright。安装：uv run --with playwright playwright install chromium --only-shell"
            ) from exc

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(
                args=["--force-color-profile=srgb", "--hide-scrollbars"]
            )
        except Exception as exc:  # noqa: BLE001
            self._playwright.stop()
            self._playwright = None
            raise RendererError(
                "启动 Chromium 失败。先运行 playwright install chromium 下载浏览器。"
                f" 原始错误：{exc}"
            ) from exc
        return self

    def __exit__(self, *exc_info) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    # ------------------------------------------------------------ 渲染

    def _ensure_page(self, storyboard: Storyboard):
        if self._page is not None:
            return self._page
        assert self._browser is not None
        self._page = self._browser.new_page(
            viewport={"width": storyboard.width, "height": storyboard.height},
            device_scale_factor=self.device_scale,
        )
        self._page.set_default_timeout(self.timeout_ms)
        return self._page

    def render(self, storyboard: Storyboard, scene: Scene, out_path: Path) -> Path:
        page = self._ensure_page(storyboard)
        html = render_html(storyboard, scene)
        page.set_content(html, wait_until="load")
        # 等字体与图片就绪，避免截到方框或空白
        page.evaluate(
            """async () => {
                if (document.fonts && document.fonts.ready) { await document.fonts.ready; }
                const imgs = Array.from(document.images);
                await Promise.all(imgs.map(i => i.complete ? null :
                    new Promise(r => { i.onload = r; i.onerror = r; })));
            }"""
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out_path), type="png")
        return out_path

    def render_all(self, storyboard: Storyboard, out_dir: Path) -> list[Path]:
        """渲染所有场次，返回按顺序排列的图片路径。"""
        out_dir.mkdir(parents=True, exist_ok=True)
        frames: list[Path] = []
        for index, scene in enumerate(storyboard.scenes, 1):
            target = out_dir / f"scene_{index:03d}.png"
            frames.append(self.render(storyboard, scene, target))
        return frames
