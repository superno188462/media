# 图文审核与自动投稿服务端 SDD

## 1. 文档头

| 项目 | 内容 |
| --- | --- |
| 标识 / 文档版本 | SDD-BE-CS / `0.1.0-draft.1` |
| 行为基线 | 候选 `0.1.0`，未锁定 |
| 状态 | 待评审，上游方向已确认，SDD 尚未锁定 |
| PRD / UI | [PRD-CS](../common/prd.md)、[UI-CS](../common/ui_notes.md)，均为 `0.1.0-draft.1` |
| 共享 Schema | [cyber-sloth.schema.json](../../contracts/cyber-sloth.schema.json)，候选 `0.1.0` |
| 负责人 / 评审人 | 项目开发者 |
| 更新日期 | 2026-10-26 |
| 确认依据 | 用户回复“继续”进入 SDD 收敛；无本 SDD 行为基线批准记录 |

### 变更与评审日志

| 文档版本 | 日期 | 阶段 / 范围 | 摘要 | 结论与依据 |
| --- | --- | --- | --- | --- |
| 0.1.0-draft.1 | 2026-10-26 | 文档准备 / REQ-04—REQ-15 | 草稿、审核授权、投稿和恢复的配套候选契约 | 待开发者评审；自查不等于批准 |

## 2. 目标与范围

### BE-SCOPE-01 能力目标

向 DSH 草稿工具、工作台、经验证的飞书回调与可信后台执行器提供图文与视频的审核发布能力。平台范围为一个工作区中的一个平台账号（抖音与 B站同为规划范围，首期先落地 B站，见 CHANGE-001）；内容类型见 [CHANGE-002](../governance.md)（`image_text` 与 `video`）。审核后自动发送，不要求第二次人工点击发表。

覆盖 REQ-04—REQ-15；视频、自动评论、企微、自建 Agent 主循环和多租户服务不在本期。实际 SDK 类型、DOM 选择器、SQL 和提示词不属于本 SDD，候选实现见 [架构](../architecture.md)。

## 3. 外部依赖

| 条款 | 依赖与能力 | 输入/输出 | 不可用语义 | 验证 |
| --- | --- | --- | --- | --- |
| BE-DEP-01 | DSH 宿主：工具、可信运营上下文与原生 UI 桥接 | 公开请求模型与应用服务结果 | 不兼容则禁用写工具，报告 CAPABILITY_UNSUPPORTED | IT-01 |
| BE-DEP-02 | 资产存储：导入、读取不可变图片与摘要 | RegisterAssetRequest / Asset | 资源越界或变化拒绝，存储失败不外发 | CT-01、IT-02 |
| BE-DEP-03 | 飞书：发送审核消息，验证并归一化交互 | ReviewRequest/Draft → 投递状态；ReviewDecision + 可信上下文 | 不可验证不应用决定；通知失败保留待审资源 | CT-05/06、IT-03 |
| BE-DEP-04 | 投稿适配器：账号/能力检查、准备、提交、核对 | ReadinessReport / PublishObservation | 能力不足不提交；提交结果不明进入 RESULT_UNKNOWN | CT-10—15、IT-04/05 |
| BE-DEP-05 | 持久化与时钟：版本、决定、任务、事件和时间 | 共享资源；时间由服务端提供 | 写入失败不得确认批准或执行外发 | CT-07/14、SP-02 |
| BE-DEP-06 | DSH 模型/已有生图能力 | 上游生成内容形成 Manifest | 生成失败不创建伪造“成功草稿”；用户可使用已有图片 | IT-01 |

生图 Skill/MCP 只是候选内容来源，不决定审批授权。版本和实际可用性见 [接入准备](../../docs/integration-readiness.md)；当前全部未做本机真实验收。

## 4. 数据模型与 Schema

### BE-DATA-01 权威定义

所有字段引用共享 JSON Schema `$defs`，语义引用 [SC-01—SC-10](../common/global_schema.md)。本 SDD 不维护另一份字段表。

