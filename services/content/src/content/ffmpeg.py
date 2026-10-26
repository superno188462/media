"""ffmpeg 的定位与调用。

二进制不提交进版本库：``services/**/.runtime/`` 已由 .gitignore 覆盖。
本地开发时放在 ``services/content/.runtime/ffmpeg/``；
容器部署时由镜像自行安装（Debian/Ubuntu 一般是 ``apt-get install -y ffmpeg``），
此时走 PATH 就能找到。

定位顺序（先命中先用）：

1. ``FFMPEG`` 环境变量 —— 显式覆盖，容器或 CI 用
2. 项目内 ``services/content/.runtime/ffmpeg/ffmpeg.exe``（Windows）或 ``ffmpeg``（POSIX）
3. 系统 PATH

许可证提醒：本项目自带的 Windows 构建启用了 ``--enable-gpl``，
以容器镜像分发时需按 GPL 处理；也可以改用发行版提供的 ffmpeg。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

#: services/content/ffmpeg.py -> services/content
_SERVICE_ROOT = Path(__file__).resolve().parents[2]

#: 项目内期望的二进制位置。
_RUNTIME_DIR = _SERVICE_ROOT / ".runtime" / "ffmpeg"

_EXE_NAME = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"


class FfmpegNotFound(RuntimeError):
    """找不到可用的 ffmpeg。"""


def find() -> Path:
    """返回可用的 ffmpeg 路径。找不到时抛 FfmpegNotFound。"""
    override = os.environ.get("FFMPEG", "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise FfmpegNotFound(f"FFMPEG 指向的文件不存在：{override}")

    bundled = _RUNTIME_DIR / _EXE_NAME
    if bundled.is_file():
        return bundled

    on_path = shutil.which("ffmpeg")
    if on_path:
        return Path(on_path)

    raise FfmpegNotFound(
        "找不到 ffmpeg。本地开发放到 services/content/.runtime/ffmpeg/，"
        "容器里安装系统 ffmpeg（如 apt-get install -y ffmpeg），"
        "或设置 FFMPEG 环境变量指向可执行文件。"
    )


def available() -> bool:
    try:
        find()
        return True
    except FfmpegNotFound:
        return False


def run(args: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    """以非交互方式运行 ffmpeg。

    统一加 ``-hide_banner -nostdin -y``：不打印横幅、不抢标准输入、覆盖输出。
    """
    binary = find()
    command = [str(binary), "-hide_banner", "-nostdin", "-y", *args]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def probe(path: Path) -> dict:
    """读取媒体的基本信息。读不到就返回空字段，不编造。

    返回 ``duration_ms`` / ``sample_rate`` / ``channels`` / ``width`` / ``height``
    / ``has_audio`` / ``has_video``；读不出来时对应值为 None。
    """
    binary = find()
    proc = subprocess.run(
        [str(binary), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = proc.stderr or ""

    info: dict = {
        "duration_ms": None,
        "sample_rate": None,
        "channels": None,
        "width": None,
        "height": None,
        "has_audio": "Audio:" in text,
        "has_video": "Video:" in text,
    }

    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", text)
    if match:
        hours, minutes, seconds, fraction = match.groups()
        info["duration_ms"] = (
            (int(hours) * 60 + int(minutes)) * 60 + int(seconds)
        ) * 1000 + int(fraction.ljust(3, "0")[:3])

    audio = re.search(r"Audio:\s*[^,]+,\s*(\d+)\s*Hz,\s*([^,]+)", text)
    if audio:
        info["sample_rate"] = int(audio.group(1))
        info["channels"] = audio.group(2).strip()

    video = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", text)
    if video:
        info["width"] = int(video.group(1))
        info["height"] = int(video.group(2))

    return info


def probe_duration_ms(path: Path) -> int | None:
    """只要时长。没有 ffmpeg 时返回 None。"""
    try:
        return probe(path)["duration_ms"]
    except (FfmpegNotFound, OSError):
        return None
