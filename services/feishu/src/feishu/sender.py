"""审核卡片发送。

对应 BE-IF-04 的 `ReviewChannel.send(review, draft)`：
只向已配置会话发送审核内容；内部错误转换为契约错误，
不回传原始 SDK 类型（避免 SDK 对象泄漏进模型上下文）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .cards import ReviewDraftView, build_review_card, card_payload_text

#: 投递状态，对应 Schema 的 DeliveryStatus。
DELIVERY_SENT = "SENT"
DELIVERY_QUEUED = "QUEUED"
DELIVERY_UNKNOWN = "UNKNOWN"
DELIVERY_FAILED = "FAILED"

#: 飞书 im/v1/files 的单文件上限（30 MB）。
MAX_VIDEO_BYTES = 30 * 1024 * 1024

#: 客户端超时（秒）。视频上传明显慢于文本，默认值会 ReadTimeout。
UPLOAD_TIMEOUT_SECONDS = 180


@dataclass
class DeliveryResult:
    """投递结果。``provider_message_id`` 未确认时为 None。"""

    delivery_status: str
    provider_message_id: str | None
    detail: str = ""


class ReviewChannelError(RuntimeError):
    """发送审核卡片失败。"""


class FeishuReviewChannel:
    """通过飞书自建应用发送审核卡片。"""

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        *,
        chat_id: str | None = None,
    ) -> None:
        self.app_id = app_id or os.environ.get("FEISHU_APP_ID", "")
        self.app_secret = app_secret or os.environ.get("FEISHU_APP_SECRET", "")
        self.chat_id = chat_id or os.environ.get("FEISHU_REVIEW_CHAT_ID", "")
        if not self.app_id or not self.app_secret:
            raise ReviewChannelError(
                "缺少 FEISHU_APP_ID / FEISHU_APP_SECRET：请写进 .local/dsh/.credentials.yaml 或环境变量。"
            )
        if not self.chat_id:
            raise ReviewChannelError(
                "缺少 FEISHU_REVIEW_CHAT_ID：审核会话尚未配置（规格要求先定审核会话与审核人 allowlist）。"
            )

    def _client(self):
        import lark_oapi as lark

        return (
            lark.Client.builder()
            .app_id(self.app_id)
            .app_secret(self.app_secret)
            # 视频上传比文本慢得多，默认超时不够（实测会 ReadTimeout）。
            .timeout(UPLOAD_TIMEOUT_SECONDS)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )

    def upload_image(self, path: Path) -> str:
        """上传图片到飞书，返回 img_key。

        卡片里的 ``img`` 元素只能用 img_key，本地路径或任意外链都不行。
        """
        from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody

        handle = path.open("rb")
        try:
            request = (
                CreateImageRequest.builder()
                .request_body(
                    CreateImageRequestBody.builder()
                    .image(handle)
                    .image_type("message")
                    .build()
                )
                .build()
            )
            response = self._client().im.v1.image.create(request)
        except Exception as exc:  # noqa: BLE001
            raise ReviewChannelError(f"上传图片失败：{type(exc).__name__}") from exc
        finally:
            handle.close()

        if not response.success():
            raise ReviewChannelError(
                f"上传图片失败：平台返回 code={response.code} msg={response.msg}"
            )

        key = getattr(response.data, "image_key", None)
        if not key:
            raise ReviewChannelError("上传图片成功但未返回 image_key")
        return key

    def upload_video(self, path: Path, duration_ms: int) -> str:
        """上传视频文件，返回 file_key。

        飞书 ``im/v1/files`` 上限 30 MB。超过时这里直接拒绝，
        避免上传到一半才失败。
        """
        size = path.stat().st_size
        if size > MAX_VIDEO_BYTES:
            raise ReviewChannelError(
                f"视频 {size / 1048576:.1f} MB 超过飞书 30 MB 上限；"
                "先压缩或改用外部链接。"
            )

        from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody

        handle = path.open("rb")
        try:
            request = (
                CreateFileRequest.builder()
                .request_body(
                    CreateFileRequestBody.builder()
                    .file_type("mp4")
                    .file_name(path.name)
                    .duration(str(duration_ms))
                    .file(handle)
                    .build()
                )
                .build()
            )
            response = self._client().im.v1.file.create(request)
        except Exception as exc:  # noqa: BLE001
            raise ReviewChannelError(f"上传视频失败：{type(exc).__name__}") from exc
        finally:
            handle.close()

        if not response.success():
            raise ReviewChannelError(
                f"上传视频失败：平台返回 code={response.code} msg={response.msg}"
            )

        key = getattr(response.data, "file_key", None)
        if not key:
            raise ReviewChannelError("上传视频成功但未返回 file_key")
        return key

    def send_video(
        self,
        path: Path,
        duration_ms: int,
        *,
        cover_image_key: str = "",
    ) -> DeliveryResult:
        """把视频作为**可在飞书内直接播放**的消息发出。

        ``msg_type=media`` 与 ``msg_type=file`` 的区别：
        media 在客户端里能直接播放，file 只能下载。
        审核人要判断画面，所以用 media。
        """
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        file_key = self.upload_video(path, duration_ms)

        content: dict = {"file_key": file_key}
        if cover_image_key:
            content["image_key"] = cover_image_key

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(self.chat_id)
                .msg_type("media")
                .content(json.dumps(content, ensure_ascii=False))
                .build()
            )
            .build()
        )

        try:
            response = self._client().im.v1.message.create(request)
        except Exception as exc:  # noqa: BLE001
            raise ReviewChannelError(f"发送视频消息失败：{type(exc).__name__}") from exc

        if not response.success():
            code = getattr(response, "code", None)
            msg = getattr(response, "msg", "")
            raise ReviewChannelError(f"发送视频消息失败：平台返回 code={code} msg={msg}")

        message_id = getattr(getattr(response, "data", None), "message_id", None)
        if not message_id:
            return DeliveryResult(
                delivery_status=DELIVERY_UNKNOWN,
                provider_message_id=None,
                detail="平台受理但未取得视频消息 ID，需人工核对。",
            )
        return DeliveryResult(
            delivery_status=DELIVERY_SENT,
            provider_message_id=message_id,
            detail=f"file_key={file_key}",
        )

    def send(self, view: ReviewDraftView) -> DeliveryResult:
        """把审核卡片发到配置的审核会话。

        失败时抛 ReviewChannelError，由调用方转换为契约错误；
        绝不把原始 SDK 异常抛给模型。
        """
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        card = build_review_card(view)
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(self.chat_id)
                .msg_type("interactive")
                .content(card_payload_text(card))
                .build()
            )
            .build()
        )

        try:
            response = self._client().im.v1.message.create(request)
        except Exception as exc:  # noqa: BLE001 - 内部异常统一转契约错误
            raise ReviewChannelError(f"发送审核卡片失败：{type(exc).__name__}") from exc

        if not response.success():
            # 只回稳定错误码与平台消息，不回传 SDK 原始结构。
            code = getattr(response, "code", None)
            msg = getattr(response, "msg", "")
            raise ReviewChannelError(f"发送审核卡片失败：平台返回 code={code} msg={msg}")

        message_id = None
        try:
            message_id = response.data.message_id
        except AttributeError:
            message_id = None

        if not message_id:
            # BE-NFR-04：结果未知保留 UNKNOWN，供人工核对。
            return DeliveryResult(
                delivery_status=DELIVERY_UNKNOWN,
                provider_message_id=None,
                detail="平台受理但未取得消息 ID，需人工核对。",
            )

        return DeliveryResult(
            delivery_status=DELIVERY_SENT,
            provider_message_id=message_id,
        )
