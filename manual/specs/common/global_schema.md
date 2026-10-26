# 共享 Schema 与跨资源语义

| 项目 | 内容 |
| --- | --- |
| 文档版本 / 候选契约 | `0.1.0-draft.1` / `0.1.0` |
| 状态 / 日期 | 待评审，未锁定 / 2026-10-26 |
| 字段权威来源 | [contracts/cyber-sloth.schema.json](../../contracts/cyber-sloth.schema.json) 的 `$defs` |
| 行为权威来源 | [后端 SDD](../backend/approval-publishing.spec.md) |

## SC-01 单一字段来源

JSON Schema 是公开数据字段、类型、必填、可空、枚举、长度与范围的唯一权威定义。本文补足 JSON Schema 不能独立表达的权限、关系、状态和字节语义。SDD 通过引用定义使用它们，不能再创造同名字段的另一套定义。

当前 Schema 是文档阶段的声明式附件，不是已经批准的可执行骨架。后续生成 TypeScript 类型、MCP input/output Schema 和契约 Fixture 均引用它；格式校验器必须显式启用 `uuid`、`date-time`、`uri` 验证，不只读取注解。

## SC-02 模型索引与数据流

| 定义 | 生产方 → 消费方 | 用途 |
| --- | --- | --- |
| `Asset` / `RegisterAssetRequest` | 资产服务 → DSH/预览/投稿 | 受控不可变图片 |
| `PublicationManifest` | 创作入口 → 草稿/审核/投稿 | 被审核的完整内容 |
| `Draft` / `DraftDetail` 与 Create/Revise/Identity/Page | 草稿服务 → DSH 工作台 | 版本、列表和当前版本的审核/任务关联 |
| `ReviewRequest` / `RequestReviewRequest` | 审核服务 → 飞书/工作台 | 版本绑定的审核请求 |
| `ReviewDecision` / `DecisionResult` | 飞书适配器 → 内部应用服务 | 可信审核动作；不向模型开放 |
| `PublishJob` / `JobIdentity` | 后台执行器 → 查询/回执 | 投稿生命周期 |
| `ReadinessRequest` / `ReadinessReport` | 投稿适配器 → 工作台 | 只读身份和能力检查 |
| `PublishObservation` / `Evidence` | 投稿适配器 → 后台应用服务 | 可核对平台结果 |
| `AuditEvent` / `ContractError` | 应用服务 → 诊断/界面 | 状态索引与安全错误 |

## SC-03 通用序列化

- 所有对象拒绝未知字段，不自动把字符串转换为数字或布尔值。
- 时间以 UTC `Z` 保存与传递；界面按 Asia/Shanghai 显示，业务比较使用服务端时钟。
- 必填字段缺失是校验错误。仅明确定义为 nullable 的字段允许 `null`。
- 无来源使用 `source_refs: []`；无退回意见用 `feedback: null`；未知平台 ID/链接用 `null`，不得填空串或伪造链接。
- 标题、正文不允许纯空白；保存时不自动裁切、换行重写、加标签或 Unicode 规范化。长度按 Unicode 码点计数。
- 所有产品限制都是候选值，不能宣称是平台上限。平台更严格时返回明确错误并要求改稿再审核。
- `default` 是契约声明，应用入口仍须落实缺省值；不假设 JSON Schema 校验器会自动填默认值。

## SC-04 内容快照与摘要

`PublicationManifest` 校验通过后序列化并保存为一份无 BOM 的 UTF-8 JSON 字节快照。`content_digest` 是这份已保存字节的 SHA-256。该版本的原始快照字节不可重写；读取时同时验证字节摘要，不通过对象重新序列化计算“等价摘要”。

初次生成快照允许实现选择 JSON 排版，落盘后这份字节就是唯一审核依据。任何可发布字段、图片顺序、来源、人设版本或公开范围变化都产生新 revision 和新快照，即使只改一处空格。历史对象相同但字节不同不得静默覆盖。

资产 `sha256` 对应实际图片字节；导入后复制为受控不可变资产。送审和最终提交前都核验资产摘要。`asset_id` 不得重复；不得发布原始路径后来被替换的图片。超过尺寸、非法图片或图片总量超限拒绝导入/创建，不静默压缩或降质；未来图片转换须先生成新资产再送审。

`source_refs` 用于审核溯源，不默认拼入正文；平台必须获得的文案都应已在 title/body 中。AI 平台标签由适配器按批准的 `ai_generated` 设置并核对，不伪造供应商字段。

`DraftDetail.current_review` 和 `publish_job` 若非 null，必须与 `draft` 的工作区、draft_id、revision 和摘要一致。当前版本从未送审或尚未批准时相应字段为 null；界面不能用上一个版本的审核状态填补它们。

