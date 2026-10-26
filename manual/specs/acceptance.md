# 契约覆盖与验收计划

版本：`0.1.0-draft.1`；对应候选行为基线/Schema：`0.1.0`；日期：2026-10-26；状态：待评审。

本文件定义将来需要证明的行为。没有测试代码，没有真实账号验收记录，所有条目当前均为“计划”。文档链接、JSON 语法或 Schema 示例校验成功不等于以下行为通过。

## 1. 服务端契约测试计划

| 用例 | 需求 / 规格 | 正常、边界与异常场景 | 骨架计划定位 |
| --- | --- | --- | --- |
| CT-01 | REQ-04/12；BE-DEP-02、BE-DATA-02；SC-04 | 合法 JPEG/PNG 导入；越界相对路径、符号链接越界、假扩展名、零字节、超过 10 MiB/8192 像素、错误归属、重复资产、字节被替换均拒绝 | AssetService.registerAsset / AssetStore |
| CT-02 | BE-DATA-01、BE-ERR-01；SC-01—03 | 对全部公开请求/返回定义参数化校验：必填/缺失/null/未知字段/严格类型/长度上下限/枚举/UTC/UUID/URI；纯空白和重复 asset_id 的语义校验另测 | 共享类型/边界校验器 |
| CT-03 | REQ-04/07；BE-IF-01、BE-STATE-01 | create 为 v1；修改为 v2；旧快照保留；待审修改取消旧审核；已批准版本不可修改；新版本需重新审核 | DraftService.createDraft / reviseDraft |
| CT-04 | REQ-09；BE-RULE-04；SC-06 | 同键同请求返回同资源；改请求同键冲突；修订请求重放不加版本；同版本新键送审复用有效请求；终态版本需先修订 | 各写方法幂等边界 |
| CT-05 | REQ-05；BE-IF-01、BE-NFR-04 | 送审记录先落盘，通知 QUEUED/SENT/FAILED/UNKNOWN 不混淆；完整预览缺失不送审；通知只有已知未受理才自动重试 | ReviewService.requestReview / ReviewChannel |
| CT-06 | REQ-03/06/12；BE-IF-02、BE-RULE-01/03；SC-05 | 合法审核人；伪签名/来源、错组织、错消息、非审核人、跨工作区、模型自填 verified 均不建立授权 | ReviewService.applyDecision / FeishuAdapter |
| CT-07 | REQ-06/09；BE-DATA-02、BE-NFR-06 | 双击、重复事件、两个审核人并发、批准与修订竞争；只形成一个决定和逻辑任务；落盘失败不确认批准；相反决定不能覆盖 | ReviewService.applyDecision / Repository |
| CT-08 | REQ-07；BE-STATE-01、BE-NFR-01 | 有效期前一瞬可批，等于/晚于 expires_at 拒绝；退回/取消/过期没有任务；旧卡片 STALE_REVIEW；重复决定的正确回显 | ReviewService.applyDecision / cancelReview |
| CT-09 | REQ-06；BE-IF-03、BE-RULE-01/02/07 | 未批准任务拒绝；错版本、摘要、账号、图片顺序、公开范围、AI 声明拒绝；合法批准不需第二次确认 | PublishingService.executePublish |
| CT-10 | REQ-10/11；BE-DEP-04、BE-IF-04；SC-07 | READY 七项能力和账号核验；只有视频、不支持图文/多图/AI 标识/最终提交/回执查询均不 READY | Publisher.check / prepare |
| CT-11 | REQ-09；BE-STATE-02、BE-NFR-02/03 | 准备 180 秒限制；只读两次上限与等待；最终提交一次上限；提交超时/非法回执/取消结果不明为 RESULT_UNKNOWN | PublishingService.executePublish / Publisher.submit |
| CT-12 | BE-NFR-01、BE-STATE-02 | 批准后 3600 秒边界；超期且未提交失败；已提交核对不受首次提交期限限制 | PublishingService.executePublish / resumePublish |
| CT-13 | REQ-09；BE-ERR-01、BE-STATE-02 | 登录/验证码明确未提交为 BLOCKED；安全恢复仍同一 job；错账号失败；RESULT_UNKNOWN/PUBLISHED/FAILED 不允许恢复重发 | PublishingService.resumePublish |
| CT-14 | REQ-09；BE-STATE-02、BE-NFR-06 | DRAFT、PENDING、QUEUED、PREPARING、SUBMITTING、已受理未落盘等故障点重启；不把提交中锁到期当重发信号 | PublishingService / 持久化恢复边界 |
| CT-15 | REQ-08；BE-RULE-05/06；SC-07 | 上传不等于受理；受理不等于公开；账号/作品/公开范围证据不匹配拒绝；列表暂缺不是未提交证明；核对不发第二条 | Publisher.reconcile / reconcilePublish |
| CT-16 | REQ-08/15；BE-NFR-04/11 | 飞书回执失败不能回滚平台成功；假链接/假用量不允许；未知用量明确显示；错误仅返回白名单 details 和 trace ID | ReceiptNotifier / 错误映射 |
| CT-17 | BE-IF-01、BE-ERR-01；SC-04/06 | 分页默认 20、上限 50、稳定排序、空页、非法游标、跨条件游标、资源不可访问、相同请求的原结果重放；详情关联当前版本审核/任务，无关联为 null | DraftService.listDrafts / getDraft |
| CT-18 | BE-DATA-02；SC-08/09 | 工作区序号递增、事件去重、资源/事件有效组合；持久化失败无成功事件；工具响应明确成功或结构化错误 | AuditStore / DshToolBridge |

