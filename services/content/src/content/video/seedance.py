"""豆包 Seedance 视频生成：创建任务 → 轮询 → 下载。

和生图/语音不同的三点：

1. **异步**：先建任务拿 ``id``，再轮询状态，不是一次调用就出结果。
2. **计费按秒**：``duration`` 直接决定花费，所以默认取最小值。
3. **参考图可以是 base64**：不需要公网图床，本地素材转 data URI 直接传。

接口与官方 curl 保持一致（``/api/v3``，不是 Agent Plan 的 ``/api/plan/v3``）：

    POST /api/v3/contents/generations/tasks
    GET  /api/v3/contents/generations/tasks/{id}

凭据读 ``VOLC_VIDEO_API_KEY``；它与生图/语音的 ``VOLC_API_KEY`` 是**两把不同的 key**。
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
CREATE_PATH = "/contents/generations/tasks"

#: 官方示例使用的模型 ID。
DEFAULT_MODEL = "doubao-seedance-2-5-260628"

#: 可选模型（按官方文档）。
MODELS = {
    "seedance-2.5": "doubao-seedance-2-5-260628",
    "seedance-2.0": "doubao-seedance-2-0-260128",
    "seedance-2.0-fast": "doubao-seedance-2-0-fast-260128",
}

#: 时长与分辨率档位。
DURATION_RANGE = (4, 30)
RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}
RESOLUTIONS = {"480p", "720p", "1080p"}

# video/seedance.py -> content -> src -> content -> services -> 仓库根
_CRED_FILE = Path(__file__).resolve().parents[5] / ".local" / "dsh" / ".credentials.yaml"


class SeedanceError(RuntimeError):
    """视频生成失败。"""


@dataclass
class Task:
    task_id: str
    status: str
    video_url: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")

    @property
    def ok(self) -> bool:
        return self.status == "succeeded" and bool(self.video_url)


def load_api_key() -> str:
    key = os.environ.get("VOLC_VIDEO_API_KEY", "")
    if key:
        return key
    if _CRED_FILE.exists():
        match = re.search(
            r"^\s*VOLC_VIDEO_API_KEY:\s*(\S+)\s*$",
            _CRED_FILE.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            return match.group(1)
    return ""


def _post(path: str, payload: dict, *, key: str, timeout: int = 60) -> dict:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise SeedanceError(f"创建任务失败 HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SeedanceError(f"网络错误: {exc.reason}") from exc


def _get(path: str, *, key: str, timeout: int = 30) -> dict:
    request = urllib.request.Request(
        BASE_URL + path,
        headers={"Authorization": f"Bearer {key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise SeedanceError(f"查询任务失败 HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SeedanceError(f"网络错误: {exc.reason}") from exc


def to_data_uri(path: Path) -> str:
    """把本地图片转成 data URI——不需要公网图床。"""
    suffix = path.suffix.lower().lstrip(".") or "png"
    mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def build_content(
    prompt: str,
    *,
    first_frame: Path | None = None,
    reference_images: list[Path] | None = None,
) -> list[dict]:
    """组装 content 数组。

    ``first_frame`` 用 ``role=first_frame``（首帧图生视频）；
    ``reference_images`` 用 ``role=reference_image``（多模态参考）。
    """
    content: list[dict] = [{"type": "text", "text": prompt}]

    if first_frame is not None:
        content.append({
            "type": "image_url",
            "image_url": {"url": to_data_uri(first_frame)},
            "role": "first_frame",
        })

    for image in reference_images or []:
        content.append({
            "type": "image_url",
            "image_url": {"url": to_data_uri(image)},
            "role": "reference_image",
        })

    return content


def create_task(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    duration: int = 4,
    ratio: str = "16:9",
    resolution: str | None = None,
    generate_audio: bool = False,
    watermark: bool = False,
    first_frame: Path | None = None,
    reference_images: list[Path] | None = None,
    key: str | None = None,
) -> Task:
    """创建一个视频生成任务，立刻返回任务 ID（不等待）。"""
    if not 4 <= duration <= 30:
        raise SeedanceError(f"时长必须在 {DURATION_RANGE[0]}–{DURATION_RANGE[1]} 秒：{duration}")
    if ratio not in RATIOS:
        raise SeedanceError(f"不支持的比例：{ratio}")
    if resolution is not None and resolution not in RESOLUTIONS:
        raise SeedanceError(f"不支持的分辨率：{resolution}")
    if not prompt.strip():
        raise SeedanceError("提示词不能为空")

    api_key = key or load_api_key()
    if not api_key:
        raise SeedanceError("缺少 VOLC_VIDEO_API_KEY")

    payload: dict = {
        "model": model,
        "content": build_content(
            prompt, first_frame=first_frame, reference_images=reference_images
        ),
        "duration": duration,
        "generate_audio": generate_audio,
        "watermark": watermark,
        "client_token": str(uuid.uuid4()),
    }
    # 首帧模式：官方明确 ratio 由首帧决定，再传会被
    # InvalidParameter.TaskTypeConstraint 拒绝。
    if first_frame is None:
        payload["ratio"] = ratio
    if resolution:
        payload["resolution"] = resolution

    data = _post(CREATE_PATH, payload, key=api_key)
    task_id = data.get("id") or data.get("task_id")
    if not task_id:
        raise SeedanceError(f"创建任务没有返回 id：{json.dumps(data, ensure_ascii=False)[:300]}")
    return Task(task_id=str(task_id), status=str(data.get("status") or "queued"), raw=data)


def query_task(task_id: str, *, key: str | None = None) -> Task:
    api_key = key or load_api_key()
    if not api_key:
        raise SeedanceError("缺少 VOLC_VIDEO_API_KEY")

    data = _get(f"{CREATE_PATH}/{task_id}", key=api_key)
    status = str(data.get("status") or "unknown")
    content = data.get("content") or {}
    url = content.get("video_url") or ""
    return Task(task_id=task_id, status=status, video_url=url, raw=data)


def wait_task(
    task_id: str,
    *,
    timeout_s: int = 600,
    interval_s: float = 5.0,
    on_progress=None,
) -> Task:
    """轮询直到完成。超时抛错，不静默返回进行中的状态。"""
    deadline = time.time() + timeout_s
    last = "queued"
    while time.time() < deadline:
        task = query_task(task_id)
        if task.status != last:
            last = task.status
            if on_progress is not None:
                on_progress(task)
        if task.status == "succeeded":
            return task
        if task.status in ("failed", "cancelled"):
            raise SeedanceError(
                f"任务 {task_id} {task.status}："
                f"{json.dumps(task.raw.get('error') or {}, ensure_ascii=False)[:300]}"
            )
        time.sleep(interval_s)
    raise SeedanceError(f"任务 {task_id} 在 {timeout_s} 秒内没有完成（最后状态 {last}）")


def download(url: str, target: Path, *, timeout: int = 300) -> Path:
    """下载成片。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            target.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        raise SeedanceError(f"下载失败 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SeedanceError(f"下载网络错误: {exc.reason}") from exc
    return target
