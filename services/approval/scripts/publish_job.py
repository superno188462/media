"""执行一个已批准的发布任务（QUEUED → 平台）。

用法::

    # 预览：只跑 bili --dry-run，**不改动任何状态**
    uv run python scripts/publish_job.py job-xxxx

    # 确认后真发
    uv run python scripts/publish_job.py job-xxxx --yes

**这是真正的外发操作。** 不加 ``--yes`` 只做预览。

设计要点：

- 预览不经过状态机。早期版本让 dry-run 走 ``execute_publish``，
  结果把 QUEUED 直接推到 FAILED，白白消耗了一次批准。预览必须是纯只读。
- 正文用 ``--file`` 传，避免多行文本在命令行里的引号转义问题。
- 一律带 ``--wait``，让 bili-cli 自己处理 60 秒的本地限流。
- 提交后结果不明（``RESULT_UNKNOWN``）绝不自动重发。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

sys.path.insert(0, str(_HERE.parents[1] / "src"))

from approval import ApprovalError, ApprovalService, PublishObservation  # noqa: E402

APPROVAL_ROOT = PROJECT_ROOT / ".local" / "approval"
BILI_CMD = PROJECT_ROOT / "bili.cmd"


def run_bili(args: list[str]) -> tuple[int, dict | None, str]:
    """调用 bili.cmd。用 cmd /c 而不是 shell=True，避免参数被二次解析。"""
    proc = subprocess.run(
        ["cmd", "/c", str(BILI_CMD), *args],
        cwd=str(PROJECT_ROOT),
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


def build_args(body: str, images: list[str], dry_run: bool) -> tuple[list[str], Path]:
    """拼参数。正文写临时文件用 --file 传，避免换行转义。"""
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".txt", delete=False
    )
    handle.write(body)
    handle.close()
    body_file = Path(handle.name)

    args = ["dynamic", "post", "--file", str(body_file)]
    for image in images:
        args += ["--image", image]
    args.append("--wait")
    if dry_run:
        args.append("--dry-run")
    return args, body_file


def find_existing_dynamic(body: str) -> dict | None:
    """发布结果不确定时，核对平台侧是否已经有这条动态。"""
    code, parsed, _ = run_bili(["dynamic", "list"])
    if code != 0 or not parsed or not parsed.get("ok"):
        return None
    for item in (parsed.get("data") or {}).get("items") or []:
        if (item.get("text") or "").strip() == body.strip():
            return item
    return None


def make_publisher():
    def publisher(manifest: dict) -> PublishObservation:
        body = manifest["body"]
        images = manifest.get("images") or []

        missing = [p for p in images if not Path(p).exists()]
        if missing:
            return PublishObservation(
                state="NOT_SUBMITTED", detail=f"配图缺失，未提交：{missing}"
            )

        args, body_file = build_args(body, images, dry_run=False)
        try:
            code, parsed, raw = run_bili(args)
        finally:
            body_file.unlink(missing_ok=True)

        if code == 0 and parsed and parsed.get("ok"):
            data = parsed.get("data") or {}
            item_id = data.get("id") or data.get("dyn_id")
            return PublishObservation(
                state="PUBLISHED" if item_id else "SUBMITTED",
                platform_item_id=str(item_id) if item_id else None,
                platform_url=data.get("url"),
                detail="bili-cli 返回成功",
            )

        error = (parsed or {}).get("error") or {}
        message = error.get("message") or raw[:300]
        code_name = error.get("code")

        # 明确没发出去的情况，不要误判为未知。
        if code_name in ("rate_limited", "validation_error", "not_logged_in"):
            return PublishObservation(state="NOT_SUBMITTED", detail=f"{code_name}: {message}")

        # 其余失败先核对平台证据（假失败：平台已成功、CLI 收尾失败）。
        found = find_existing_dynamic(body)
        if found:
            return PublishObservation(
                state="PUBLISHED",
                platform_item_id=str(found.get("id")),
                platform_url=found.get("url"),
                detail=f"CLI 报错但平台已确认存在：{message}",
            )
        return PublishObservation(state="RESULT_UNKNOWN", detail=f"结果不确定：{message}")

    return publisher


# ---------------------------------------------------------------- 视频投稿

#: 从正文里解析 B站 话题标签。# 后面不能有空白。
TAG_PATTERN = re.compile(r"#([^\s#]{1,20})")

#: B站 投稿要求 1–10 个标签。
MIN_TAGS = 1
MAX_TAGS = 10
FALLBACK_TAGS = ["AI"]

TITLE_MAX = 80
DESC_MAX = 2000


def is_video(manifest: dict) -> bool:
    return bool(manifest.get("video"))


def is_private(manifest: dict) -> bool:
    return str(manifest.get("visibility") or "").lower() in {"private", "self"}


def extract_tags(manifest: dict) -> list[str]:
    """取标签：显式 tags 优先，否则从正文的 #话题 解析。"""
    raw = [str(t).strip() for t in (manifest.get("tags") or []) if str(t).strip()]
    if not raw:
        raw = TAG_PATTERN.findall(manifest.get("body") or "")

    seen: set[str] = set()
    ordered: list[str] = []
    for tag in raw:
        if tag not in seen:
            seen.add(tag)
            ordered.append(tag)

    if not ordered:
        ordered = list(FALLBACK_TAGS)
    return ordered[:MAX_TAGS]


