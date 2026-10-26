"""卡片动作监听（长连接）。

DEC-07 已选长连接：本机无需公网回调地址，由 SDK 主动连出。

这里只负责**接收并归一化**，然后交给受信的 `applyDecision` 入口。
监听器本身不做决定，也不直接触发外发——BE-IF-03 要求发布只能由
受信执行器执行。

用法::

    listener = FeishuCardListener(
        app_id=..., app_secret=...,
        workspace_id="ws-1",
        tenant_key="...", 
        allowed_chat_ids={"oc_xxx"},
        reviewer_allowlist={"ou_xxx"},
        on_decision=apply_decision,
    )
    listener.start()   # 阻塞，直到进程退出
"""

from __future__ import annotations

import json
import os
from typing import Callable

from .events import DecisionRejection, ReviewDecision, VerifiedReviewerContext, normalize
from .sender import ReviewChannelError

#: 收到决定后的回调签名：(context, decision) -> 可选的回执文案（用作 toast）
DecisionHandler = Callable[[VerifiedReviewerContext, ReviewDecision], "str | None"]

#: 收到非法回调时的回调签名
RejectionHandler = Callable[[DecisionRejection], None]


def _to_plain(value: object) -> object:
    """把 SDK 的事件对象递归转成普通 dict / list。

    ``lark-oapi`` 传给回调的是 ``P2CardActionTrigger`` 实例，不是 dict；
    对它的属性直接 ``.get()`` 会抛 ``AttributeError``（实测踩过）。
    """
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(v) for v in value]
    if isinstance(value, (str, bytes, int, float, bool)) or value is None:
        return value
    obj_dict = getattr(value, "__dict__", None)
    if isinstance(obj_dict, dict):
        return {k: _to_plain(v) for k, v in obj_dict.items() if not k.startswith("_")}
    return value


class FeishuCardListener:
    """监听卡片动作事件。"""

    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_secret: str | None = None,
        workspace_id: str,
        tenant_key: str | None,
        allowed_chat_ids: set[str],
        reviewer_allowlist: set[str],
        on_decision: DecisionHandler,
        on_rejection: RejectionHandler | None = None,
        extra_event_types: set[str] | None = None,
        on_raw: Callable[[dict], None] | None = None,
    ) -> None:
        self.app_id = app_id or os.environ.get("FEISHU_APP_ID", "")
        self.app_secret = app_secret or os.environ.get("FEISHU_APP_SECRET", "")
        self.workspace_id = workspace_id
        self.tenant_key = tenant_key
        self.allowed_chat_ids = set(allowed_chat_ids)
        self.reviewer_allowlist = set(reviewer_allowlist)
        self.on_decision = on_decision
        self.on_rejection = on_rejection or (lambda rejection: None)
        #: 控制台可能要求先订阅一个事件才允许配置回调。这些事件我们不消费，
        #: 但必须注册兜底处理器——SDK 对未注册的事件类型会抛
        #: ``EventException``，每次触发都打一条错误日志。
        self.extra_event_types = set(extra_event_types or ())
        #: 可选：每次卡片动作都把原始载荷交给它，用于摸清平台真实字段。
        self.on_raw = on_raw
        self._event_ids: set[str] = set()

    def _dispatch(self, raw: object) -> object:
        """把 SDK 事件转成内部输入并交给受信入口。

        必须返回 ``P2CardActionTriggerResponse``。返回 None 时飞书会弹出
        「出错了，请稍后重试 code: 200671」——实测踩过。
        """
        data = _to_plain(raw)
        if not isinstance(data, dict):
            return self._toast(False, "无法解析的回调")

        if self.on_raw is not None:
            self.on_raw(data)

        payload = data.get("event") if isinstance(data.get("event"), dict) else data
        header = data.get("header") if isinstance(data.get("header"), dict) else {}
        event_id = header.get("event_id")
        provider_event_id = event_id or self._derive_event_id(payload)

        # 重复事件：同一 event_id 只处理一次（BE-IF-02 的幂等要求）。
        if provider_event_id in self._event_ids:
            return self._toast(True, "这条操作已处理过")

        context, decision, rejection = normalize(
            payload,
            workspace_id=self.workspace_id,
            expected_tenant_key=self.tenant_key,
            allowed_chat_ids=self.allowed_chat_ids,
            reviewer_allowlist=self.reviewer_allowlist,
            provider_event_id=provider_event_id,
        )
        if rejection is not None:
            self._event_ids.add(provider_event_id)
            self.on_rejection(rejection)
            return self._toast(False, f"{rejection.code}：{rejection.message}")

        self._event_ids.add(provider_event_id)
        assert context is not None and decision is not None
        message = self.on_decision(context, decision)
        label = {"approve": "已批准", "reject": "已退回", "cancel": "已取消"}.get(
            decision.action, "已收到"
        )
        return self._toast(
            True,
            message
            or f"{label}（审核 {decision.review_id} v{decision.expected_revision}）",
        )

    @staticmethod
    def _toast(ok: bool, text: str) -> object:
        """构造飞书要求的回调响应；没有 SDK 时返回 None（测试环境）。"""
        try:
            from lark_oapi.event.callback.model.p2_card_action_trigger import (
                P2CardActionTriggerResponse,
            )
        except Exception:  # noqa: BLE001 - 测试环境没装 lark-oapi
            return None
        return P2CardActionTriggerResponse(
            {"toast": {"type": "success" if ok else "error", "content": text}}
        )

    @staticmethod
    def _derive_event_id(payload: dict) -> str:
        """没有稳定事件 ID 时，生成可重复的交互去重标识。

        Schema 允许：*"无稳定标识时由适配器生成可重复的交互去重标识并验收"*。
        这里用动作绑定 + 消息 ID + 操作者 + 动作名，同一交互必然相同。
        """
        action = payload.get("action") or {}
        value = action.get("value") or {}
        operator = payload.get("operator") or {}
        context = payload.get("context") or {}
        material = "|".join(
            str(x)
            for x in (
                value.get("review_id"),
                value.get("revision"),
                value.get("content_digest"),
                operator.get("open_id"),
                context.get("open_message_id"),
                value.get("action"),
            )
        )
        import hashlib

        return "derived-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _ignore_event(payload: object) -> None:
        """额外订阅事件的兜底处理器：只确认收到，不做任何处理。

        这些事件不是审核闭环的一部分，注册它是为了让 SDK 不抛
        ``EventException``（SDK 对未注册的事件类型会抛异常并打错误日志）。
        """
        return None

    def start(self) -> None:
        """启动长连接，阻塞运行。"""
        import lark_oapi as lark

        builder = lark.EventDispatcherHandler.builder("", "").register_p2_card_action_trigger(
            self._dispatch
        )
        # 兜底：为控制台强制勾选的额外事件注册空处理器，避免刷错误日志。
        for event_type in sorted(self.extra_event_types):
            builder = builder.register_p2_customized_event(event_type, self._ignore_event)

        handler = builder.build()
        client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.WARNING,
        )
        client.start()