关系必须满足：Draft/ReviewRequest/PublishJob 的 workspace、draft、revision、digest 相符；PublishJob 的账号等于 manifest 账号；只有 APPROVED 审核可关联发布任务。操作者和审核人均来自可信上下文，不接受模型自报身份。

### BE-DATA-02 存储一致性

审批成功对外可见时，审核决定、批准草稿版本和唯一逻辑发布任务必须已经持久化。允许采用任意满足此可观察原子性的存储实现。事件不得先于对应资源的成功持久化呈现。

图片和 manifest 在审核前形成不可变快照。任意校验失败都不允许交给投稿提供方。修订保留历史版本；目标账号变化也算新版本。

### BE-STATE-01 草稿与审核

| 当前草稿 / 审核 | 动作 | 结果 |
| --- | --- | --- |
| 不存在 | createDraft | revision=1，DRAFT |
| DRAFT / REJECTED / CANCELED / EXPIRED | reviseDraft，版本匹配 | revision+1，DRAFT |
| IN_REVIEW / PENDING | reviseDraft，版本匹配 | 旧审核 CANCELED，新 revision+1 为 DRAFT |
| DRAFT | requestReview | IN_REVIEW，新审核 PENDING，通知 QUEUED |
| IN_REVIEW | 同版本重复送审 | 返回已有有效审核，不产生第二个逻辑审核 |
| PENDING | 合法 approve | 审核 APPROVED，草稿 APPROVED，唯一任务 QUEUED |
| PENDING | 合法 reject / cancel | 审核和草稿为 REJECTED / CANCELED，无任务 |
| PENDING，时间达到 expires_at | 决定或过期扫描 | 审核和草稿 EXPIRED，无任务；决定返回 REVIEW_EXPIRED |
| APPROVED | 改稿、重新送审、取消审核 | DRAFT_LOCKED；如需不同内容另建草稿 |
| 任意终态审核 | 相同审核人重复同一决定 | 返回既有结果，applied=false |
| 任意终态审核 | 不同决定 | DECISION_ALREADY_TAKEN；过期/失效场景使用更具体错误 |

修订与批准并发时只接受一个先决结果：修订先成功则旧回调为 STALE_REVIEW；批准先成功则修订为 DRAFT_LOCKED。不得出现“批准旧图却发新图”。

同一版本审核终态后不创建第二份审核；退回、取消或过期后通过 reviseDraft 建新版本再送审，允许新内容与旧内容文字相同但仍形成新版本。对这些终态版本使用新幂等键直接 requestReview 返回 DECISION_ALREADY_TAKEN；APPROVED 版本返回 DRAFT_LOCKED；合法原请求重放仍按幂等规则返回旧结果。

cancelReview 若发现截止时间已到，先按过期规则处理并返回 REVIEW_EXPIRED；不能因为取消动作晚到而把 EXPIRED 改成 CANCELED。

### BE-STATE-02 投稿任务

| 当前状态 | 触发 / 前提 | 下一状态及可观察效果 |
| --- | --- | --- |
| QUEUED | 获得账号排他执行权，尚未超时 | PREPARING |
| QUEUED / PREPARING | 已到 submit_deadline_at 且可证明未提交 | FAILED / APPROVAL_EXPIRED |
| PREPARING | 登录/验证码/页面异常，明确尚未最终提交 | BLOCKED，发出处理通知 |
| PREPARING | 不支持图文、AI 标识不能核对、资产变化或账号错误 | FAILED，具体错误码，无最终提交 |
| PREPARING | 内容/账号/AI 标识/公开范围核对成功 | 先持久化 SUBMITTING，才允许最终提交 |
| SUBMITTING | 平台明确接受且可追踪 | SUBMITTED；有充分发布证据则可直接 PUBLISHED |
| SUBMITTING | 明确证明未提交且可恢复 | BLOCKED；否则 FAILED |
| SUBMITTING | 超时、失联或是否接受不明确 | RESULT_UNKNOWN，禁止再次提交 |
| SUBMITTED | 核对到批准范围内的实际发布结果 | PUBLISHED |
| SUBMITTED | 平台明确拒绝 | FAILED，保留作品标识和证据 |
| SUBMITTED | 查询暂不可用 | 保持 SUBMITTED，记录查询错误，不把“查询失败”改成未提交 |
| BLOCKED | 运营者处理后 resumePublish，未超期且确认未提交 | QUEUED，同一 job，不重新批准 |
| RESULT_UNKNOWN | reconcilePublish 得到充分证据 | SUBMITTED / PUBLISHED / FAILED；不能直接转 QUEUED |
| PUBLISHED / FAILED | 重复查询 | 保持终态；不自动生成新投稿 |

