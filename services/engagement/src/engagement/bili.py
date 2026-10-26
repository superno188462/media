"""bili-cli 适配器。

只做一件事：把回复真正发出去。风险判定不在这里。

**正文一律用 --file 传**。教训：多行正文直接拼进命令行时，
Windows `cmd` 会把换行当命令分隔符，导致只发出第一行、
后续参数（含 --image / --dry-run）全部失效——曾经因此误发过一条截断动态。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SendResult:
    ok: bool
    rpid: int | None
    detail: str

    @property
    def sent(self) -> bool:
        return self.ok and self.rpid is not None


class BiliClient:
    def __init__(self, project_root: Path, command: str = "bili.cmd") -> None:
        self.project_root = project_root
        self.command = project_root / command

    def _run(self, args: list[str]) -> tuple[int, dict | None, str]:
        proc = subprocess.run(
            ["cmd", "/c", str(self.command), *args],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        raw = (proc.stdout or "").strip()
        parsed = None
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
        return proc.returncode, parsed, raw or (proc.stderr or "")

    def reply(
        self,
        oid: str,
        rpid: int,
        text: str,
        comment_type: str = "draw",
        root: int | None = None,
    ) -> SendResult:
        """回复一条评论。"""
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".txt", delete=False
        )
        handle.write(text)
        handle.close()
        body_file = Path(handle.name)

        args = ["comment", "reply", str(oid), str(rpid), "--type", comment_type,
                "--file", str(body_file), "--wait"]
        if root is not None:
            args += ["--root", str(root)]

        try:
            code, parsed, raw = self._run(args)
        finally:
            body_file.unlink(missing_ok=True)

        if code == 0 and parsed and parsed.get("ok"):
            data = parsed.get("data") or {}
            new_rpid = data.get("rpid")
            return SendResult(ok=True, rpid=new_rpid, detail="发送成功")

        error = (parsed or {}).get("error") or {}
        detail = error.get("message") or raw[:300]
        code_name = error.get("code")
        return SendResult(ok=False, rpid=None, detail=f"{code_name or 'failed'}: {detail}")

    def list_comments(
        self,
        oid: str,
        comment_type: str = "draw",
        page: int = 1,
        unreplied: bool = True,
    ) -> tuple[list[dict], dict]:
        """读一页评论。``unreplied`` 让服务端先筛掉已回复的，省本地开销。"""
        args = [
            "comment", "list", str(oid),
            "--type", comment_type,
            "--page", str(page),
            "--sort", "time",
        ]
        if unreplied:
            args.append("--unreplied")
        code, parsed, raw = self._run(args)
        if code != 0 or not parsed or not parsed.get("ok"):
            return [], {"error": raw[:300]}
        data = parsed.get("data") or {}
        return list(data.get("items") or []), data

    def list_replies(
        self,
        oid: str,
        rpid: int,
        comment_type: str = "draw",
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict], dict]:
        """列出某条根评论下的**楼中楼**回复。"""
        args = [
            "comment", "replies", str(oid), str(rpid),
            "--type", comment_type,
            "--page", str(page),
            "--size", str(size),
        ]
        code, parsed, raw = self._run(args)
        if code != 0 or not parsed or not parsed.get("ok"):
            return [], {"error": raw[:300]}
        data = parsed.get("data") or {}
        return list(data.get("items") or []), data

    def is_visible(self, oid: str, rpid: int, comment_type: str = "draw",
                   root: int | None = None) -> tuple[bool, str]:
        """确认发出去的评论别人能看到（新号可能进审核）。"""
        args = ["comment", "check", str(oid), str(rpid), "--type", comment_type]
        if root is not None:
            args += ["--root", str(root)]
        code, parsed, raw = self._run(args)
        if code != 0 or not parsed or not parsed.get("ok"):
            return False, raw[:200]
        data = parsed.get("data") or {}
        return bool(data.get("visible")), data.get("note", "")
