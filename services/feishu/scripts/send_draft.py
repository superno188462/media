"""完整送审流程：建草稿 → 送审 → 发卡片 → 回填消息 ID。

与 ``send_review.py`` 的区别：这个脚本**先把状态写进审核状态机**，
所以卡片上的 review_id 是真实的，点按钮能驱动状态流转。

用法::

    uv run --with lark-oapi --no-project python scripts/send_draft.py \
        --title "内卷树懒 · 第一条图文" \
        --body-file body.txt \
        --image post.jpg \
        --account-id "bilibili:383714514"

**只送审，不发布。**
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]

sys.path.insert(0, str(_HERE.parents[1] / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "approval" / "src"))

from approval import ApprovalError, ApprovalService  # noqa: E402
from feishu.cards import ReviewDraftView, build_review_card  # noqa: E402
from feishu.credentials import load_from_file  # noqa: E402
from feishu.sender import FeishuReviewChannel, ReviewChannelError  # noqa: E402

CRED_FILE = PROJECT_ROOT / ".local" / "dsh" / ".credentials.yaml"
APPROVAL_ROOT = PROJECT_ROOT / ".local" / "approval"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--image", action="append", default=[])
    parser.add_argument("--account-id", required=True, help="如 bilibili:383714514")
    parser.add_argument("--account-label", default="内卷树懒")
    parser.add_argument("--workspace", default="cyber-sloth")
    parser.add_argument("--draft-id", default=None, help="给定时作为已有草稿的新版本送审")
    args = parser.parse_args()

    load_from_file(CRED_FILE)

    import os

    reviewer = os.environ.get("FEISHU_REVIEWER_OPEN_ID", "")
    if not reviewer:
        print("缺少 FEISHU_REVIEWER_OPEN_ID", file=sys.stderr)
        return 2

    body_path = Path(args.body_file)
    if not body_path.exists():
        print(f"正文文件不存在：{body_path}", file=sys.stderr)
        return 2
    body = body_path.read_text(encoding="utf-8").strip()

    image_paths = [Path(p) for p in args.image]
    for p in image_paths:
        if not p.exists():
            print(f"配图不存在：{p}", file=sys.stderr)
            return 2

    service = ApprovalService(APPROVAL_ROOT, args.workspace, {reviewer})

    manifest = {
        "title": args.title,
        "body": body,
        # 存绝对路径：发布执行器要能找回原图。契约的 Asset(asset_id/sha256)
        # 尚未实现，这里先记路径，属已知偏差。
        "images": [str(p.resolve()) for p in image_paths],
        "account_id": args.account_id,
    }

    try:
        if args.draft_id:
            draft = service.revise_draft(args.draft_id, manifest)
            print(f"草稿 {draft.draft_id} 已修订到 v{draft.revision}")
        else:
            draft = service.create_draft(manifest)
            print(f"已建草稿 {draft.draft_id} v{draft.revision}")
    except ApprovalError as exc:
        print(f"建稿失败：{exc}", file=sys.stderr)
        return 3

    try:
        review = service.request_review(draft.draft_id)
    except ApprovalError as exc:
        print(f"送审失败：{exc}", file=sys.stderr)
        return 4

    print(f"已建立审核 {review.review_id}（v{review.revision}，状态 {review.status}）")

    try:
        channel = FeishuReviewChannel()
    except ReviewChannelError as exc:
        print(f"初始化失败：{exc}", file=sys.stderr)
        return 5

    keys: list[str] = []
    for p in image_paths:
        try:
            key = channel.upload_image(p)
        except ReviewChannelError as exc:
            print(f"上传图片失败 {p.name}：{exc}", file=sys.stderr)
            print("（审核已建立但未发卡片；修好权限后可用同一 review 重发）", file=sys.stderr)
            return 6
        keys.append(key)
        print(f"已上传 {p.name} -> img_key={key}")

    view = ReviewDraftView(
        review_id=review.review_id,
        draft_id=draft.draft_id,
        revision=review.revision,
        content_digest=review.content_digest,
        title=args.title,
        body=body,
        image_keys=keys,
        target_account_label=args.account_label,
    )

    try:
        result = channel.send(view)
    except ReviewChannelError as exc:
        print(f"发送失败：{exc}", file=sys.stderr)
        return 7

    service.mark_delivery(review.review_id, result.provider_message_id, result.delivery_status)

    print()
    print("=== 送审完成（已写入状态机）===")
    print("draft_id        :", draft.draft_id)
    print("review_id       :", review.review_id)
    print("revision        :", review.revision)
    print("content_digest  :", review.content_digest)
    print("投递状态        :", result.delivery_status)
    print("飞书消息 ID     :", result.provider_message_id)
    print("审核有效期至    :", review.expires_at)

    card = build_review_card(view)
    print()
    print("卡片动作绑定值：")

    def walk(elements: list) -> None:
        for element in elements:
            if element.get("tag") == "button":
                v = element["value"]
                print(f"  {element['text']['content']}: {v['action']} / {v['review_id']} / v{v['revision']}")
            children = element.get("elements") or element.get("actions")
            if isinstance(children, list):
                walk(children)

    walk(card["elements"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