SUBMITTING 在执行器重启后恢复为 RESULT_UNKNOWN。PREPARING 重启只有确认尚未进入最终提交才可回 QUEUED，否则同样为 RESULT_UNKNOWN。不能因为锁到期、没有回执或作品列表暂时为空就重发。

## 5. 接口定义

### BE-IF-01 公共应用服务

以下为拟议 TypeScript 文档签名，不是已生成骨架；所有方法异步，成功返回共享类型，失败抛出携带 ContractError 的领域异常。没有声明默认参数的方法不补隐藏默认值。

| 方法签名 | 调用方 / 成功语义 | 失败与副作用 |
| --- | --- | --- |
| `registerAsset(input: RegisterAssetRequest, ctx: OperatorContext): Promise<Asset>` | 导入允许素材目录中的图片，返回受控资产 | 越界、坏图/尺寸超限为 ASSET_INVALID；复制落盘但不对外发 |
| `createDraft(input: CreateDraftRequest, ctx: OperatorContext): Promise<Draft>` | 校验已归属工作区资产，创建 DRAFT v1 | VALIDATION_ERROR / ASSET_INVALID；不自动送审 |
| `reviseDraft(input: ReviseDraftRequest, ctx: OperatorContext): Promise<Draft>` | 原子建立下一版并使旧待审请求失效 | REVISION_CONFLICT / DRAFT_LOCKED；历史快照保留 |
| `getDraft(input: DraftIdentity, ctx: OperatorContext): Promise<DraftDetail>` | 返回当前版本、该版本审核与唯一发布任务的聚合视图；无关联为 null | NOT_FOUND；不暴露不可访问工作区记录 |
| `listDrafts(input: ListDraftsRequest, ctx: OperatorContext): Promise<DraftPage>` | 按创建时间/ID 降序，过滤与游标绑定 | 非法/跨条件游标 VALIDATION_ERROR；无数据为空数组 |
| `requestReview(input: RequestReviewRequest, ctx: OperatorContext): Promise<ReviewRequest>` | 建立 PENDING，异步投递通知 | 版本/摘要冲突拒绝；无法提供完整预览为 PREVIEW_UNAVAILABLE |
| `cancelReview(input: ReviewIdentity, ctx: OperatorContext): Promise<ReviewRequest>` | 取消待审；重复取消返回原记录 | 已决定且非取消返回 DECISION_ALREADY_TAKEN；无投稿 |
| `getPublishJob(input: JobIdentity, ctx: OperatorContext): Promise<PublishJob>` | 返回真实持久化任务状态 | NOT_FOUND；不触发重试或外发 |
| `checkReadiness(input: ReadinessRequest, ctx: OperatorContext): Promise<ReadinessReport>` | 只读核验账号与七项必需能力 | 依赖不可用返回 BLOCKED/UNSUPPORTED 报告；无批准不上传素材 |
| `resumePublish(input: JobIdentity, ctx: OperatorContext): Promise<PublishJob>` | 仅恢复安全 BLOCKED 任务为 QUEUED | JOB_NOT_RESUMABLE / APPROVAL_EXPIRED；结果未知不能恢复提交 |
| `reconcilePublish(input: JobIdentity, ctx: OperatorContext): Promise<PublishJob>` | SUBMITTED/RESULT_UNKNOWN 只读核对；终态原样返回 | 查询失败保留原状态和错误；不得触发新提交 |

