"""豆包语音合成。

从 ``scripts/tts.py`` 抽出来的库部分，供脚本和视频流程共用。

接口要点（实测踩出来的，别改）：

- 端点是 ``openspeech.bytedance.com``，不是 ``ark.cn-beijing.volces.com``
- 必须同时带 ``X-Api-Key`` 和 ``Authorization: Bearer``，少一个就是 400
- ``X-Api-Resource-Id`` 固定 ``seed-tts-2.0``；音色必须属于这个资源族
- 响应两种形态：短文本直接给音频二进制；长文本给 **NDJSON**，
  每行一个 base64 分片，要拼起来
- HTTP 200 也可能是错误，必须看 ``code``；成功码有 0 和 20000000
"""

from __future__ import annotations

import base64
import json
import os
import re
import uuid
from pathlib import Path

TTS_URL = "https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional"
RESOURCE_ID = "seed-tts-2.0"

#: 相对仓库根定位凭据文件。
#: content/tts.py -> src/content -> src -> content -> services -> 仓库根
_CRED_FILE = Path(__file__).resolve().parents[4] / ".local" / "dsh" / ".credentials.yaml"

#: 当前套餐实测可用的音色。别的族会返回 55000000。
VOICES = {
    "vv": "zh_female_vv_uranus_bigtts",
    "xiaohe": "zh_female_xiaohe_uranus_bigtts",
    "roumei": "zh_female_roumeinvyou_uranus_bigtts",
    "m191": "zh_male_m191_uranus_bigtts",
    "taocheng": "zh_male_taocheng_uranus_bigtts",
    "keai": "saturn_zh_female_keainvsheng_tob",
    "tiaopi": "saturn_zh_female_tiaopigongzhu_tob",
    "shuanglang": "saturn_zh_male_shuanglangshaonian_tob",
}

DEFAULT_SPEAKER = VOICES["keai"]


class TtsError(RuntimeError):
    """合成失败。"""


def load_api_key() -> str:
    key = os.environ.get("VOLC_API_KEY", "")
    if key:
        return key
    if _CRED_FILE.exists():
        match = re.search(
            r"^\s*VOLC_API_KEY:\s*(\S+)\s*$",
            _CRED_FILE.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            return match.group(1)
    return ""


def resolve_speaker(name: str) -> str:
    """短名（如 ``keai``）或完整音色 ID 都能传。"""
    return VOICES.get(name, name)


def synthesize(
    text: str,
    *,
    speaker: str = DEFAULT_SPEAKER,
    fmt: str = "mp3",
    sample_rate: int = 24000,
    speed: float | None = None,
    loudness: float | None = None,
    emotion: str | None = None,
    api_key: str | None = None,
    timeout: int = 120,
) -> bytes:
    """合成一段语音，返回音频字节。"""
    import urllib.error
    import urllib.request

    key = api_key or load_api_key()
    if not key:
        raise TtsError("缺少 VOLC_API_KEY")

    params: dict = {
        "text": text,
        "speaker": resolve_speaker(speaker),
        "audio_params": {"format": fmt, "sample_rate": sample_rate},
    }
    if speed is not None:
        params["speed_ratio"] = speed
    if loudness is not None:
        params["loudness_ratio"] = loudness
    if emotion:
        params["emotion"] = emotion

    payload = json.dumps({"user": {"uid": "cyber-sloth"}, "req_params": params}).encode("utf-8")
    request = urllib.request.Request(
        TTS_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": key,
            "Authorization": f"Bearer {key}",
            "X-Api-Resource-Id": RESOURCE_ID,
            "X-Api-Request-Id": str(uuid.uuid4()),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise TtsError(f"接口返回 {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TtsError(f"网络错误: {exc.reason}") from exc

    if raw[:1] != b"{":
        return raw

    audio = bytearray()
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue
        code = chunk.get("code")
        if code not in (0, None, 20000000):
            if code == 55000000:
                raise TtsError(
                    f"音色与资源不匹配：{params['speaker']} 不属于 {RESOURCE_ID}；"
                    "改用 *_uranus_bigtts 或 saturn_*_tob"
                )
            raise TtsError(f"code={code} {chunk.get('message') or ''}")
        if chunk.get("data"):
            audio += base64.b64decode(chunk["data"])

    if not audio:
        raise TtsError("接口没有返回音频数据")
    return bytes(audio)


def synthesize_to_file(
    text: str,
    out_path: Path,
    *,
    speaker: str = DEFAULT_SPEAKER,
    fmt: str = "mp3",
    sample_rate: int = 24000,
    speed: float | None = None,
    **kwargs,
) -> Path:
    """合成并写盘。``fmt`` 决定扩展名，调用方应保持一致。"""
    audio = synthesize(
        text, speaker=speaker, fmt=fmt, sample_rate=sample_rate, speed=speed, **kwargs
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio)
    return out_path
