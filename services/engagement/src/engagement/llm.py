"""最小 LLM 客户端。

只用于两件事：意图识别、发送前门禁。

原则：
- 凭据从 `.local/dsh/.credentials.yaml` 读，不硬编码
- 任何失败都抛异常，由调用方决定 **fail closed**（宁可不发）
- 强制模型输出 JSON，解析失败视为失败
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


class LlmError(RuntimeError):
    """调用模型失败。调用方应据此拒绝发送。"""


@dataclass
class LlmConfig:
    api_key: str
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    timeout: int = 40

    @classmethod
    def from_credentials(cls, path: Path, *, env_name: str = "DEEPSEEK_API_KEY",
                         model: str = "deepseek-chat",
                         base_url: str = "https://api.deepseek.com/v1") -> "LlmConfig":
        if not path.exists():
            raise LlmError(f"凭据文件不存在：{path}")
        text = path.read_text(encoding="utf-8")
        match = re.search(rf"^\s*{env_name}:\s*(\S+)\s*$", text, re.MULTILINE)
        if not match:
            raise LlmError(f"凭据里没有 {env_name}")
        return cls(api_key=match.group(1), model=model, base_url=base_url)


class LlmClient:
    def __init__(self, config: LlmConfig) -> None:
        self.config = config

    def chat_json(self, system: str, user: str) -> dict:
        """要求模型返回 JSON 对象。失败一律抛 LlmError。"""
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise LlmError(f"模型接口返回 {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LlmError(f"网络错误: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LlmError("模型调用超时") from exc

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError(f"模型响应结构异常: {str(body)[:200]}") from exc

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LlmError(f"模型未返回合法 JSON: {content[:200]}") from exc
