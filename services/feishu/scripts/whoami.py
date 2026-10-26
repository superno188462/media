"""一次性工具：查出审核会话 chat_id 与审核人 ID。

配置前需要两样东西，这里都能查：

1. **审核群 chat_id**（``oc_`` 开头）—— 列出机器人所在的群::

       uv run --with lark-oapi --no-project python scripts/whoami.py --list-chats

2. **审核人 open_id**（``ou_`` 开头）—— 列群成员，或用邮箱/手机号换::

       uv run --with lark-oapi --no-project python scripts/whoami.py --chat oc_xxx
       uv run --with lark-oapi --no-project python scripts/whoami.py --email you@example.com

凭证从环境变量读取：``FEISHU_APP_ID`` / ``FEISHU_APP_SECRET``。
本工具只读，不发消息、不改配置。
"""

from __future__ import annotations

import argparse
import os
import sys


def _client():
    import lark_oapi as lark

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        print("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET", file=sys.stderr)
        raise SystemExit(2)
    return (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .log_level(lark.LogLevel.WARNING)
        .build()
    )


def list_chats(client) -> int:
    """列出机器人所在的群，用来找审核会话的 chat_id。

    需要 ``im:chat:readonly`` 权限。
    """
    from lark_oapi.api.im.v1 import ListChatRequest

    request = ListChatRequest.builder().page_size(50).sort_type("ByCreateTimeAsc").build()
    response = client.im.v1.chat.list(request)
    if not response.success():
        print(f"查询失败 code={response.code} msg={response.msg}", file=sys.stderr)
        print("提示：需要 im:chat:readonly 权限，申请后记得发版本。", file=sys.stderr)
        return 1

    items = getattr(response.data, "items", None) or []
    if not items:
        print("机器人还没有加入任何群。先把机器人拉进审核群，再跑一次。", file=sys.stderr)
        return 1

    print(f"机器人所在群（{len(items)} 个）：")
    for chat in items:
        print(f"  chat_id={getattr(chat, 'chat_id', '?')}  name={getattr(chat, 'name', '')}")
    return 0


def by_chat(client, chat_id: str) -> int:
    """列出群成员。需要 im:chat 或 im:chat:readonly 权限。"""
    from lark_oapi.api.im.v1 import GetChatMembersRequest

    request = (
        GetChatMembersRequest.builder()
        .chat_id(chat_id)
        .member_id_type("open_id")
        .page_size(50)
        .build()
    )
    response = client.im.v1.chat_members.get(request)
    if not response.success():
        print(f"查询失败 code={response.code} msg={response.msg}", file=sys.stderr)
        return 1

    items = getattr(response.data, "items", None) or []
    if not items:
        print("群成员为空，或应用不在该群/无权限。", file=sys.stderr)
        return 1

    print(f"群 {chat_id} 成员（{len(items)} 人）：")
    for member in items:
        member_id = getattr(member, "member_id", "?")
        name = getattr(member, "name", "")
        print(f"  open_id={member_id}  name={name}")
    return 0


def by_email(client, email: str | None, mobile: str | None) -> int:
    """用邮箱/手机号换用户 ID。"""
    from lark_oapi.api.contact.v3 import BatchGetIdUserRequest, BatchGetIdUserRequestBody

    body = BatchGetIdUserRequestBody.builder()
    if email:
        body = body.emails([email])
    if mobile:
        body = body.mobiles([mobile])
    request = BatchGetIdUserRequest.builder().user_id_type("open_id").request_body(body.build()).build()

    response = client.contact.v3.user.batch_get_id(request)
    if not response.success():
        print(f"查询失败 code={response.code} msg={response.msg}", file=sys.stderr)
        print("提示：需要 contact:user.id:readonly（或 contact:user.base:readonly）权限。", file=sys.stderr)
        return 1

    users = getattr(response.data, "user_list", None) or []
    if not users:
        print("未找到对应用户。", file=sys.stderr)
        return 1

    for user in users:
        print(f"  open_id={getattr(user, 'user_id', '?')}  name={getattr(user, 'name', '')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list-chats", action="store_true", help="列出机器人所在的群，找审核会话 chat_id")
    group.add_argument("--chat", help="审核群 chat_id（oc_ 开头），列出群成员")
    group.add_argument("--email", help="审核人邮箱")
    group.add_argument("--mobile", help="审核人手机号")
    args = parser.parse_args()

    if not (args.list_chats or args.chat or args.email or args.mobile):
        parser.error("至少给一个：--list-chats / --chat / --email / --mobile")

    client = _client()
    if args.list_chats:
        return list_chats(client)
    if args.chat:
        return by_chat(client, args.chat)
    return by_email(client, args.email, args.mobile)


if __name__ == "__main__":
    raise SystemExit(main())
