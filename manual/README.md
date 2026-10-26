# 内卷树懒

基于 DeepSeek Harness（DSH）的 AI 创作者学习项目。首期让 DSH 准备抖音图文，把确定版本的内容送到飞书审核，授权审核人点击“通过并发布”后自动投稿，并核对发布结果。

本项目已准备需求、设计与声明式契约，并在项目根目录的 `dsh/` 配好官方 DSH `0.2.1-rc.3`。内卷树懒业务尚未实现。另按用户追加要求安装 bili-cli `1.1.2` 与项目 Skill，B站账号“内卷树懒”已扫码登录；真实读取与发布结果分别记录，不视为发布闭环已完成。

双击项目根目录的 [启动DSH.cmd](../启动DSH.cmd) 启动宿主。源码位置、配置迁移、旧版备份和验证结果见 [DSH 环境记录](docs/dsh-environment.md)；两个运营工具与直播截图的分析见 [工具研究](docs/creator-tools-analysis.md)。

开始体验 B站自动流程请读 [DSH 与 B站上手指南](docs/bilibili-quickstart.md)。

## 动手之前

实际要把环境跑起来，先看这两份：

1. [前期准备工作](docs/preparation.md)：环境要求、目录约定、各服务安装与验证、凭据管理、B站登录与生图配置。
2. [飞书配置指南](docs/feishu-setup.md)：自建应用与机器人、权限清单、长连接回调、获取 `chat_id`/`open_id`/`tenant_key`、错误码速查，以及**新开一个飞书机器人的完整清单**。

本目录是手册入口；项目实际目录、各服务职责与后续文件放置规则见 [目录说明](directory-layout.md)。

## 当前阶段

| 项目 | 状态 |
| --- | --- |
| 文档版本 | `0.1.0-draft.1` |
| 日期 | 2026-10-26（Asia/Shanghai） |
| PRD / UI | 用户回复“继续”，按当前版本方向进入 SDD 收敛 |
| SDD / Schema | 配套草案待评审，尚未锁定 |
| 骨架 / 契约测试 / 实现 | 已实现 `content`/`approval`/`feishu`/`engagement` 四个服务，251 个测试通过；**正式评审未做**，见[治理记录](specs/governance.md) |
| 真实依赖 | DSH `0.2.1-rc.3` 构建、Web、模型推理及 CLI 工具调用通过；B站图文**已真实发布 1 条**；飞书审核闭环实测通过；抖音尚未接入 |

## 建议阅读顺序

1. [产品需求 PRD](specs/common/prd.md)：为什么做、为谁做、这一期交付什么。
2. [交互基线](specs/common/ui_notes.md)：DSH 内的操作与飞书审核卡片。
3. [架构与决策](specs/architecture.md)：DSH、插件、MCP、浏览器各自的职责。
4. [共享数据契约说明](specs/common/global_schema.md)与[JSON Schema](contracts/cyber-sloth.schema.json)：字段、状态和消息的权威定义。
5. [服务端 SDD](specs/backend/approval-publishing.spec.md)：审核、授权、投稿与恢复契约。
6. [交互 SDD](specs/frontend/review-console.spec.md)：页面、卡片、加载和失败行为。
7. [验收矩阵](specs/acceptance.md)：如何证明契约被实现。
8. [学习与迁移路线](docs/learning-roadmap.md)：怎样从本项目学会插件与新项目开发。
9. [阶段评审与变更记录](specs/governance.md)：哪些内容需要先定稿，怎样修改契约。
10. [真实依赖验证清单](docs/integration-readiness.md)：候选插件、证据和环境准备。
11. [前期准备工作](docs/preparation.md)与[飞书配置指南](docs/feishu-setup.md)：把环境跑起来、接入飞书审核。
12. [文档自查记录](docs/document-validation.md)：本轮实际检查及尚未验证的范围。
13. [RedBeacon 基座分析](docs/redbeacon-analysis.md)：外部项目的可迁移工程方法（**只提炼工程，不含商业化**），含与本项目的差距表与三条优先改进项。

## 本期边界

- DSH 是运行主体，优先复用会话、模型、插件、MCP 和现有界面扩展能力。
- 自建插件负责业务流程、审核授权、任务状态和可观察结果。
- 第一出口是抖音图文；飞书仅承担审核和结果通知。
- 暂缓视频制作 MCP、企微接入、评论自动回复、复杂长期记忆和多租户 SaaS。
- 保留依赖替换边界，为以后商业工具复用；不提前实现商业平台。

## 工作方式

`PRD/UI 评审 → SDD 评审 → 骨架评审 → 契约测试评审 → 逐函数实现 → 真实集成验收`。

AI 可以准备和自查文档，开发者负责基线批准；“同意编写文档”不等于“批准尚未产出的契约”。当前只请求对文档评审，不要求提交账号密钥。

后续 TypeScript 插件沿用所选 DSH 的工具链；自建 Python MCP 使用 `uv`、`pyproject.toml`、`uv.lock`。第三方项目保留自身工具链，不因本项目强行迁移。
