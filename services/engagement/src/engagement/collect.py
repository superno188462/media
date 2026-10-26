"""评论采集：**不拉全量**，用增量 + 漏斗控制数量。

三层过滤，成本递增：

1. **服务端**：``comment list --unreplied`` 让 B 站自己筛掉已回复的
2. **水位线**：只取上次之后的新评论（``rpid`` 单调递增，可比较）
3. **本地规则**：``relevance.should_reply`` 剔掉垃圾/无意义，再按优先级排序取 Top N

只有走到最后的少数几条才值得花模型 token。

分页也有上限，避免一条动态几百条评论时无限翻页。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .relevance import Relevance, should_reply


@dataclass
class RawComment:
    """从平台读到的原始评论。

    ``root`` / ``parent`` 用于区分**楼中楼**：
    - 根评论：``root`` 与 ``parent`` 都为 None
    - 楼中楼：``root`` 是它所属的根评论 rpid，``parent`` 是被直接回复的那条
    """

    rpid: int
    oid: str
    user_mid: str
    user_name: str
    content: str
    time: str
    like: int = 0
    reply_count: int = 0
    is_supporter: bool = False
    root: int | None = None
    parent: int | None = None

    @property
    def is_nested(self) -> bool:
        return self.root is not None

    @classmethod
    def from_api(cls, item: dict, oid: str) -> "RawComment | None":
        try:
            rpid = int(item["rpid"])
        except (KeyError, TypeError, ValueError):
            return None
        user = item.get("user") or {}

        def _opt_int(key: str) -> int | None:
            value = item.get(key)
            if value in (None, ""):
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        return cls(
            rpid=rpid,
            oid=oid,
            user_mid=str(user.get("mid", "")),
            user_name=str(user.get("name", "")),
            content=str(item.get("content") or ""),
            time=str(item.get("time") or ""),
            like=int(item.get("like") or 0),
            reply_count=int(item.get("reply_count") or 0),
            is_supporter=bool(item.get("charged") or item.get("fan_medal")),
            root=_opt_int("root"),
            parent=_opt_int("parent"),
        )


@dataclass
class Triaged:
    """一条评论在漏斗里的结果。"""

    comment: RawComment
    relevance: Relevance

    @property
    def accepted(self) -> bool:
        return self.relevance.should_reply


class WatermarkStore:
    """记录每个评论区处理到哪一条，下次只取更新的。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def get(self, oid: str, comment_type: str) -> int:
        entry = self._load().get(f"{comment_type}:{oid}") or {}
        try:
            return int(entry.get("last_rpid", 0))
        except (TypeError, ValueError):
            return 0

    def set(self, oid: str, comment_type: str, last_rpid: int, last_time: str = "") -> None:
        data = self._load()
        key = f"{comment_type}:{oid}"
        previous = data.get(key) or {}
        if last_rpid <= int(previous.get("last_rpid", 0)):
            return  # 不倒退
        data[key] = {"last_rpid": last_rpid, "last_time": last_time}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def triage(
    comments: list[RawComment],
    *,
    limit: int = 10,
    self_mid: str = "",
    classifier=None,
) -> list[Triaged]:
    """对一批评论做本地过滤 + 排序，返回按优先级降序的结果（含被拒的）。

    ``classifier`` 可注入自定义判定（例如走大模型的 ``intent.classify``）；
    不传则用确定性的正则规则 ``should_reply``。
    """
    if classifier is None:
        def classifier(comment: RawComment) -> Relevance:
            return should_reply(comment.content, is_supporter=comment.is_supporter)

    results: list[Triaged] = []
    for comment in comments:
        if self_mid and comment.user_mid == self_mid:
            # 自己发的（比如刚才那条回复）不算候选
            results.append(
                Triaged(
                    comment,
                    Relevance(False, "self", 0, "self", "自己发的评论"),
                )
            )
            continue
        results.append(Triaged(comment, classifier(comment)))

    results.sort(key=lambda t: (-t.relevance.priority, -t.comment.rpid))
    accepted = [t for t in results if t.accepted][:limit]
    rejected = [t for t in results if not t.accepted]
    return accepted + rejected


