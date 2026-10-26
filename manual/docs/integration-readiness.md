# 真实依赖与接入准备

版本：`0.1.0-draft.1`；调查日期：2026-10-26。以下是公开文档调查和待执行验证，不是本机集成成功报告。

## INT-01 证据层级

`公开说明 → 读配置/源码 → 可安装加载 → 假环境测试 → 真环境只读/草稿 → 用户批准的真实发布`。

每项记录版本或 commit、环境、步骤、证据和限制。仓库可访问、README 写了支持、安装成功和一次发布成功是不同证据。插件市场的兼容标记不能代替本项目验收。

## INT-02 DSH

核对安装路径、宿主和 SDK 版本、原生界面扩展点、preset 隔离、模型可用性及浏览器服务。固定经过验证的版本；升级前重新运行兼容测试。

官方参考：

- [插件开发](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/index.md)：TypeScript / Cordis 插件注册。
- [Agent preset](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/preset/agent-preset/README.md)：声明能力组合及生效边界。
- [MCP 客户端](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)：stdio、Streamable HTTP、工具生命周期与超时。
- [模型提供方配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/providers.md)：自定义网关入口。

以上链接指向可变分支。本机现已固定官方标签 `dsh-v0.2.1-rc.3`、commit `1f81c047fc48fa190a683e469daa699857e9afe8`，完成官方构建和 Web 启动。目录、模型配置迁移与验证边界见 [DSH 环境记录](dsh-environment.md)。后续 SDK 使用固定检出中的文档与源码；界面挂载、工具隔离和模型调用仍须单独验证。

## INT-03 飞书

> 配置步骤、权限清单、回调字段与**新开机器人清单**见 [飞书配置指南](feishu-setup.md)。
> 本机环境准备见 [前期准备工作](preparation.md)。

准备自建应用、机器人能力、审核会话和审核人 allowlist。App Secret、令牌、事件校验材料仅配置在本机服务端，不通过模型上下文传递。

必须验证：发送完整内容和图片；卡片动作确实可达；取得真实组织/操作者；来源验证；重复事件；按钮与旧版本绑定；操作结果回显；通知失败重试。

