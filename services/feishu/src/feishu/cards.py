"""审核卡片构建。

卡片是审核人在飞书里看到的完整审核内容。规格要求：
- 卡片必须承载**完整**正文与图片，不能用摘要替代（PRD 第 3 节）。
- 三个动作：通过并发布 / 退回修改 / 取消审核（BE-IF-02、UI-CS）。
- 卡片必须绑定版本与摘要，收到旧卡片时服务端要能拒绝（BE-RULE-02、STALE_REVIEW）。

本模块只负责**构造**卡片载荷，不发送、不解析回调。发送在 sender.py，
回调验证在 events.py。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .events import FEEDBACK_MAX_LEN


@dataclass
class VideoInfo:
    """视频审核的附加信息。

    飞书卡片**不能内嵌播放视频**，所以只能用「关键帧 + 元信息」表达内容。
    审核人要看完整视频，需要另开只读预览入口（见 ``preview_note``）。
    """

    duration_ms: int
    width: int
    height: int
    byte_size: int
    #: 已上传的关键帧 img_key，按时间顺序。
    keyframe_keys: list[str]
    #: 完整视频的只读预览地址；没有可靠入口时留空，卡片会如实说明。
    preview_url: str = ""
    #: 视频已作为独立消息发到同一会话时填消息 ID。
    #: 飞书 ``msg_type=media`` 的消息能在客户端直接播放，审核人点开即可。
    video_message_id: str = ""

    @property
    def duration_text(self) -> str:
        # 向下取整：26.9 秒显示 0:26，不显示比实际更长的时长
        total_seconds = int(self.duration_ms / 1000)
        return f"{total_seconds // 60}:{total_seconds % 60:02d}"

    @property
    def size_text(self) -> str:
        mb = self.byte_size / (1024 * 1024)
        return f"{mb:.1f} MB"


@dataclass
class ReviewDraftView:
    """送审内容的只读视图。

    由调用方从草稿快照填充；本模块不读数据库、不读文件。
    """

    review_id: str
    draft_id: str
    revision: int
    content_digest: str
    title: str
    body: str
    #: 已上传到飞书后拿到的 img_key。卡片用它显示图片，
    #: 本地路径或任意外链都不行（先把图上传，见 sender.upload_image）。
    image_keys: list[str]
    #: 目标账号展示名，让审核人知道会发到哪个号。
    target_account_label: str = ""
    #: 视频审核时填写；图文留 None。
    video: "VideoInfo | None" = None


#: 三个动作的 value。事件回调里会原样带回，服务端据此校验绑定。
ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"
ACTION_CANCEL = "cancel"


def build_review_card(view: ReviewDraftView) -> dict[str, Any]:
    """构造交互式审核卡片载荷。"""
    elements: list[dict[str, Any]] = []

    elements.append(
        {
            "tag": "markdown",
            "content": f"**{view.title}**",
        }
    )

    # 绑定信息放进卡片，审核人看得到版本，服务端也据此校验。
    elements.append(
        {
            "tag": "markdown",
            "content": (
                f"版本 `v{view.revision}`　草稿 `{view.draft_id}`\n"
                f"摘要 `{view.content_digest[:16]}…`"
                + (f"\n目标账号：**{view.target_account_label}**" if view.target_account_label else "")
            ),
        }
    )
    elements.append({"tag": "hr"})
    elements.append({"tag": "markdown", "content": view.body})

    if view.video is not None:
        elements.append({"tag": "hr"})
        video = view.video
        elements.append(
            {
                "tag": "markdown",
                "content": (
                    f"🎬 **视频**　时长 {video.duration_text}　"
                    f"{video.width}×{video.height}　{video.size_text}"
                ),
            }
        )
        for index, key in enumerate(video.keyframe_keys, 1):
            elements.append(
                {
                    "tag": "img",
                    "img_key": key,
                    "alt": {
                        "tag": "plain_text",
                        "content": f"关键帧 {index}/{len(video.keyframe_keys)}",
                    },
                }
            )
        if video.preview_url:
            elements.append(
                {
                    "tag": "markdown",
                    "content": f"[查看完整视频]({video.preview_url})",
                }
            )
        elif video.video_message_id:
            elements.append(
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": (
                                "完整视频已作为上一条消息发出，"
                                "点开即可播放；以上是关键帧预览。"
                            ),
                        }
                    ],
                }
            )
        else:
            # 如实说明：飞书卡片不能播放视频，这里只给了关键帧。
            elements.append(
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": (
                                "卡片无法播放视频，以上是关键帧。"
                                "完整视频需在审核机上确认后再批准。"
                            ),
                        }
                    ],
                }
            )
    elif view.image_keys:
        elements.append({"tag": "hr"})
        for index, key in enumerate(view.image_keys, 1):
            elements.append(
                {
                    "tag": "img",
                    "img_key": key,
                    "alt": {
                        "tag": "plain_text",
                        "content": f"配图 {index}/{len(view.image_keys)}",
                    },
                }
            )

    elements.append({"tag": "hr"})
    # 输入框 + 三个按钮放在同一个 form 里：按钮用 form_submit，
    # 这样点击时飞书会把输入框内容放进 action.form_value 回传。
    elements.append(
        {
            "tag": "form",
            "name": "review_form",
            "elements": [
                {
                    "tag": "input",
                    "name": "feedback",
                    "placeholder": {
                        "tag": "plain_text",
                        "content": "退回意见（可选，最多 500 字；批准/取消时忽略）",
                    },
                    "max_length": FEEDBACK_MAX_LEN,
                },
                {
                    "tag": "button",
                    "name": "approve_btn",
                    "text": {"tag": "plain_text", "content": "通过并发布"},
                    "type": "primary",
                    "action_type": "form_submit",
                    "value": _action_value(view, ACTION_APPROVE),
                },
                {
                    "tag": "button",
                    "name": "reject_btn",
                    "text": {"tag": "plain_text", "content": "退回修改"},
                    "type": "danger",
                    "action_type": "form_submit",
                    "value": _action_value(view, ACTION_REJECT),
                },
                {
                    "tag": "button",
                    "name": "cancel_btn",
                    "text": {"tag": "plain_text", "content": "取消审核"},
                    "type": "default",
                    "action_type": "form_submit",
                    "value": _action_value(view, ACTION_CANCEL),
                },
            ],
        }
    )
    elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "通过后由后台自动投稿；批准只对上面这个版本有效。",
                }
            ],
        }
    )

    is_video = view.video is not None
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "视频待审核" if is_video else "内容待审核",
            },
            "template": "purple" if is_video else "orange",
        },
        "elements": elements,
    }


def _action_value(view: ReviewDraftView, action: str) -> dict[str, str]:
    """动作按钮携带的绑定值。

    服务端收到回调后，用这里的 review_id / revision / digest 校验
    「这个动作确实绑定在当前版本上」。模型填的 JSON 不能建立可信身份，
    但它也不能伪造对一个不存在的版本的批准。
    """
    return {
        "action": action,
        "review_id": view.review_id,
        "revision": str(view.revision),
        "content_digest": view.content_digest,
    }


def card_payload_text(card: dict[str, Any]) -> str:
    """把卡片载荷转成 JSON 字符串，供发送时使用。"""
    return json.dumps(card, ensure_ascii=False)