def summarize(results: list[Triaged]) -> dict:
    """给出一份可读的漏斗统计。"""
    accepted = [t for t in results if t.accepted]
    by_rule: dict[str, int] = {}
    for item in results:
        if not item.accepted:
            by_rule[item.relevance.rule] = by_rule.get(item.relevance.rule, 0) + 1
    return {
        "total": len(results),
        "accepted": len(accepted),
        "rejected": len(results) - len(accepted),
        "rejected_by_rule": dict(sorted(by_rule.items(), key=lambda kv: -kv[1])),
        "categories": [t.relevance.category for t in accepted],
    }


#: 一页大约多少条。用来判断是否已到最后一页（不依赖平台返回的固定值）。
PAGE_SIZE_GUESS = 20


def fetch_new(
    client,
    oid: str,
    comment_type: str,
    watermarks: WatermarkStore,
    *,
    max_pages: int = 2,
    limit: int = 10,
    self_mid: str = "",
    unreplied: bool = True,
    classifier=None,
    include_nested: bool = True,
    max_nested_roots: int = 3,
) -> tuple[list[Triaged], dict]:
    """拉取新评论并做漏斗，返回 (结果列表, 统计)。

    只取 ``rpid`` 大于水位线的新评论，翻页数有上限。处理完后把水位线
    推进到本次见到的最大 rpid——**被拒的评论也不会再被反复检查**。

    楼中楼：``comment list`` 只给根评论和几条预览，所以对有回复的根评论
    再调一次 ``comment replies``。为避免请求爆炸，只查前 ``max_nested_roots``
    个有新回复的根评论。

    **已知限制**：只检查本次翻页看到的根评论。若新楼中楼出现在更早的
    根评论下（已不在当前页），本次不会发现；那条回复的 rpid 更大，
    会在下次该根评论重新出现在分页里时被捕获。
    """
    last = watermarks.get(oid, comment_type)
    collected: list[RawComment] = []
    roots_with_replies: list[int] = []
    max_seen = last
    pages_read = 0
    errors: list[str] = []
    nested_fetched = 0

    for page in range(1, max_pages + 1):
        items, meta = client.list_comments(oid, comment_type, page, unreplied=unreplied)
        if meta.get("error"):
            errors.append(str(meta["error"]))
            break
        pages_read += 1
        if not items:
            break
        for item in items:
            parsed = RawComment.from_api(item, oid)
            if parsed is None:
                continue
            max_seen = max(max_seen, parsed.rpid)
            if parsed.rpid > last:
                collected.append(parsed)
            if include_nested and parsed.reply_count > 0:
                roots_with_replies.append(parsed.rpid)
        if len(items) < PAGE_SIZE_GUESS:
            break  # 已经是最后一页

    # 楼中楼：只查有限个根评论，避免请求数量失控。
    for root_rpid in roots_with_replies[:max_nested_roots]:
        nested_items, meta = client.list_replies(oid, root_rpid, comment_type)
        if meta.get("error"):
            errors.append(f"replies {root_rpid}: {meta['error']}")
            continue
        nested_fetched += 1
        for item in nested_items:
            parsed = RawComment.from_api(item, oid)
            if parsed is None:
                continue
            if parsed.root is None:
                parsed.root = root_rpid  # 保底：接口没给 root 时用查询的根补上
            max_seen = max(max_seen, parsed.rpid)
            if parsed.rpid > last:
                collected.append(parsed)

    results = triage(collected, limit=limit, self_mid=self_mid, classifier=classifier)
    stats = summarize(results)
    stats["pages_read"] = pages_read
    stats["new"] = len(collected)
    stats["nested_roots_checked"] = nested_fetched
    stats["nested_found"] = sum(1 for c in collected if c.is_nested)
    stats["watermark_before"] = last
    stats["watermark_after"] = max_seen
    if errors:
        stats["errors"] = errors

    if max_seen > last:
        watermarks.set(oid, comment_type, max_seen)
    return results, stats


RE_RPID = re.compile(r"\d+")