创作 Agent 仅可使用 registerAsset/createDraft/reviseDraft/getDraft/listDrafts/requestReview/getPublishJob。取消、准备检查、恢复与核对由受信运营入口调用；如后续开放为工具，须更新权限契约。普通查询不默认暴露 Cookie、内部路径或平台原始响应。

### BE-IF-02 内部审核入口

`applyDecision(input: ReviewDecision, ctx: VerifiedReviewerContext): Promise<DecisionResult>`。

只接受已验证的飞书适配器调用，校验组织、消息归属、审核人 allowlist、版本、摘要、PENDING 与有效期。approve 的成功返回必须包含唯一 PublishJob；reject/cancel 为 null。feedback 仅 reject 允许非 null。

| 分支 | 行为 |
| --- | --- |
| 伪造来源 / 未登录 | UNAUTHORIZED，不改变审核/任务 |
| 来源合法但操作者非审核人 | FORBIDDEN，无发布任务 |
| 审核与当前版本不符 | STALE_REVIEW |
| 当前时间等于或晚于截止 | REVIEW_EXPIRED，落盘过期状态 |
| 重复相同事件/决定 | 返回已有资源，applied=false |
| 已决定后相反动作 | DECISION_ALREADY_TAKEN |
| 持久化失败 | STORAGE_UNAVAILABLE，不确认批准、不派发外发 |

飞书协议接收成功不等于审核已批准。适配器可先确认事件收妥，但必须在决定真实持久化后才向用户展示“已批准”。

### BE-IF-03 内部执行入口

`executePublish(input: JobIdentity, ctx: ExecutionContext): Promise<PublishJob>`。

只有受信执行器可调用；不通过任何模型可见工具直接授予权限。必须复核绑定记录、快照、资产、账号、期限和能力。失败恢复与证据语义按 BE-STATE-02，不让 LLM 自行推断“应该再发一次”。

### BE-IF-04 可替换外部端口

| 端口签名 | 输入输出与边界 |
| --- | --- |
| `ReviewChannel.send(review: ReviewRequest, draft: Draft): Promise<Pick<ReviewRequest, 'delivery_status' \| 'provider_message_id'>>` | 只向已配置会话发送审核内容；内部错误转换为 ContractError，不回传原始 SDK 类型 |
| `Publisher.check(input: ReadinessRequest): Promise<ReadinessReport>` | 只读；READY 必须符合 SC-07 |
| `Publisher.prepare(job: PublishJob, manifest: PublicationManifest, ctx: ExecutionContext): Promise<PreparedSubmission>` | 准备上传/编辑页但不最终提交；PreparedSubmission 为不可序列化的受控句柄，只在当前执行中有效 |
| `Publisher.submit(prepared: PreparedSubmission, ctx: ExecutionContext): Promise<PublishObservation>` | 唯一最终提交边界；必须在 SUBMITTING 已落盘之后调用 |
| `Publisher.reconcile(job: PublishJob): Promise<PublishObservation>` | 只读核对，不上传、不点击最终提交 |

PreparedSubmission 是内存能力句柄，不是公开 Schema；持久化只存标准 job。跨重启不得重用句柄。提供方若返回非法结构，提交前为 DEPENDENCY_INVALID_RESPONSE；提交后涉及受理不确定时为 RESULT_UNKNOWN。

### BE-IF-05 无公共 REST 服务

本期应用接口通过 DSH 插件内桥接调用，不要求另建 FastAPI。飞书接收传输和卡片事件格式属于 INT-03 的待验证项；选择后补适配契约，不能先生成猜测的 HTTP 路由或回调字段。

## 6. 异常与错误契约

### BE-ERR-01 错误目录

字段结构按 ContractError。下表为领域传播边界；本期无公共 HTTP 状态映射。

