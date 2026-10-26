# feishu · 飞书适配器

审核闭环的飞书侧实现：**发卡片 → 收动作 → 验来源 → 交受信入口**。

本模块**不做决定，也不做外发**。那两件事属于受信入口
（`applyDecision` / `executePublish`），见
[后端 SDD](../../manual/specs/backend/approval-publishing.spec.md)。

> 飞书应用侧的完整配置（权限、回调、发版本、取 `chat_id`/`open_id`、
> 新开机器人清单）见 [飞书配置指南](../../manual/docs/feishu-setup.md)。
> 本 README 只讲代码怎么用。

## 职责边界

| 模块 | 做什么 | 不做什么 |
|---|---|---|
| `cards.py` | 构造审核卡片载荷 | 不发送、不解析回调 |
| `sender.py` | 把卡片发到审核会话 | 不判断业务状态 |
| `events.py` | 验证来源、归一化可信上下文 | 不落库、不派发任务 |
| `listener.py` | 长连接收事件、去重、派发 | 不调用外发 |

## 为什么长连接（DEC-07）

`manual/specs/governance.md` 的 GOV-03 记录了选型依据。本机
`lark-oapi` SDK 实测支持：

- `lark.ws.Client(app_id, app_secret, event_handler)` —— 长连接，自动重连，**无需公网回调地址**
- `EventDispatcherHandler.builder("", "").register_p2_card_action_trigger(...)` —— 卡片动作回调
- `P2CardActionTriggerData` 含 `operator` / `context` / `action`，其中
  `CallBackOperator` 提供 `tenant_key` / `user_id` / `open_id`，
  `CallBackContext` 提供 `open_message_id` / `open_chat_id` / `preview_token`

关键点：**回调自带真实操作者身份**，所以 BE-IF-02 要求的可信上下文
不需要靠猜 HTTP 字段实现（BE-IF-05 明确禁止生成猜测的路由和字段）。

## 来源验证（BE-IF-02 / CT-06）

`events.normalize()` 按 BE-ERR-01 的错误优先级校验：

| 检查 | 失败错误码 |
|---|---|
| 回调含可验证的操作者与会话 | `UNAUTHORIZED` |
| 组织与配置一致 | `UNAUTHORIZED` |
| 会话在审核会话白名单内 | `FORBIDDEN` |
| 操作者在审核人 allowlist 内 | `FORBIDDEN` |
| 动作是受支持的三个按钮之一 | `UNAUTHORIZED` |
| 卡片绑定了 review_id / revision / digest | `STALE_REVIEW` |

**任何一项不通过都不返回可信上下文**，只有 `ReviewDecision`。
模型填的 JSON 不能创建可信审核身份（BE-RULE-03、BE-DEP-03）。

## 退回意见（feedback）

契约见共享 Schema 的 `ReviewDecision.feedback`：可选，1–500 字，**只有 reject 允许非 null**。

接收端已实现，读两个来源（按优先级）：

1. `action.form_value["feedback"]` —— 卡片里的表单 ✅ **已实测确认走这里**
2. `action.input_value` —— 卡片里的单个输入框（兜底，实测为 `null`）

规则：

| 动作 | 输入框里有字 | 结果 |
|---|---|---|
| approve / cancel | 有 | `feedback = null`（契约要求，忽略） |
| reject | 无 / 纯空白 | `feedback = null` |
| reject | 1–500 字 | 采纳，前后空白去掉 |
| reject | >500 字 | `VALIDATION_ERROR`，**不静默截断** |

**实测记录（2026-10-26）**：卡片用 `form` + `input(name=feedback)` + `button(action_type=form_submit)` 三者组合可行；点击后退回原文落在 `action.form_value.feedback`，`action.input_value` 为 `null`。

## 幂等

同一 `event_id` 只处理一次。没有稳定事件 ID 时，
用「动作绑定 + 消息 ID + 操作者 + 动作名」派生可重复去重标识
（Schema 的 `provider_event_id` 明确允许）。

## 额外事件订阅（控制台限制）

部分飞书应用要求**先在「事件订阅」勾选至少一个事件**，回调配置才可用。
这些事件并不属于审核闭环，但必须处理，因为 SDK 对**未注册处理器的事件类型会
抛 `EventException`**，每次触发都打一条错误日志（长连接不会断，但日志会脏）。

`FeishuCardListener(extra_event_types={...})` 会为这些事件注册空处理器：

```python
FeishuCardListener(
    ...,
    extra_event_types={"im.chat.member.bot.added_v1"},
)
```

**选择原则：挑触发频率最低、携带数据最少的事件。**
`im.message.receive_v1` 会带来每条消息的全文与发送者信息，不建议用它凑数。

## 配置

| 环境变量 | 说明 | 必需 |
|---|---|---|
| `FEISHU_APP_ID` | 自建应用 App ID | 是 |
| `FEISHU_APP_SECRET` | 自建应用 App Secret | 是 |
| `FEISHU_REVIEW_CHAT_ID` | 审核会话（群 chat_id） | 是 |

凭据放 `.local/dsh/.credentials.yaml` 或环境变量，
**不进模型上下文、卡片和日志**（BE-NFR-07）。

## 必需的应用权限

实测缺权限时飞书返回 `99991672 Access denied`，并在错误信息里给出可申请范围。

| 权限 | 用途 | 必需 |
|---|---|---|
| `im:chat:readonly`（或 `im:chat`） | 列出机器人所在群、读群成员 → 拿 `chat_id` / `open_id` | 是 |
| `im:message:send_as_bot` | 以应用身份发送审核卡片 | 是 |
| `im:resource:upload`（或 `im:resource`） | 上传配图，卡片才能显示图片 | 是（有配图时） |
| `contact:user.id:readonly` | 用邮箱/手机号换 `open_id`（可选路径） | 否 |

**申请后必须「版本管理与发布」创建版本并发布**，否则权限不生效。

应用还需开启「**机器人**」能力，否则无法发消息、也进不了群。

## 快速上手

```bash
cd services/feishu
uv run --with pytest --no-project python -m pytest tests/ -q
```

## 目录

```
services/feishu/
├── pyproject.toml
├── uv.lock
├── README.md
├── src/feishu/
│   ├── cards.py       # 卡片构建
│   ├── sender.py      # 发送
│   ├── events.py      # 来源验证与归一化
│   └── listener.py    # 长连接监听
└── tests/
    ├── test_cards.py
    ├── test_events.py
    └── test_listener.py
```

## 未完成 / 未验证

- **未获真实飞书账号验证**。当前只做到：SDK 能力实测 + 26 个契约测试。
  建应用、选会话、拿审核人 open_id 都还需要真实环境。
- `applyDecision` 受信入口 —— **未实现**（属应用服务层，不在本适配器内）
- 完整预览 —— 卡片只带第一张图和摘要。多图完整预览方案待定
  （UI-CS 要求卡片放不下时必须附经身份校验的只读预览入口）
- 审核有效期与批准后提交期限的落盘与过期扫描 —— 属应用服务层