def build_video_args(
    video: str,
    title: str,
    tags: list[str],
    body: str,
    private: bool,
    cover: str | None = None,
) -> tuple[list[str], Path]:
    """拼 ``bili upload video`` 参数。简介写文件，避免换行转义。"""
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".txt", delete=False
    )
    handle.write(body)
    handle.close()
    body_file = Path(handle.name)

    args = ["upload", "video", video, "--title", title, "--desc-file", str(body_file)]
    for tag in tags:
        args += ["--tag", tag]
    # 契约要求 AI 声明；bili-cli 默认就开，这里显式写出来避免默认值变化。
    args.append("--ai-declare")
    if private:
        args.append("--private")
    if cover:
        args += ["--cover", cover]
    return args, body_file


def find_existing_upload(title: str) -> dict | None:
    """投稿结果不确定时，核对平台侧是否已经有这个标题的稿件。"""
    code, parsed, _ = run_bili(["upload", "list"])
    if code != 0 or not parsed or not parsed.get("ok"):
        return None
    for item in (parsed.get("data") or {}).get("items") or []:
        if (item.get("title") or "").strip() == title.strip():
            return item
    return None


def make_video_publisher():
    def publisher(manifest: dict) -> PublishObservation:
        video = manifest.get("video") or ""
        title = (manifest.get("title") or "").strip()
        body = manifest.get("body") or ""

        if not video or not Path(video).is_file():
            return PublishObservation(state="NOT_SUBMITTED", detail=f"视频缺失：{video}")
        if not title:
            return PublishObservation(state="NOT_SUBMITTED", detail="缺少标题")

        tags = extract_tags(manifest)
        args, body_file = build_video_args(
            video, title, tags, body, is_private(manifest), manifest.get("cover")
        )
        try:
            code, parsed, raw = run_bili(args)
        finally:
            body_file.unlink(missing_ok=True)

        if code == 0 and parsed and parsed.get("ok"):
            data = parsed.get("data") or {}
            bvid = data.get("bvid")
            return PublishObservation(
                state="PUBLISHED" if bvid else "SUBMITTED",
                platform_item_id=str(bvid) if bvid else None,
                platform_url=data.get("url"),
                detail="bili-cli 返回成功",
            )

        error = (parsed or {}).get("error") or {}
        message = error.get("message") or raw[:300]
        code_name = error.get("code")

        if code_name in ("rate_limited", "validation_error", "not_logged_in"):
            return PublishObservation(state="NOT_SUBMITTED", detail=f"{code_name}: {message}")

        # 上传可能已经成功但收尾失败，先去稿件列表核对。
        found = find_existing_upload(title)
        if found:
            bvid = found.get("bvid")
            return PublishObservation(
                state="PUBLISHED",
                platform_item_id=str(bvid) if bvid else None,
                platform_url=f"https://www.bilibili.com/video/{bvid}" if bvid else None,
                detail=f"CLI 报错但平台已确认存在：{message}",
            )
        return PublishObservation(state="RESULT_UNKNOWN", detail=f"结果不确定：{message}")

    return publisher