| code | 触发 | 恢复 / retryable |
| --- | --- | --- |
| VALIDATION_ERROR | 缺失/多余字段、类型/范围/游标非法、纯空白正文 | 改输入；false |
| UNAUTHORIZED | 无可信上下文、飞书来源验证失败 | 完成认证；false |
| FORBIDDEN | 工作区、审核人、组织或操作权限不符 | 管理员处理；false |
| NOT_FOUND | 工作区内不存在或不可访问的资源 | 返回列表；false |
| REVISION_CONFLICT | 修订/送审期望版本或摘要不匹配 | 重新读取再改稿；false |
| DRAFT_LOCKED | 修改或重审已批准内容 | 另建草稿；false |
| STALE_REVIEW | 旧卡片、已被改稿取消的审核、卡片绑定不符 | 使用新卡片；false |
| REVIEW_EXPIRED | 审核时间已到期 | 新版本重新送审；false |
| DECISION_ALREADY_TAKEN | 对终态审核作相反决定 | 展示已有结果；false |
| IDEMPOTENCY_CONFLICT | 同键或同事件 ID 携带不同内容 | 使用正确原请求；false |
| ASSET_INVALID | 资源不存在、越界、重复、不归属工作区或格式/尺寸非法 | 重新导入合法资产；false |
| ASSET_CHANGED | 已导入资产或快照字节被替换 | 重新建稿审核；false |
| CAPABILITY_UNSUPPORTED | 依赖不支持图文/最终提交等必需能力 | 替换或补适配器；false |
| DEPENDENCY_UNAVAILABLE | 依赖不可达且确认无外发副作用 | 只读或安全操作可重试；true；提交后不使用此码冒充未受理 |
| DEPENDENCY_TIMEOUT | 只读或明确未提交的操作超时 | 只读/安全准备可重试；true |
| DEPENDENCY_INVALID_RESPONSE | 依赖输出不满足契约，且尚未最终提交 | 维护适配器；false |
| LOGIN_REQUIRED / CAPTCHA_REQUIRED | 登录失效或需用户完成验证，确认未提交 | 暂停；处理后显式 resume；false |
| ACCOUNT_MISMATCH | 当前实际账号与已批准目标不同或无法可靠核对 | 校正账号，重新核对；false |
| LAYOUT_CHANGED | 必需投稿控件无法确认，尚未提交 | 更新适配器，不能盲点；false |
| AI_LABEL_UNVERIFIED | 无法设置或核对平台支持的 AI 标识 | 补能力；false |
| APPROVAL_EXPIRED | 批准后首次最终提交已超期 | 未提交证据明确后另建稿审核；false |
| RESULT_UNKNOWN | 最终提交可能已被平台接受，但无可靠结论 | 只读核对；false |
| JOB_NOT_RESUMABLE | 非安全 BLOCKED 状态尝试恢复提交 | 查看任务或核对；false |
| STORAGE_UNAVAILABLE | 关键持久化未完成 | 未发生外发时可重试；true；提交中落盘失败按未知处理 |
| PREVIEW_UNAVAILABLE | 审核人无法查看完整文字/图片 | 修预览后再送审；true |
| INTERNAL_ERROR | 未分类内部异常 | 显示 trace ID，查询状态；false，不暴露堆栈 |

错误优先级：先做来源/权限校验，再查询可访问资源，再判定请求幂等，随后判断版本/状态。合法幂等重放不能被后续状态变化误判为第二次操作。未知异常不得导致自动最终提交。

## 7. 非功能规格

所有数值是本稿待批准的产品目标，非已测成绩。

