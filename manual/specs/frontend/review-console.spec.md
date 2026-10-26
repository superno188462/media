# DSH 工作台与飞书审核前端 SDD

## 1. 文档头

| 项目 | 内容 |
| --- | --- |
| 标识 / 文档版本 | SDD-FE-CS / `0.1.0-draft.1` |
| 行为基线 / 状态 | 候选 `0.1.0`，未锁定 / 待评审 |
| PRD / UI | [PRD-CS](../common/prd.md)、[UI-CS](../common/ui_notes.md)，用户已确认当前方向 |
| 共享 Schema / 后端 | [共享定义](../../contracts/cyber-sloth.schema.json) `0.1.0` / SDD-BE-CS `0.1.0-draft.1` |
| 责任人 / 评审人 | 项目开发者 |
| 更新 / 确认依据 | 2026-10-26 / 用户回复“继续”确认交互方向；本 SDD 尚未批准 |

### 变更与评审日志

| 版本 | 日期 | 范围 | 结论 |
| --- | --- | --- | --- |
| 0.1.0-draft.1 | 2026-10-26 | DSH 原生工作台和飞书卡片交互 | 待开发者评审 |

## 2. 目标与范围

### FE-SCOPE-01

为运营者提供草稿列表、完整详情、审核与投稿状态，为审核人在飞书提供版本明确的一次发布授权入口。覆盖 REQ-04—REQ-10。沿用 UI-CS 方向，不新增聊天前端、独立登录系统、WYSIWYG 编辑器或多租户后台。

DSH 具体侧栏/设置页挂载 API 尚未核实；界面是候选交互，不能因文档出现组件名就推定 SDK 已有相同符号。

## 3. 外部依赖

| 条款 | 依赖 | 不可用行为 | 验证 |
| --- | --- | --- | --- |
| FE-DEP-01 | DSH 原生 UI 和可信应用桥接 | 清楚显示兼容错误，不显示可用发布按钮 | UI-CT-01、IT-01 |
| FE-DEP-02 | BE-IF-01 的查询和运营操作 | 按 ContractError 展示，不解析自由文本 | UI-CT-02—05 |
| FE-DEP-03 | 飞书卡片和来源验证适配器 | 卡片更新失败时不谎报后台操作失败；服务端状态为准 | UI-CT-06、IT-03 |
| FE-DEP-04 | 完整图片预览 | 无法查看时显示失败，不能隐藏缺图后宣称内容完整 | UI-CT-07、SP-03 |

## 4. 数据模型与 Schema

### FE-DATA-01 共享模型

Draft、DraftDetail、ReviewRequest、PublishJob、ContractError 和分页请求全部引用 JSON Schema，不另写冲突类型。服务端资源是业务状态的唯一可信来源；界面不能只靠本地 `approved=true` 启用投稿。

本地展示状态为 `initial / loading / ready / empty / recoverable_error / fatal_error`，请求期间操作按钮为 disabled；这些是 UI 状态，不写入领域资源。首期不持久化 UI 缓存，只在当前界面内保留筛选和选中项；刷新后重新取服务端状态。

### FE-DATA-02 显示语义

- 缺失必要字段视为非法服务响应，不能显示成功。
- null 平台链接显示“尚无可核对链接”，不生成猜测链接；空列表展示空态。
- 无修改意见显示“未填写修改意见”；不将 null 转成用户似乎填写过的空文本。
- 日期按 Asia/Shanghai，卡片注明北京时间；图片按 manifest 顺序，显示“第 N 张”。
- 卡片只显示人可读摘要短码；授权校验使用完整摘要。
- 渲染正文为纯文本或安全转义的 Markdown，不执行模型输出的 HTML/脚本。

## 5. 页面、组件与请求契约

### FE-IF-01 组件候选签名

组件名是后续骨架的计划定位，不是已存在源码。TypeScript 文档签名如下：

