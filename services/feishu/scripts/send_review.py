"""把一条草稿发到飞书审核群，等审核人点按钮。

用法::

    uv run --with lark-oapi --no-project python scripts/send_review.py \
        --title "内卷树懒 · 第一条图文" \
        --body-file body.txt \
        --image path/to/post.jpg \
        --account-label "内卷树懒"

它只做「送审」这一件事：上传图片 → 构造卡片 → 发到审核群。
**不发布任何内容**。审核人点「通过并发布」后，后续由受信入口处理。

凭证从环境变量读取：``FEISHU_APP_ID`` / ``FEISHU_APP_SECRET`` / ``FEISHU_REVIEW_CHAT_ID``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from feishu.cards import ReviewDraftView, build_review_card  # noqa: E402
from feishu.credentials import load_from_file  # noqa: E402
from feishu.sender import FeishuReviewChannel, ReviewChannelError  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRED_FILE = PROJECT_ROOT / ".local" / "dsh" / ".credentials.yaml"


def compute_digest(title: str, body: str, image_names: list[str], account: str) -> str:
    """内容摘要。绑定「审核的是哪一版内容」。"""
    material = json.dumps(
        {"title": title, "body": body, "images": image_names, "account": account},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True, help="正文文件路径（UTF-8）")
    parser.add_argument("--image", action="append", default=[], help="配图路径，可重复，顺序即发布顺序")
    parser.add_argument("--account-label", default="内卷树懒")
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--review-id", default=None)
    args = parser.parse_args()

    load_from_file(CRED_FILE)

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

    review_id = args.review_id or f"rv-{uuid.uuid4().hex[:12]}"
    digest = compute_digest(
        args.title, body, [p.name for p in image_paths], args.account_label
    )

    try:
        channel = FeishuReviewChannel()
    except ReviewChannelError as exc:
        print(f"初始化失败：{exc}", file=sys.stderr)
        return 3

    keys: list[str] = []
    for p in image_paths:
        try:
            key = channel.upload_image(p)
        except ReviewChannelError as exc:
            print(f"上传图片失败 {p.name}：{exc}", file=sys.stderr)
            return 4
        keys.append(key)
        print(f"已上传 {p.name} -> img_key={key}")

    view = ReviewDraftView(
        review_id=review_id,
        draft_id=f"draft-{digest[:8]}",
        revision=args.revision,
        content_digest=digest,
        title=args.title,
        body=body,
        image_keys=keys,
        target_account_label=args.account_label,
    )

    try:
        result = channel.send(view)
    except ReviewChannelError as exc:
        print(f"发送失败：{exc}", file=sys.stderr)
        return 5

    print()
    print("=== 送审完成 ===")
    print("review_id      :", review_id)
    print("revision       :", args.revision)
    print("content_digest :", digest)
    print("投递状态       :", result.delivery_status)
    print("飞书消息 ID    :", result.provider_message_id)
    if result.detail:
        print("说明           :", result.detail)

    # 卡片预览（便于核对实际发出去的绑定值）
    card = build_review_card(view)
    print()
    print("卡片动作绑定值：")

    def walk(elements: list) -> None:
        for element in elements:
            if element.get("tag") == "button":
                v = element["value"]
                print(
                    f"  {element['text']['content']}: "
                    f"{v['action']} / {v['review_id']} / v{v['revision']}"
                )
            children = element.get("elements") or element.get("actions")
            if isinstance(children, list):
                walk(children)

    walk(card["elements"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