def preview_video(manifest: dict) -> int:
    """视频预览：只展示计划，**不调用 bili**。

    ``bili upload video`` 没有 ``--dry-run``，调用就等于真上传，
    所以这里绝不发起请求。
    """
    video = manifest.get("video") or ""
    title = (manifest.get("title") or "").strip()
    body = manifest.get("body") or ""
    tags = extract_tags(manifest)
    private = is_private(manifest)
    path = Path(video) if video else None
    exists = bool(path and path.is_file())

    print("视频投稿计划（预览不调用 bili：upload video 没有 dry-run）")
    print(f"  文件    : {video}（{'存在' if exists else '缺失'}）")
    if exists and path is not None:
        print(f"  大小    : {path.stat().st_size / 1048576:.2f} MB")
    print(f"  标题    : {title}（{len(title)} 字，上限 {TITLE_MAX}）")
    print(f"  简介    : {len(body)} 字（上限 {DESC_MAX}）")
    print(f"  标签    : {len(tags)} 个 -> {tags}")
    print(f"  可见性  : {'仅自己可见' if private else '公开'}")
    print("  AI 声明 : 已勾选（--ai-declare）")

    problems: list[str] = []
    if not exists:
        problems.append("视频文件不存在")
    if not title:
        problems.append("缺少标题")
    if len(title) > TITLE_MAX:
        problems.append(f"标题超过 {TITLE_MAX} 字（{len(title)}）")
    if len(body) > DESC_MAX:
        problems.append(f"简介超过 {DESC_MAX} 字（{len(body)}）")
    if not MIN_TAGS <= len(tags) <= MAX_TAGS:
        problems.append(f"标签数量不合规（{len(tags)}）")

    if problems:
        print()
        for problem in problems:
            print(f"  ✗ {problem}")
        return 1
    print("\n  ✓ 可以提交")
    return 0


def preview(manifest: dict) -> int:
    images = manifest.get("images") or []
    args, body_file = build_args(manifest["body"], images, dry_run=True)
    print("将执行：")
    print("  bili", " ".join(a if a != str(body_file) else "<正文临时文件>" for a in args))
    print(f"  正文长度 {len(manifest['body'])} 字，配图 {len(images)} 张")
    for image in images:
        print(f"    - {image} ({'存在' if Path(image).exists() else '缺失'})")
    print()
    try:
        code, parsed, raw = run_bili(args)
    finally:
        body_file.unlink(missing_ok=True)

    print("bili-cli 返回：")
    print(json.dumps(parsed, ensure_ascii=False, indent=2) if parsed else raw[:800])
    return 0 if code == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--yes", action="store_true", help="真正提交；不加只做预览")
    parser.add_argument("--workspace", default="cyber-sloth")
    args = parser.parse_args()

    import re

    cred = PROJECT_ROOT / ".local" / "dsh" / ".credentials.yaml"
    reviewer = ""
    if cred.exists():
        match = re.search(
            r"^\s*FEISHU_REVIEWER_OPEN_ID:\s*(\S+)\s*$",
            cred.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            reviewer = match.group(1)
    if not reviewer:
        print("缺少 FEISHU_REVIEWER_OPEN_ID（用于加载工作区配置）", file=sys.stderr)
        return 2

    service = ApprovalService(APPROVAL_ROOT, args.workspace, {reviewer})

    jobs = {job.job_id: job for job in service.list_jobs()}
    job = jobs.get(args.job_id)
    if job is None:
        print(f"任务不存在：{args.job_id}", file=sys.stderr)
        return 3

    print(f"任务 {job.job_id} 状态={job.status} 审核={job.review_id}")
    print(f"  账号={job.target_account_id} 草稿={job.draft_id} v{job.revision}")
    print(f"  批准时间={job.approved_at} 提交期限={job.submit_deadline_at}")

    draft = service.get_draft(job.draft_id)

    if not args.yes:
        print("\n=== 预览模式（不改动任何状态）===\n")
        if is_video(draft.manifest):
            return preview_video(draft.manifest)
        return preview(draft.manifest)

    print("\n=== 真发模式 ===\n")
    publisher = make_video_publisher() if is_video(draft.manifest) else make_publisher()
    try:
        done = service.execute_publish(job.job_id, publisher)
    except ApprovalError as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 4

    print("=== 执行结果 ===")
    print("状态        :", done.status)
    print("平台作品 ID :", done.platform_item_id)
    print("平台链接    :", done.platform_url)
    if done.last_error:
        print("错误        :", json.dumps(done.last_error, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
