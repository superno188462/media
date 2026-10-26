"""视频送审：抽关键帧 → 上传飞书 → 建稿送审 → 发卡片。

用法::

    uv run --with playwright --with lark-oapi --no-project python scripts/send_video_review.py \
        --video .runtime/demo_tts.mp4 \
        --title "内卷树懒 Day 0" \
        --body-file .local/content/demo/body.txt \
        --account-id "bilibili:383714514" \
        --keyframes 5

为什么是「关键帧 + 元信息」而不是视频本身：
**飞书卡片不能内嵌播放视频**，`im/v1/images` 也只收图片。
所以卡片给出关键帧、时长、分辨率、体积和完整正文；
完整视频由审核人在本机确认，或另配只读预览入口（``--preview-url``）。

**本脚本只送审，不发布。**
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]
CONTENT_ROOT = _HERE.parents[1]

sys.path.insert(0, str(CONTENT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "approval" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "feishu" / "src"))

from approval import ApprovalError, ApprovalService  # noqa: E402
from content import ffmpeg as ffmpeg_tool  # noqa: E402
from content.video.compose import ComposeError, extract_keyframes  # noqa: E402
from feishu.cards import ReviewDraftView, VideoInfo, build_review_card  # noqa: E402
from feishu.credentials import load_from_file  # noqa: E402
from feishu.sender import FeishuReviewChannel, ReviewChannelError  # noqa: E402

CRED_FILE = PROJECT_ROOT / ".local" / "dsh" / ".credentials.yaml"
APPROVAL_ROOT = PROJECT_ROOT / ".local" / "approval"
#: 抽帧中间产物放运行区（ffmpeg 写不了 .local）。
KEYFRAME_DIR = CONTENT_ROOT / ".runtime" / "review-keyframes"


def fail(code: str, message: str, hint: str = "") -> int:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if hint:
        payload["error"]["hint"] = hint
    print(json.dumps(payload, ensure_ascii=False))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, help="mp4 路径")
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True, help="正文文件（UTF-8）")
    parser.add_argument("--account-id", required=True, help="如 bilibili:383714514")
    parser.add_argument("--account-label", default="内卷树懒")
    parser.add_argument("--keyframes", type=int, default=5)
    parser.add_argument("--preview-url", default="", help="完整视频的只读预览地址（可选）")
    parser.add_argument("--draft-id", default="",
                        help="对已退回的草稿出新版本并再送审；不给则新建草稿")
    parser.add_argument("--workspace", default="cyber-sloth")
    args = parser.parse_args()

    load_from_file(CRED_FILE)
    reviewer = os.environ.get("FEISHU_REVIEWER_OPEN_ID", "")
    if not reviewer:
        return fail("NO_CREDENTIAL", "缺少 FEISHU_REVIEWER_OPEN_ID")

    video = Path(args.video)
    if not video.is_file():
        return fail("INVALID_ARGS", f"视频不存在：{video}")

    body_path = Path(args.body_file)
    if not body_path.is_file():
        return fail("INVALID_ARGS", f"正文不存在：{body_path}")
    body = body_path.read_text(encoding="utf-8").strip()
    if not body:
        return fail("INVALID_ARGS", "正文为空")

    info = ffmpeg_tool.probe(video)
    duration_ms = info.get("duration_ms")
    if not duration_ms or not info.get("has_video"):
        return fail("INVALID_VIDEO", "读不到视频时长或不是视频文件")

    manifest = {
        "content_type": "video",
        "title": args.title,
        "body": body,
        "video": str(video.resolve()),
        "account_id": args.account_id,
    }

    service = ApprovalService(APPROVAL_ROOT, args.workspace, {reviewer})
    try:
        if args.draft_id:
            # 退回后出新版本：revision+1，历史版本不被覆盖
            draft = service.revise_draft(args.draft_id, manifest)
        else:
            draft = service.create_draft(manifest)
        review = service.request_review(draft.draft_id)
    except ApprovalError as exc:
        return fail(exc.code, exc.message, exc.hint)

    # --- 抽关键帧并上传 ---
    try:
        frames = extract_keyframes(video, args.keyframes, KEYFRAME_DIR)
    except ComposeError as exc:
        return fail("KEYFRAME_FAILED", str(exc))

    try:
        channel = FeishuReviewChannel()
    except ReviewChannelError as exc:
        return fail("FEISHU_INIT_FAILED", str(exc))

    keys: list[str] = []
    for frame in frames:
        try:
            keys.append(channel.upload_image(frame))
        except ReviewChannelError as exc:
            return fail("UPLOAD_FAILED", f"{frame.name}: {exc}")

    # --- 先发视频消息，再发卡片 ---
    # 飞书 msg_type=media 的消息能在客户端直接播放；卡片本身不能播。
    # 顺序很关键：卡片里要说「完整视频已作为上一条消息发出」。
    try:
        video_delivery = channel.send_video(
            video, duration_ms, cover_image_key=keys[0] if keys else ""
        )
    except ReviewChannelError as exc:
        return fail("VIDEO_SEND_FAILED", str(exc))

    view = ReviewDraftView(
        review_id=review.review_id,
        draft_id=draft.draft_id,
        revision=review.revision,
        content_digest=review.content_digest,
        title=args.title,
        body=body,
        image_keys=[],
        target_account_label=args.account_label,
        video=VideoInfo(
            duration_ms=duration_ms,
            width=info.get("width") or 0,
            height=info.get("height") or 0,
            byte_size=video.stat().st_size,
            keyframe_keys=keys,
            preview_url=args.preview_url,
            video_message_id=video_delivery.provider_message_id or "",
        ),
    )

    try:
        delivery = channel.send(view)
    except ReviewChannelError as exc:
        return fail("SEND_FAILED", str(exc))

    service.mark_delivery(review.review_id, delivery.provider_message_id, delivery.delivery_status)

    card = build_review_card(view)
    print(json.dumps({
        "ok": True,
        "data": {
            "draft_id": draft.draft_id,
            "review_id": review.review_id,
            "revision": review.revision,
            "content_digest": review.content_digest,
            "video": str(video),
            "duration_ms": duration_ms,
            "width": info.get("width"),
            "height": info.get("height"),
            "byte_size": video.stat().st_size,
            "keyframes": keys,
            "video_message_id": video_delivery.provider_message_id,
            "video_delivery_status": video_delivery.delivery_status,
            "preview_url": args.preview_url or None,
            "delivery_status": delivery.delivery_status,
            "provider_message_id": delivery.provider_message_id,
            "card_header": card["header"]["title"]["content"],
            "expires_at": review.expires_at,
            "playable_in_feishu": video_delivery.delivery_status == "SENT",
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
