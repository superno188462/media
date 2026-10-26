"""监听的幂等与派发测试。"""

from __future__ import annotations

from feishu.listener import FeishuCardListener

TENANT = "tenant_ok"
CHAT = "oc_review_chat"
REVIEWER = "ou_reviewer"


def payload(event_id: str | None = "evt-1", open_id: str = REVIEWER, action: str = "approve") -> dict:
    raw = {
        "event": {
            "action": {
                "value": {
                    "action": action,
                    "review_id": "rev-1",
                    "revision": "2",
                    "content_digest": "abc123",
                }
            },
            "operator": {"tenant_key": TENANT, "user_id": "u-1", "open_id": open_id},
            "context": {"open_message_id": "om_msg", "open_chat_id": CHAT, "preview_token": "pv"},
        }
    }
    if event_id:
        raw["header"] = {"event_id": event_id}
    return raw


def make_listener(seen: list, rejected: list) -> FeishuCardListener:
    return FeishuCardListener(
        app_id="app",
        app_secret="secret",
        workspace_id="ws-1",
        tenant_key=TENANT,
        allowed_chat_ids={CHAT},
        reviewer_allowlist={REVIEWER},
        on_decision=lambda ctx, dec: seen.append((ctx, dec)),
        on_rejection=lambda rej: rejected.append(rej),
    )


def test_valid_event_is_dispatched():
    seen, rejected = [], []
    listener = make_listener(seen, rejected)
    listener._dispatch(payload())
    assert len(seen) == 1
    assert rejected == []
    ctx, decision = seen[0]
    assert decision.action == "approve"


def test_duplicate_event_id_is_ignored():
    seen, rejected = [], []
    listener = make_listener(seen, rejected)
    listener._dispatch(payload("evt-1"))
    listener._dispatch(payload("evt-1"))
    assert len(seen) == 1


def test_event_without_id_is_deduplicated_by_derived_key():
    seen, rejected = [], []
    listener = make_listener(seen, rejected)
    listener._dispatch(payload(None))
    listener._dispatch(payload(None))
    assert len(seen) == 1


def test_non_reviewer_event_is_rejected_not_dispatched():
    seen, rejected = [], []
    listener = make_listener(seen, rejected)
    listener._dispatch(payload("evt-2", open_id="ou_stranger"))
    assert seen == []
    assert len(rejected) == 1
    assert rejected[0].code == "FORBIDDEN"


def test_derived_event_id_is_stable():
    a = FeishuCardListener._derive_event_id(payload(None)["event"])
    b = FeishuCardListener._derive_event_id(payload(None)["event"])
    assert a == b
    assert a.startswith("derived-")


def test_derived_event_id_differs_for_different_action():
    a = FeishuCardListener._derive_event_id(payload(None, action="approve")["event"])
    b = FeishuCardListener._derive_event_id(payload(None, action="reject")["event"])
    assert a != b


def test_extra_event_types_are_recorded_for_fallback_registration():
    """控制台可能强制先订阅一个事件。

    这些事件我们不消费，但必须注册兜底处理器：SDK 对未注册的事件类型会抛
    EventException 并打错误日志。这里只验证参数被正确保存。
    """
    listener = FeishuCardListener(
        app_id="app",
        app_secret="secret",
        workspace_id="ws-1",
        tenant_key=TENANT,
        allowed_chat_ids={CHAT},
        reviewer_allowlist={REVIEWER},
        on_decision=lambda ctx, dec: None,
        extra_event_types={"im.message.receive_v1"},
    )
    assert listener.extra_event_types == {"im.message.receive_v1"}


def test_ignore_event_is_a_noop():
    """兜底处理器不产生副作用。"""
    assert FeishuCardListener._ignore_event({"any": "payload"}) is None


def test_no_extra_events_by_default():
    seen: list = []
    listener = FeishuCardListener(
        app_id="app",
        app_secret="secret",
        workspace_id="ws-1",
        tenant_key=TENANT,
        allowed_chat_ids={CHAT},
        reviewer_allowlist={REVIEWER},
        on_decision=lambda ctx, dec: seen.append(dec),
    )
    assert listener.extra_event_types == set()


class _Obj:
    """模拟 lark-oapi 的事件对象（有属性、没有 .get）。"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_dispatch_accepts_sdk_object_not_just_dict():
    """SDK 传的是 P2CardActionTrigger 实例，不是 dict。

    直接对它调 .get() 会抛 AttributeError，导致飞书弹 200671。
    """
    seen: list = []
    rejected: list = []
    listener = make_listener(seen, rejected)
    obj = _Obj(
        header=_Obj(event_id="evt-obj-1"),
        event=_Obj(
            operator=_Obj(tenant_key=TENANT, user_id="u-1", open_id=REVIEWER),
            action=_Obj(
                value={
                    "action": "approve",
                    "review_id": "rev-1",
                    "revision": "2",
                    "content_digest": "abc123",
                }
            ),
            context=_Obj(open_message_id="om_msg", open_chat_id=CHAT, preview_token="pv"),
        ),
    )
    listener._dispatch(obj)
    assert len(seen) == 1
    assert rejected == []
    assert seen[0][1].action == "approve"


def test_duplicate_object_event_is_ignored():
    seen: list = []
    listener = make_listener(seen, [])
    obj = _Obj(
        header=_Obj(event_id="evt-obj-2"),
        event=_Obj(
            operator=_Obj(tenant_key=TENANT, user_id="u", open_id=REVIEWER),
            action=_Obj(
                value={
                    "action": "cancel",
                    "review_id": "rev-1",
                    "revision": "1",
                    "content_digest": "d1",
                }
            ),
            context=_Obj(open_message_id="om", open_chat_id=CHAT),
        ),
    )
    listener._dispatch(obj)
    listener._dispatch(obj)
    assert len(seen) == 1