| 组件/桥接签名 | 行为与服务映射 |
| --- | --- |
| `DraftList(props: { workspace_id: string }): ReactNode` | listDrafts；筛选变化回第一页 |
| `DraftDetailView(props: { workspace_id: string; draft_id: string }): ReactNode` | getDraft 返回 DraftDetail；通过 current_review/publish_job 取得当前关联记录，必要时 getPublishJob；展示当前版本与审核记录 |
| `ReviewStatusPanel(props: { review: ReviewRequest }): ReactNode` | 显示审核与投递状态，不拥有决定权限 |
| `PublishStatusPanel(props: { job: PublishJob }): ReactNode` | 显示投稿状态和按条件可用的恢复/核对操作 |
| `IntegrationStatus(props: { workspace_id: string; target_account_id: string }): ReactNode` | checkReadiness；只读能力检查 |
| `ReviewCardRenderer.render(review: ReviewRequest, draft: Draft): CardPayload` | 输出飞书卡片适配对象；CardPayload 为提供方私有类型，不跨应用服务边界 |

所用宿主若不采用 React，保留相同行为，骨架评审时将组件签名映射为实际宿主声明；变更公共协议时仍走契约评审。

### FE-STATE-01 页面与请求生命周期

| 当前状态 / 事件 | 下一状态 | 可观察行为 |
| --- | --- | --- |
| initial / 首次进入 | loading | 显示加载文字，禁用送审等操作 |
| loading / 有数据 | ready | 显示当前服务端版本与状态 |
| loading / 列表为空 | empty | 引导在 DSH 对话中创建图文 |
| ready / 点击送审 | loading | 单次调用 requestReview，保持当前完整内容可见 |
| loading / 审核资源成功 | ready | 显示等待审核与 delivery_status；SENT 不显示为已批准 |
| loading / 可恢复查询失败 | recoverable_error | 保留选择，提供重新读取按钮，不自动重放写请求 |
| 任意 / 无权限或资源不存在 | fatal_error | 明确提示并提供返回列表 |
| 任意 / 切换草稿或筛选 | loading | 旧请求结果不能覆盖新资源 |
| 任意 / 刷新或重新打开 | loading | 从服务端恢复，不恢复旧批准按钮状态 |

异步请求按资源 ID 和当前选择关联；同一资源较旧 updated_at 的响应不覆盖已展示的新状态。时间相同且存在并发歧义时再次读取，不由前端决定胜负。

### FE-ACTION-01 操作按钮

| 控件 | 启用条件 | 行为 / 反馈 |
| --- | --- | --- |
| 送审 | DRAFT、数据已加载、无同类进行中请求 | 传明确版本和摘要；成功显示审核请求，失败保留内容 |
| 取消审核 | IN_REVIEW | cancelReview；冲突后刷新并显示真实结果 |
| 通过并发布（飞书） | 卡片标记待审，但服务端仍作最终校验 | 已持久化后显示“已批准，等待投稿”；不用第二次批准 |
| 退回修改（飞书） | 待审 | feedback 可选，最多 500 字符；与 Schema 一致 |
| 取消审核（飞书） | 待审 | action=cancel，feedback=null |
| 处理登录后恢复 | BLOCKED 且后台报告可恢复 | resumePublish；不用于 RESULT_UNKNOWN |
| 核对结果 | SUBMITTED / RESULT_UNKNOWN | reconcilePublish，只读，不触发再提交 |
| 打开作品 | 存在已核对 HTTPS 链接 | 只打开链接，不额外变更资源 |

模型会话修改内容后，工作台重新读取新版本。批准按钮的禁用/更新只是交互反馈，服务端必须拒绝过期卡片，即使飞书消息没更新成功。

### FE-ACTION-02 重复、取消和完整预览

写请求生成一次 idempotency_key 并在该次未知结果核对期间保留；网络超时先读取资源状态，不能更换键自动创建第二次审核。新内容与新的有意请求才产生新键。

首期不提供“取消正在最终提交”的按钮，也不把页面离开视为撤销已批准任务。只有待审取消是明确业务操作。完整预览 GET 无副作用；必须通过服务端访问控制，URL 本身不授予发布权限。

## 6. 异常与错误契约

### FE-ERR-01 错误映射

