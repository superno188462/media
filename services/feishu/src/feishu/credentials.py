"""从项目凭据文件补充环境变量。

脚本直接运行时要能拿到 ``FEISHU_*`` 配置，但不想让用户每次手动 export。
只补充**缺失**的变量，不覆盖已有环境变量。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: 允许从凭据文件加载的变量名。
LOADABLE = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_REVIEW_CHAT_ID",
    "FEISHU_REVIEWER_OPEN_ID",
    "FEISHU_TENANT_KEY",
    "FEISHU_WORKSPACE_ID",
)


def load_from_file(path: Path) -> list[str]:
    """读取凭据文件，把缺失的变量写进 ``os.environ``。

    返回实际加载的变量名列表（不含值，避免把密钥写进日志）。
    """
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    loaded: list[str] = []
    for name in LOADABLE:
        if os.environ.get(name):
            continue
        match = re.search(rf"^\s*{name}:\s*(\S+)\s*$", text, re.MULTILINE)
        if match:
            os.environ[name] = match.group(1)
            loaded.append(name)
    return loaded
