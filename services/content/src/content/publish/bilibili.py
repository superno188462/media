"""B 站发布适配器。

三条硬要求：

1. **先 dry-run 再 publish**。公开发布不可逆，模型必须先把要发什么给人看。
2. **只发 approved 的内容**。创作模型不能自行批准。
3. **提交结果未知时不自动重发**。bili-cli 出现过「平台已成功、CLI 收尾写
   本地状态失败 → 返回 internal_error」的情况。此时必须先核对平台证据，
   确认没发出去才允许再发，绝不盲目重发。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..model import ContentItem
from ..validate import assert_valid

#: 根目录的兼容转发入口。
BILI_CMD = "bili.cmd"


@dataclass
class PublishPreview:
    """发布前的预览，给人确认用。"""

    action: str
    text: str
    images: list[str]
    topic: str | None
    at_users: list[str]

    def render(self) -> str:
        lines = [
            f"动作   : {self.action}",
            f"正文   : {self.text}",
            f"配图   : {len(self.images)} 张（顺序即发布顺序）",
        ]
        for index, path in enumerate(self.images, 1):
            lines.append(f"  {index}. {path}")
        if self.topic:
            lines.append(f"话题   : {self.topic}")
        if self.at_users:
            lines.append(f"@     : {', '.join(self.at_users)}")
        return "\n".join(lines)


@dataclass
class PublishResult:
    ok: bool
    detail: str
    platform_ref: str | None = None
    #: 平台侧证据（用于核对「其实发出去了」的情况）。
    evidence: dict | None = None


class BilibiliPublisher:
    """通过 bili-cli 发布图文动态。"""

    def __init__(self, project_root: Path, command: str = BILI_CMD) -> None:
        self.project_root = project_root
        self.command = command

    # ------------------------------------------------------------------ helpers

    def _run(self, args: list[str]) -> tuple[int, dict | None, str]:
        # bili.cmd 是 .cmd 批处理，Windows 上必须经由 shell 启动。
        proc = subprocess.run(
            [self.command, *args],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=True,
        )
        raw = (proc.stdout or "").strip()
        parsed: dict | None = None
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
        return proc.returncode, parsed, raw or (proc.stderr or "")

    # ------------------------------------------------------------------- dry run

    def preview(self, item: ContentItem) -> PublishPreview:
        """生成发布预览。不做任何写操作。"""
        return PublishPreview(
            action="bili dynamic post（图文动态）",
            text=item.body,
            images=list(item.images),
            topic=item.topic,
            at_users=list(item.at_users),
        )

    # ------------------------------------------------------------------ evidence

    def _verify_published(self, item: ContentItem) -> dict | None:
        """查平台证据：这条内容到底发出去没有。

        用于「CLI 报错但平台可能已成功」的情况。返回匹配到的动态，
        没找到返回 None。
        """
        code, parsed, _ = self._run(["dynamic", "list"])
        if code != 0 or not parsed or not parsed.get("ok"):
            return None
        items = (parsed.get("data") or {}).get("items") or []
        for entry in items:
            if entry.get("text") == item.body:
                return entry
        return None

    # -------------------------------------------------------------------- publish

    def publish(self, item: ContentItem, implemented: list[str] | None = None) -> PublishResult:
        """发布一条图文动态。

        会先跑校验（含审核闸门），再执行；失败时核对平台证据。
        """
        assert_valid(item, implemented)

        args = ["dynamic", "post", item.body]
        for image in item.images:
            args += ["--image", image]
        if item.topic:
            args += ["--topic", item.topic]
        for user in item.at_users:
            args += ["--at", user]

        code, parsed, raw = self._run(args)

        if code == 0 and parsed and parsed.get("ok"):
            data = parsed.get("data") or {}
            return PublishResult(
                ok=True,
                detail="发布成功",
                platform_ref=data.get("id") or data.get("url"),
                evidence=data,
            )

        # 失败：先核对平台证据，绝不盲目重发。
        error = (parsed or {}).get("error") or {}
        message = error.get("message", raw)
        found = self._verify_published(item)
        if found:
            return PublishResult(
                ok=True,
                detail=(
                    f"CLI 返回失败，但平台侧已确认发布成功：{message}\n"
                    f"未重发。以平台证据为准。"
                ),
                platform_ref=found.get("id"),
                evidence=found,
            )

        return PublishResult(ok=False, detail=f"发布失败：{message}", evidence=None)