| 来源 | 状态与用户提示 | 恢复 |
| --- | --- | --- |
| VALIDATION_ERROR / ASSET_INVALID | 保留内容，指出公开字段错误 | 改稿或重新导入 |
| REVISION_CONFLICT / STALE_REVIEW | “内容版本已变化，请查看最新版本” | 重新读取，不自动批准新版 |
| REVIEW_EXPIRED / APPROVAL_EXPIRED | 明确过期，禁用旧动作 | 新版本重新送审 |
| UNAUTHORIZED / FORBIDDEN | “无法验证身份”或“没有审核权限” | 由运营者处理身份/权限 |
| DECISION_ALREADY_TAKEN / DRAFT_LOCKED | 显示既有状态；已批准内容只读 | 刷新，必要时另建草稿 |
| LOGIN_REQUIRED / CAPTCHA_REQUIRED | BLOCKED，显示手动处理入口说明 | 处理后恢复同一任务 |
| RESULT_UNKNOWN | 结果待确认；隐藏/禁用重新提交 | 只读核对 |
| DEPENDENCY_* / STORAGE_UNAVAILABLE | 显示安全消息及 trace ID | 查询可重新读取；写操作先核对结果 |
| CAPABILITY_UNSUPPORTED / AI_LABEL_UNVERIFIED / LAYOUT_CHANGED / ACCOUNT_MISMATCH | 明确需要修复接入能力 | 不显示“已成功投稿” |
| 其他错误 | 显示服务端安全 message；不暴露 raw details | 显示诊断 ID，返回或重新读取 |

## 7. 非功能规格

| 条款 | 要求 | 验证 |
| --- | --- | --- |
| FE-NFR-01 | 用户点击后 200ms 内出现加载/禁用反馈；本机数据请求 10 秒无结果显示超时并允许只读核对 | UI-CT-02，假时钟；真实设备 SP-01 |
| FE-NFR-02 | 界面显示不超过每 5 秒一次的当前详情只读刷新；离开详情停止；后台状态可用时 10 秒内反映。飞书消息更新为尽力而为，旧卡片依靠服务端拒绝保持安全 | UI-CT-03/06、IT-03 |
| FE-NFR-03 | 桌面 1280×720 和手机 375 像素宽可阅读；自建按钮可键盘聚焦，错误文本可见 | SP-05 |
| FE-NFR-04 | 不将密钥/令牌/平台原始响应放进前端持久缓存；HTML 转义；预览请求带受验证身份 | UI-CT-07、SP-03 |

## 8. 业务硬规则

| 条款 | 交互不变量 | 服务端引用 |
| --- | --- | --- |
| FE-RULE-01 | “通过并发布”明确表达该条内容的外发授权 | BE-RULE-01/02 |
| FE-RULE-02 | 显示全量正文、全部图片、顺序、账号、AI 声明和公开范围 | BE-RULE-02/07 |
| FE-RULE-03 | 不把消息已发送、按钮已点击或素材已上传显示成已发布 | BE-RULE-06 |
| FE-RULE-04 | 结果未知时不能通过界面重新最终提交 | BE-RULE-05 |
| FE-RULE-05 | 前端禁用按钮不能代替后台授权；无批准记录不能通过改页面状态投稿 | BE-RULE-01、SC-05 |

## 9. 验收与追踪

| 验收 | 条款与基线 | 骨架计划 / 测试 |
| --- | --- | --- |
| FE-AC-01 | UI-01/02/05、FE-STATE-01 | DraftList / DraftDetailView；UI-CT-01—03 |
| FE-AC-02 | UI-03/04、FE-ACTION-01、FE-RULE-01—03 | ReviewCardRenderer；UI-CT-04/06/07、IT-03 |
| FE-AC-03 | FE-ERR-01、FE-ACTION-02、FE-RULE-04/05 | PublishStatusPanel；UI-CT-05、SP-03 |
| FE-AC-04 | FE-NFR-01—04 | SP-01/03/05，真实环境单独验收 |

评审结论：SDD 待评审。UI-CS 方向已确认；DSH 界面挂载点、飞书卡片回调与完整预览方案仍需按固定宿主版本落实并实测，不生成猜测 SDK 的前端业务实现。