CT-02 需要对 JSON Schema 每个属性生成或列出有效和无效场景；不能只用一个“正常 JSON 能解析”测试代表所有字段。SC-04、SC-05、SC-07 的跨资源语义不能只用 Schema 验证。

## 2. 前端交互契约计划

| 用例 | 对应规格 | 场景与预期 |
| --- | --- | --- |
| UI-CT-01 | FE-SCOPE-01、FE-DEP-01、UI-01/02 | 宿主兼容/不兼容；原生入口、初始、列表和空态 |
| UI-CT-02 | FE-STATE-01、FE-NFR-01、FE-ERR-01 | 加载提示、写操作禁重复、10 秒超时、输入保留和安全错误 |
| UI-CT-03 | FE-STATE-01、FE-NFR-02、FE-DATA-01 | 切换草稿/筛选、旧请求晚到、刷新恢复、详情轮询退出、较旧状态不覆盖 |
| UI-CT-04 | FE-ACTION-01、FE-RULE-01/02 | 完整版本展示与通过/退回/取消；卡片不把“阅读”当批准；新版本不继承旧批准 |
| UI-CT-05 | FE-ACTION-01/02、FE-RULE-03/04 | 只读核对按钮、BLOCKED 恢复、UNKNOWN 禁重发、提交中不提供假取消 |
| UI-CT-06 | FE-DEP-03、FE-NFR-02 | 后台批准成功但卡片更新失败；旧卡片再次点击仍由后台拒绝/幂等返回 |
| UI-CT-07 | FE-DATA-02、FE-NFR-04、FE-RULE-05 | null/空态、全部图片顺序、未授权预览、转义外部文本、GET 预取无写操作、客户端改状态无法授权 |

## 3. 真实集成计划

| 用例 | 覆盖 | 必需证据 |
| --- | --- | --- |
| IT-01 | DSH 原生插件、模型、工具、受限 preset、UI 桥接 | 固定版本、工具注册与卸载、实际模型调用；不输出密钥 |
| IT-02 | 持久化、资产、历史版本 | 真实文件摘要、重启查询、越界素材拒绝、快照一致性 |
| IT-03 | 飞书通知与审核 | 自建应用真实卡片、真实身份回调、重复事件、旧卡片、完整预览访问、失败回显 |
| IT-04 | 抖音图文准备 | 真实账号核对，多图顺序、正文、公开范围和 AI 标识，停最终提交前；记录插件/浏览器版本 |
| IT-05 | 一次批准后的自动发布 | 用户先审核该测试版本；后台自动提交；平台作品 ID、链接、状态、完整内容与公开范围核对；飞书回执 |
| IT-06 | 恢复与真实错误 | 依赖断开/重连、登录失效、进程重启、不确定结果的只读核对；不得用真实重复发布制造测试数据 |

IT-05 不因为本文件存在就提前授权外发。审核人对具体版本的“通过并发布”是该次外发授权。

## 4. 专项验收计划

| 用例 | 覆盖 | 方法与限制 |
| --- | --- | --- |
| SP-01 | BE-NFR-05/10、FE-NFR-01/02 | 记录机器和数据规模，测本机查询、批准后派发延迟和 UI 反馈；不把外部平台延迟算成本地 SLA |
| SP-02 | BE-NFR-06、BE-DATA-02 | 模拟持久化故障、同账号双进程、失联提交；验证第二执行器不能直接重发 |
| SP-03 | BE-NFR-07、BE-RULE-01/03/08、FE-NFR-04 | 检查凭据/路径脱敏，跨工作区拒绝，预览鉴权，签名与消息绑定；验证创作 preset 无通用 shell/浏览器/数据库旁路 |
| SP-04 | BE-NFR-08/09 | 用固定时钟验证 14 天日志规则；停机一致备份恢复到隔离目录，不自动启动真实发布 |
| SP-05 | UI-06、FE-NFR-03 | 桌面与手机视口、键盘焦点、图序、长正文与错误文字；平台宿主限制单独记录 |

## 5. 需求闭环索引

| 需求 | 主要验证 |
| --- | --- |
| REQ-01 / REQ-14 学习与迁移 | learning-roadmap 中 L0—L6 练习及开发者讲解 |
| REQ-02 / REQ-13 完整流程 | IT-01—IT-06 |
| REQ-03 权限 | CT-06/07、SP-03 |
| REQ-04 草稿 | CT-01—04、IT-02 |
| REQ-05 送审 | CT-05、UI-CT-04/07、IT-03 |
| REQ-06 自动发布 | CT-07/09/10、IT-05 |
| REQ-07 退回取消过期 | CT-03/08/12 |
| REQ-08 真实结果 | CT-15/16、IT-05 |
| REQ-09 恢复 | CT-11—15、IT-06、SP-02 |
| REQ-10 / REQ-11 复用与替换 | IT-01、CT-10、L6 假投稿适配器练习 |
| REQ-12 隔离 | CT-01/06、SP-03 |
| REQ-15 指标 | CT-16、SP-01 |

## 6. 阶段报告规范

每个用例后续记录基线、测试文件、命令、实际结果和证据。尚未生成测试时不填写虚构路径，不标“通过”。契约测试需 Mock 外部协作者，不 Mock 被测业务方法；不通过 skip/弱断言把未实现包装成成功。