## SC-05 可信身份上下文

公开请求中的 `workspace_id` 只是选择资源，不是权限。下列上下文由宿主或适配器创建，不是模型/浏览器客户端可提交的 JSON Schema：

| 上下文 | 来源 | 必须校验的内容 |
| --- | --- | --- |
| `OperatorContext` | 本机受信 DSH 宿主 / 已鉴权运营入口 | 工作区成员、操作权限、trace ID |
| `VerifiedReviewerContext` | 完成来源验证的飞书适配器 | 工作区绑定、飞书组织、审核人、消息与动作归属 |
| `ExecutionContext` | 受信后台执行器 | 工作区、job ID、审核授权、目标账号、执行排他性 |

上述类型是非导出构造能力：外部输入一个 `verified: true`、`reviewer_id` 或“我是老板”的文本不能取得身份。字段来源与适配器构造方式在骨架阶段明确，业务权限在本稿已定义。

MCP/DSH 工具面向创作 Agent 时只暴露创建、修订、送审、查询和运营者许可的取消动作；`applyDecision`、`executePublish`、底层 `submit` 不暴露为创作工具。通用 shell/浏览器能力与审批数据写权限必须同时收敛，详见 ARC-02。

## SC-06 幂等与并发

幂等键作用域为 `(workspace_id, 方法名, idempotency_key)`。同键同一校验后请求返回原有资源；同键不同请求返回 `IDEMPOTENCY_CONFLICT`。JSON 对象键顺序不影响“同一请求”，文字内容、显式值和数组顺序参与比较，不做 Unicode 规范化或文字裁切。即使相同请求使用新键，创建草稿也可以是新资源；不能按标题或文字相同就判重。

修订以 `expected_revision` 并发控制；已接受请求重放时返回其原始结果版本，不能再递增一次。送审对 `(workspace_id, draft_id, revision, content_digest)` 只允许一个有效审核请求；同版本重复送审复用该请求。

审核事件按已验证的提供方/组织/事件标识去重。完全相同事件重复返回现有结果，`applied=false`；相同事件标识内容变化为冲突。终态收到同一授权人相同决定返回已有结果；不同决定返回 `DECISION_ALREADY_TAKEN`，不得覆盖。

## SC-07 发布证据约束

- `ReadinessReport.READY` 必须核对实际账号，并具有 Schema 中七项能力；仅工具名存在不算 READY。
- `SUBMITTED`、`PUBLISHED`、`REJECTED` 观察至少有一条有效证据，且已核对账号；已发布还必须有作品 ID 和链接。
- `PUBLISHED` 表示作品按批准的 visibility 已确认生效；`private` 内容也需确认仅自己可见，不误写成“公开上线”。
- `SUBMITTED` 表示平台受理且可追踪，不等于审核通过；平台拒绝后记录失败。
- 作品列表暂时没有结果不能独立证明“没有提交成功”。不能据此重新提交。
- 用户手工核对结果需通过可信运营入口，给出具体账号/作品证据；聊天里一句“好像没发”不构成重发许可。

## SC-08 事件

事件是持久化可诊断事实，不要求 SSE、WebSocket 或独立消息队列。状态持久化后才向消费者呈现相应事件；以 `sequence` 解释同一工作区顺序，以 `event_id` 去重，不能用消息到达先后覆盖新状态。

| resource_type | 允许的 event_type |
| --- | --- |
| draft | draft.created / draft.revised |
| review | review.requested / review.decided / review.expired / notification.state_changed |
| publish_job | publish.queued / publish.state_changed / notification.state_changed |

UI 首期通过服务读取资源，不直接消费未定义的原始平台事件。平台回调协议属于飞书适配器契约，不能向领域层泄漏 SDK 对象。

## SC-09 错误与边界协议

应用服务成功返回对应资源，失败抛出携带 `ContractError` 的领域异常。DSH 工具边界返回结构化 `{ok:true,data:T}` 或 `{ok:false,error:ContractError}`，并依 DSH 实际工具协议正确设置错误标记；前端通过共享 Client/Bridge 解包，不解析自由文本判断错误。

首期不定义公共 HTTP REST API，因此没有虚构的 `/api/v1/...` 路径或 HTTP 状态映射。飞书 HTTP 回调若被选中，其来源验证、协议响应和平台回执必须另形成已评审适配契约。

## SC-10 示例

[示例文件](../../contracts/examples/)用于阅读和 Schema 校验，标识与摘要为虚构值，不是有效审批、真实素材或发布证据。示例的字节摘要关系、资产存在性和跨资源关系在未来业务测试中另外验证；单纯通过 JSON Schema 不证明这些约束满足。
