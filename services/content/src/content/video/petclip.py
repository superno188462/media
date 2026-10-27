"""宠物动画的素材源抽象。

一个「动作」= 一串 RGBA 帧 + 播放参数。谁产出帧不重要：

- ``flipbook``：一目录的 PNG 帧（用生图批量生成，零额外成本）
- ``video``：一段视频，抽成帧（Vidu/豆包视频生成产出，需要积分）
- ``static``：一张静图（兜底，行为和之前一样）

上层（合成器）只认 ``PetClip.frame_at(t_ms)``，换来源不改渲染逻辑。
前台配置页将来只需要改配置文件里的 ``source`` 和路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

#: 支持的帧源类型。
SOURCE_FLIPBOOK = "flipbook"
SOURCE_VIDEO = "video"
SOURCE_STATIC = "static"

SOURCES = {SOURCE_FLIPBOOK, SOURCE_VIDEO, SOURCE_STATIC}

#: 翻页动画的默认播放帧率。12fps 足够"活着"，又不至于闪烁太明显。
DEFAULT_CLIP_FPS = 12

#: 相邻帧的交叉淡化占单帧时长的比例。0 表示硬切（会闪）。
DEFAULT_CROSSFADE = 0.45

#: 视频抽帧的默认帧率（预留）。
DEFAULT_FPS_VIDEO = 12


class ClipError(RuntimeError):
    """帧源加载失败。"""


class PetClip(Protocol):
    """帧源接口。实现者只需保证 ``frame_at`` 返回 RGBA 图。"""

    fps: int
    frame_count: int

    def frame_at(self, t_ms: float): ...


def _smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def _blend(first, second, weight: float):
    """两帧按权重混合，保留 alpha。"""
    from PIL import Image

    if weight <= 0.001:
        return first
    if weight >= 0.999:
        return second
    return Image.blend(first, second, weight)


@dataclass
class FlipbookClip:
    """一目录 RGBA 帧，循环播放，相邻帧交叉淡化。

    为什么淡化：生图逐帧生成，角色细节（脸、手）会有轻微漂移，
    硬切会像闪烁；淡化能把跳变压成"动"。
    """

    frames: list
    fps: int = DEFAULT_CLIP_FPS
    crossfade: float = DEFAULT_CROSSFADE

    def __post_init__(self) -> None:
        if not self.frames:
            raise ClipError("翻页动画没有帧")
        if self.fps <= 0:
            raise ClipError(f"帧率必须为正：{self.fps}")
        if not 0.0 <= self.crossfade < 1.0:
            raise ClipError(f"交叉淡化比例必须在 [0,1)：{self.crossfade}")

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def frame_at(self, t_ms: float):
        count = self.frame_count
        if count == 1:
            return self.frames[0]

        frame_ms = 1000.0 / self.fps
        position = max(0.0, t_ms) / frame_ms
        index = int(position) % count
        fraction = position - int(position)

        # 只在单帧末尾的一段做淡化，前面保持清晰
        start = 1.0 - self.crossfade
        if self.crossfade <= 0 or fraction < start:
            return self.frames[index]

        weight = _smoothstep((fraction - start) / self.crossfade)
        return _blend(self.frames[index], self.frames[(index + 1) % count], weight)

    @classmethod
    def load(
        cls,
        directory: Path,
        *,
        fps: int = DEFAULT_CLIP_FPS,
        crossfade: float = DEFAULT_CROSSFADE,
        height: int | None = None,
    ) -> "FlipbookClip":
        from PIL import Image

        directory = Path(directory)
        if not directory.is_dir():
            raise ClipError(f"帧目录不存在：{directory}")

        paths = sorted(
            p for p in directory.iterdir()
            if p.suffix.lower() in (".png", ".webp") and p.is_file()
        )
        if not paths:
            raise ClipError(f"帧目录里没有 PNG：{directory}")

        frames = []
        for path in paths:
            with Image.open(path) as opened:
                image = opened.convert("RGBA")
            if height is not None and image.height != height:
                scale = height / image.height
                image = image.resize(
                    (max(1, round(image.width * scale)), height), Image.LANCZOS
                )
            frames.append(image)

        # 尺寸必须一致，否则混合会报错
        sizes = {f.size for f in frames}
        if len(sizes) > 1:
            raise ClipError(f"帧尺寸不一致：{sorted(sizes)}")

        return cls(frames=frames, fps=fps, crossfade=crossfade)


@dataclass
class StaticClip:
    """单帧兜底：行为和以前的静态立绘一致。"""

    image: object
    fps: int = DEFAULT_CLIP_FPS

    @property
    def frame_count(self) -> int:
        return 1

    def frame_at(self, t_ms: float):
        return self.image

    @classmethod
    def load(cls, path: Path, *, height: int | None = None) -> "StaticClip":
        from PIL import Image

        path = Path(path)
        if not path.is_file():
            raise ClipError(f"立绘不存在：{path}")
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
        if height is not None and image.height != height:
            scale = height / image.height
            image = image.resize(
                (max(1, round(image.width * scale)), height), Image.LANCZOS
            )
        return cls(image=image)


@dataclass
class VideoClip:
    """从视频抽帧。预留给 Vidu / 豆包 视频生成产出。

    当前未启用：两家都没有可用的视频生成额度。实现放在这里，
    等积分到位后只需把 ``load`` 接通，上层不用改。
    """

    frames: list
    fps: int = DEFAULT_CLIP_FPS
    crossfade: float = DEFAULT_CROSSFADE

    def __post_init__(self) -> None:
        if not self.frames:
            raise ClipError("视频帧为空")

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def frame_at(self, t_ms: float):
        frame_ms = 1000.0 / self.fps
        index = int(max(0.0, t_ms) / frame_ms) % self.frame_count
        return self.frames[index]

    @classmethod
    def load(
        cls,
        video: Path,
        *,
        fps: int = DEFAULT_FPS_VIDEO,
        height: int | None = None,
        tolerance: int = 30,
        cache_dir: Path | None = None,
        crossfade: float = 0.0,
    ) -> "VideoClip":
        """从 mp4 抽帧 → 抠图 → 归一化。

        视频里角色是连续的，所以相邻帧天然一致，``crossfade`` 可以留 0。

        抽帧结果会缓存到 ``cache_dir``，避免每次渲染都重新抠图
        （抠图是纯 Python 洪泛填充，48 帧要几十秒）。
        """
        video = Path(video)
        if not video.is_file():
            raise ClipError(f"视频不存在：{video}")

        cache = Path(cache_dir) if cache_dir else video.parent / f"{video.stem}_frames"
        marker = cache / ".ready"
        if cache.is_dir() and marker.exists():
            return _load_frame_dir(
                cache, fps=fps, crossfade=crossfade, height=height
            )

        frames = _extract_and_cut(video, cache, fps=fps, height=height, tolerance=tolerance)
        marker.write_text(str(len(frames)), encoding="utf-8")
        return cls(frames=frames, fps=fps, crossfade=crossfade)


def build_clip(
    source: str,
    *,
    directory: Path | None = None,
    path: Path | None = None,
    fps: int = DEFAULT_CLIP_FPS,
    crossfade: float = DEFAULT_CROSSFADE,
    height: int | None = None,
) -> PetClip:
    """按配置构造帧源。前台配置页最终就是调这个。"""
    if source == SOURCE_FLIPBOOK:
        if directory is None:
            raise ClipError("flipbook 需要 directory")
        return FlipbookClip.load(
            directory, fps=fps, crossfade=crossfade, height=height
        )
    if source == SOURCE_STATIC:
        if path is None:
            raise ClipError("static 需要 path")
        return StaticClip.load(path, height=height)
    if source == SOURCE_VIDEO:
        if path is None:
            raise ClipError("video 需要 path")
        return VideoClip.load(path, fps=fps)
    raise ClipError(f"未知帧源类型：{source}")


def _extract_raw_frames(video: Path, out_dir: Path, fps: int) -> list[Path]:
    """用 ffmpeg 抽帧到目录，返回按序路径。"""
    from .. import ffmpeg as ffmpeg_tool

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("raw_*.jpg"):
        stale.unlink()

    result = ffmpeg_tool.run(
        ["-i", str(video), "-vf", f"fps={fps}", "-q:v", "2", str(out_dir / "raw_%04d.jpg")],
        timeout=900,
    )
    if result.returncode != 0:
        raise ClipError(f"抽帧失败：{(result.stderr or '')[-300:]}")
    return sorted(out_dir.glob("raw_*.jpg"))


def _normalize(images: list, height: int | None) -> list:
    """统一缩放到同一高度，再居中到同宽画布。"""
    from PIL import Image

    if not images:
        raise ClipError("没有可用帧")
    if height is None:
        height = images[0].height

    scaled = []
    for image in images:
        width = max(1, round(image.width * height / image.height))
        scaled.append(image.resize((width, height), Image.LANCZOS))

    canvas_w = max(image.width for image in scaled)
    out = []
    for image in scaled:
        canvas = Image.new("RGBA", (canvas_w, height), (0, 0, 0, 0))
        canvas.paste(image, ((canvas_w - image.width) // 2, 0), image)
        out.append(canvas)
    return out


def _extract_and_cut(
    video: Path, cache: Path, *, fps: int, height: int | None, tolerance: int
) -> list:
    from PIL import Image

    from ..imagegen.cutout import remove_background, trim_transparent

    raw_paths = _extract_raw_frames(video, cache, fps)
    if not raw_paths:
        raise ClipError("视频里抽不到帧")

    cut = []
    for index, path in enumerate(raw_paths):
        intermediate = cache / f"tmp_{index:04d}.png"
        remove_background(path, intermediate, tolerance=tolerance)
        trim_transparent(intermediate, intermediate)
        with Image.open(intermediate) as opened:
            cut.append(opened.convert("RGBA").copy())
        intermediate.unlink(missing_ok=True)

    frames = _normalize(cut, height)
    # 归一化后的帧落盘，二次加载才真的省时间
    for stale in cache.glob("frame_*.png"):
        stale.unlink()
    for index, frame in enumerate(frames):
        frame.save(cache / f"frame_{index:04d}.png", "PNG")
    return frames


def _load_frame_dir(
    directory: Path, *, fps: int, crossfade: float, height: int | None
) -> "VideoClip":
    from PIL import Image

    paths = sorted(p for p in directory.glob("frame_*.png"))
    if not paths:
        raise ClipError(f"缓存目录里没有帧：{directory}")
    frames = []
    for path in paths:
        with Image.open(path) as opened:
            frames.append(opened.convert("RGBA").copy())
    return VideoClip(frames=_normalize(frames, height), fps=fps, crossfade=crossfade)