| 条款 | 要求 | 验证归属 |
| --- | --- | --- |
| BE-NFR-01 | 审核 86400 秒有效，首次提交期限为批准后 3600 秒；边界使用 `now >= deadline` | CT-08、CT-12，假时钟 |
| BE-NFR-02 | 普通只读外部调用每次 10 秒，最多 2 次，重试等待 1 秒；最终提交最多调用 1 次，超时 60 秒后按证据决定未知，不自动重试 | CT-11、CT-15 |
| BE-NFR-03 | 发布准备最长 180 秒；操作被取消后若无法证明无最终提交，进入 RESULT_UNKNOWN；不得当作可重试失败 | CT-11/14 |
| BE-NFR-04 | 通知单次 15 秒，最多 2 次；只有已知未被接收才自动重试，等待 2 秒；结果未知保留 UNKNOWN 并供人工核对，不能回滚已批准或已发布结果 | CT-05、CT-16 |
| BE-NFR-05 | 主机醒着、依赖就绪、账号空闲时，批准落盘后 30 秒内开始 PREPARING；非平台发布完成 SLA | SP-01 |
| BE-NFR-06 | 同一账号最多一个活跃执行器；提交中失联不自动主备接管；只允许本机单实例 | CT-07/14、SP-02 |
| BE-NFR-07 | 凭据和资产路径不进模型上下文、卡片及普通日志；预览只对已授权审核人开放；无来源验证不应用决定 | CT-06、SP-03 |
| BE-NFR-08 | 草稿历史、图片快照、审核、任务、幂等和审计首期不自动删除，直至运营者停机维护；普通运行日志滚动保留 14 天。首期不提供在线删除 API，商业化时另定保留/删除契约 | IT-02、SP-04 |
| BE-NFR-09 | 发布前备份需覆盖资源记录与引用素材的一致集合；在隔离目录恢复后可核对版本/审核/任务，不触发真实投稿 | SP-04 |
| BE-NFR-10 | 原生操作入口在 4 核/8 GiB/SSD、1000 个草稿、无外部调用条件下，查询 p95 ≤500ms；不是对用户机器已作保证 | SP-01 |
| BE-NFR-11 | 具备失败回执和 trace ID；模型用量缺失为未知；调用 New API 不产生“永不宕机”承诺 | IT-01、CT-16 |

## 8. 业务硬规则

| 条款 | 不变量 | 违反时处理 |
| --- | --- | --- |
| BE-RULE-01 | 未经可信审核批准不得发生最终投稿 | 拒绝执行；SP-03 还需验证创作 preset 无旁路写能力 |
| BE-RULE-02 | 批准绑定精确版本、快照、图片顺序、账号、公开范围和 AI 声明 | 不一致拒绝，旧审核失效 |
| BE-RULE-03 | 人设、新闻、评论、模型输出不是授权来源 | 作为资料处理，不提升权限 |
| BE-RULE-04 | 一份有效审核只对应一个逻辑发布任务；同版本重复送审不复制审核 | 返回已有资源 |
| BE-RULE-05 | 结果未知绝不自动再提交；不能保证外部系统全局恰好一次 | 进入 RESULT_UNKNOWN，只读核对 |
| BE-RULE-06 | 真实发布成功必须有可核对证据，素材上传和消息发送不是发布成功 | 仅标 SUBMITTED/UNKNOWN，不能假报 PUBLISHED |
| BE-RULE-07 | 审核后原样发布，不静默改稿或添加未经审核的文字/图片 | 拒绝或另建稿审核 |
| BE-RULE-08 | 卡片 GET 预览无写副作用，只有可信审核动作才建立授权 | 预取、转发、机器人访问不触发批准 |
| BE-RULE-09 | 真实审批与测试环境隔离；假适配器成功不意味着真实平台已通 | 单独记录 IT 验收证据 |

## 9. 验收与追踪

统一追踪见 [验收矩阵](../acceptance.md)。模型与方法签名均为拟议定位，尚未生成骨架或测试文件。

| 验收 | 对应条款 | 预期 |
| --- | --- | --- |
| BE-AC-01 | BE-IF-01、BE-DATA-01/02、BE-STATE-01 | 草稿版本、资产和送审可被一致读取 |
| BE-AC-02 | BE-IF-02、BE-RULE-01—04、BE-NFR-01/07 | 只允许合法且未过期的准确版本建立唯一任务 |
| BE-AC-03 | BE-IF-03/04、BE-STATE-02、BE-RULE-05—07 | 正常、阻塞、未知与恢复有确定结果 |
| BE-AC-04 | BE-NFR-02—06、08—11、BE-RULE-08/09 | 超时、重启、通知、备份与真实验收独立验证 |

评审结论：待评审。未决项：DEC-01—DEC-07，尤其图文投稿真实能力、飞书事件传输与受控 preset 隔离。存在这些缺口时不得将本稿标为锁定。