普通自定义 Webhook 不提供卡片请求回调交互，不能作为原生一键审批的完整方案。参考：[机器人概述](https://open.feishu.cn/document/client-docs/bot-v3/bot-overview)、[自定义机器人说明](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot?lang=zh-CN)、[卡片按钮](https://open.feishu.cn/document/common-capabilities/message-card/add-card-interaction/interactive-components/button?lang=zh-CN)。

HTTP 与长连接暂不锁定；核对实际 SDK 对卡片事件的支持、重连与回执要求后决定。若使用外部预览链接，另验身份验证、访问期限与图片可见性；不能把本机 localhost 链接发到手机上就视为可用。

### 本机实测记录（2026-10-26）

已选定**长连接**（DEC-07，见 [governance](../specs/governance.md) GOV-03）。以下为本机真实调用证据，环境为一个企业自建应用（`cli_` 开头，具体值不入库），审核群 `oc_…`。

| 项 | 结果 | 证据 / 限制 |
|---|---|---|
| App 凭证 | ✅ | `tenant_access_token` 返回 `code=0` |
| 列出机器人所在群 | ✅ | `im/v1/chats` 返回 1 个群，取得 `chat_id` |
| 读群成员 | ✅ | `im/v1/chats/:id/members` 取得审核人 `open_id` |
| 发送交互卡片 | ✅ | `im/v1/messages` 返回消息 ID `om_x100b62c5…b22`；卡片正文、三按钮、版本/摘要绑定均正常显示 |
| 卡片按钮回调可达 | ✅ | 长连接收到 `card.action.trigger`，`provider_event_id` 有值 |
| 取得真实组织/操作者 | ✅ | 回调带回 `tenant_key`、`operator_open_id`，与会话白名单逐一比对通过（具体值不入库） |
| 按钮与版本绑定 | ✅ | 回调中 `review_id`/`revision`/`content_digest` 与卡片下发值完全一致 |
| 重复事件 | ✅（本地去重） | 同一 `event_id` 只处理一次；未观测平台侧重投 |
| 操作结果回显 | ✅ | 返回 `P2CardActionTriggerResponse` toast，飞书显示成功 |
| 退回意见（feedback） | ✅ | 卡片 `form` + `input` + `form_submit` 可行；退回原文落在 `action.form_value.feedback`，`action.input_value` 为 `null`；`ReviewDecision.feedback` 正确提取 |
| **上传图片** | ❌ 阻塞 | `im/resource/upload` 返回 `99991672`，应用身份未开 `im:resource:upload` |
| 通知失败重试 | ⚠️ 未验证 | 未构造失败场景 |
| 完整内容预览 | ⚠️ 未达成 | 卡片已能展示全文，但图片因上传权限阻塞缺失；未做外部只读预览入口 |

**踩过的两个实现坑**（已修，测试已锁）：

1. `lark-oapi` 传给回调的是 `P2CardActionTrigger` **实例**，不是 dict；直接 `.get()` 抛 `AttributeError`。
2. 回调必须返回 `P2CardActionTriggerResponse`。返回 `None` 时飞书弹「出错了，请稍后重试 **code: 200671**」，即使业务逻辑已正确执行。

**尚未实现**：`applyDecision` 持久化与唯一发布任务创建。当前监听器只把决定写入本地 `.local/feishu-decisions.jsonl`，**不触发任何外发**；审核状态机与派发属应用服务层，见 [后端 SDD](../specs/backend/approval-publishing.spec.md) BE-IF-02 / BE-IF-03。

## INT-04 抖音图文投稿

用户手动登录自己的创作者中心，在专用浏览器 profile 中保存会话。不得从其他浏览器或无关应用提取凭据。

| 候选 | 已查到的公开能力 | 本项目未证明的内容 |
| --- | --- | --- |
| [7gzgn/dsh-douyin-publish](https://github.com/7gzgn/dsh-douyin-publish) | 浏览器操作创作者中心，视频上传、文案、可见性，默认 draft | 图文多图、AI 标识、作品查询、当前宿主兼容、审核后自动最终提交 |
| [WU079/dsh-douyin-subagent](https://github.com/WU079/dsh-douyin-subagent) | 浏览/互动工具；README 说明实际投稿走创作者网页 | 完整图文发布契约；其需要特殊签名的 MCP 路线不作为本期依赖 |
| [lussey820/aitoearn-dsh-plugin](https://github.com/lussey820/aitoearn-dsh-plugin) | 图文/视频技能与第三方服务、浏览器流程 | 服务费用、授权范围、实际图文结果、是否满足本地审批授权 |
| [himengxue/my-code](https://github.com/himengxue/my-code) | 原生 DSH 插件、六个工具、Python/Node 执行器；作者记录一次 Windows 视频发布 | 当前入口主要面向视频；评论受短信验证影响；本项目图文、飞书审批与完整 DSH 链路未实测 |

这些候选均未在此工作区安装或验收，尚无推荐的锁定版本。新增两个视频关联工具及直播实现的分析见 [工具研究](creator-tools-analysis.md)。不能在用户批准后才发现只能发视频。

进入真实外发前至少通过：

1. 图文入口、1–9 张图、顺序、正文、公开范围。
2. 识别当前登录账号与已审核的目标账号完全一致。
3. 设置并核对平台支持的 AI 声明；不假设存在 `is_ai_generated` 请求字段。
4. 能在准备完成后精确控制最终提交，且无其他脚本绕过审批。
5. 取得作品标识/链接，并区分平台审核中与公开发布。
6. 页面变化、验证码、提交后超时有明确失败/结果未知行为。

参考官方：[抖音创作者中心](https://creator.douyin.com/)、[AI 标识公告](https://trust.douyin.com/article/15868)。如未来改官方 OAuth，另验实际获批能力，不沿用网页登录权限的推论。

## INT-05 模型与素材

先使用一个可用文字模型和人工准备的图片验证闭环。DSH 可接现有 New API；网关故障、模型不可用、额度不足应阻止创作或明确失败，不影响已落盘任务的查询。

生图 MCP 后选；角色素材、字体和图片的使用权需要记录。用户提供素材不代表可以自动用于未来所有商业项目。

## INT-06 环境与商业前置

首期单机常驻，休眠或断网可能中断执行。备份和日志使用受控工作区目录；运行 profile 与开发 profile 分离。插件、上游 SDK、素材和模型服务许可证逐项记录。

后续产品化还需单独验证客户账号授权、分发方式、租户隔离、软件更新、平台政策和成本。这些是下一版 PRD 的输入，不在本期声称完成。
