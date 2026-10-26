# RedBeacon 基座分析：可迁移的工程方法

版本 `0.1.0`；日期 2026-10-26；状态：学习笔记，**非契约、非规格，不约束实现**。

## 范围声明（先读）

本文只提炼**工程方法**，服务于「内卷树懒」当前目标：把自动化运营链路做扎实。

**商业化分析不在本文范围。** 原项目如何用算力点与发布计费形成收入，本文仅在「暂不采纳」一节留一句存档说明，不作为本项目的设计输入。当前阶段不设计计费、不设计多租户、不设计套餐。

## 证据分级

| 标记 | 含义 |
|---|---|
| `[源码]` | 本次静态阅读可在源码中核对，附文件与行号 |
| `[运行]` | 本次实际执行并观察到结果 |
| `[文档]` | 原项目自述的设计意图，未经本项目复现 |
| `[推断]` | 我的判断，无直接代码证据 |

**本次实际执行**：仅运行 `python examples/offline_workflow.py`（标准库 + 内存端口），确认 5 条业务规则生效。未安装依赖、未启动客户端、未登录、未联网、未执行任何 Skill 命令、未发布任何内容。

**教学副本限制**：平台服务端、真实数据、生产权限均不包含。因此本文所有结论都只覆盖**客户端实现**，不能据此推断服务端行为或商业验证。

---

## 1. 为什么值得读它

`[文档]` 原项目把「一位数字员工持续运营多个内容账号」当作完整工作来处理，而不是「输入提示词，返回一篇文案」（`软件设计思路.md:9`）。它的价值在于：**同一条业务链路同时服务桌面界面、AI 助手和定时自动化三个入口，而规则只有一份。**

「内卷树懒」目前的分层形状与它接近（`services/content` 生产、`services/approval` 状态机、`services/feishu` 审核、`services/engagement` 互动），但有几处工程纪律明显弱于它。本文把这些差异列成可执行的改进项。

---

## 2. 核心结构

`[源码]` 唯一组装点是 `composition.py`，其文件头写明「其它任何地方（adapters/）都不许 import infra/」。

```
┌──────────────┬──────────────┬──────────────┐
│  桌面 UI      │  CLI (AI)    │  账号自动化    │   ← 三个入口
└──────┬───────┴──────┬───────┴──────┬────────┘
       └──────────────┼──────────────┘
                      ▼
        ┌─────────────────────────────┐
        │  core/usecases/  （唯一规则） │   ← 审核门槛、状态转换、重试顺序
        └──────────────┬──────────────┘
                      ▼
        ┌─────────────────────────────┐
        │  core/ports.py  （Protocol） │   ← 只声明"需要什么能力"
        └──────────────┬──────────────┘
          ┌────────────┼───────────┬──────────┐
          ▼            ▼           ▼          ▼
       SQLite      平台网关     浏览器发布   本机渲染
                            ▲
                     composition.py（唯一组装点）
```

**对我们有意义的一点**：`[源码]` 桌面 UI **不经过 CLI**。`教学导读.md:9` 明确「不要让 UI 后端通过解析 CLI 输出完成业务」。CLI 只是给 AI 和人工诊断用的一个入口，不是唯一入口。

---

## 3. 六条可迁移方法

按对「自动化运营」的价值排序。

### 方法 1 · 工作包冻结（最高价值）

`[源码]` 程序先冻结业务快照，再交给 AI：

| 证据 | 位置 |
|---|---|
| 工作包结构 | `core/domain.py:764 CreationWorkPackage`（含 `topic`/`plan`/`copy_task`/`image_intent`/`paths`） |
| 不得含密钥 | 同处注释：「不得包含令牌、Cookie 或代理秘密」 |
| 程序准备 | `core/usecases/creation.py:365 prepare_item()` |
| AI 不重拼 | `.codex/skills/redbeacon-generate/SKILL.md:88`：「不自行重新拼定位、选题或方案」 |
| 风格冻结 | 同文件 `:98`：重试沿用原 `generation_id` 与 `style_snapshot`，不能重抽 |

**为什么值钱**：把 AI 的出错面收敛到"写文案、画图"两件事。重试不会换选题、换风格、换方案；宿主失败可以精确回退到"只补图片，文案不重做"。

**适用前提**：有一份可序列化的完整业务上下文，且 AI 侧能读写本地文件。

### 方法 2 · 一份规则，多入口共用

`[源码]` `core/usecases/review.py:117 review_preflight_issues()` 是纯函数：UI 可复用它做实时预审，`submit_review():221` 在落库前再调一次——**两处调用，一份实现**。

**为什么值钱**：避免出现"CLI 能过、UI 不能过"的双标。

**适用前提**：规则能提炼成纯函数且入口无法绕过。

### 方法 3 · 完成标准是可验证事实

`[文档]` `redbeacon-generate/SKILL.md:18`：「成稿只进入审稿台，不自动通过、不自动发布。」批次结束读 `batch-status` 汇总；只有出现新成稿才打开一次 UI。

**为什么值钱**：AI 说"做完了"不算，要能查到一个记录 ID。

**适用前提**：终态能被程序查询。

### 方法 4 · 副作用前验收，副作用后按证据重试

`[源码]` 两道闸门都在写库之前：

| 闸门 | 位置 | 作用 |
|---|---|---|
| 文案解析 | `core/usecases/generate.py:297 parse_copy()` | 不是合法 JSON、正文为空 → 直接拒绝，**不写审核表** |
| 发布前校验 | `core/usecases/publish.py:86 validate_publish_payload()` | 空标题/坏字符/JSON 残留/无图 → 拦下 |

重试前先查"迟到成功"：`publish.py:392-395` 在 attempt > 1 时调 `recover_before_retry()`，拿到回执就不再重发。

**适用前提**：外部动作有可查回执（哪怕迟到）。

### 方法 5 · 先归档、再删源（顺序铁律）

`[源码]` `publish.py:6` 写死了顺序：「**先 archive_create 成功、再 review_delete**；归档失败不删审核行（宁可重试不丢数据）。」

失败分支的处理是重点（`:467-477`）：已发布但归档失败 → 返回 `PUBLISH_OK, archived=False`，把原稿标为"需人工处理"，**绝不回待发队列**（否则会重复发布）。

**适用前提**：有两个存储位置，且能容忍短暂重复。

### 方法 6 · 恢复计划由程序生成

`[源码]` `core/usecases/creation.py:1359 recover_batch()` 返回带 `actions[].sequence` 的计划；Skill 只按序执行（`generate/SKILL.md:71-80`），不自己推断"做到哪一步了"。

**为什么值钱**：崩溃恢复时不靠 AI 猜，避免跳过已扣费阶段或重做已完成工作。

**适用前提**：有持久状态机，且每个阶段可判定。

---

## 4. 映射到「内卷树懒」：现状与差距

| 方法 | 我们的现状 | 差距 |
|---|---|---|
| 1 工作包冻结 | 🟡 `services/feishu/scripts/send_draft.py` 由调用者传 title/body/image；`.agents/skills/cyber-sloth-content` 让模型自己写正文 | **没有冻结层**：重试时模型可以换文案；选题/方案/风格没有快照 |
| 2 一份规则 | ✅ `services/approval` 与 `services/content/validate.py` 规则集中 | 基本达标 |
| 3 可验证完成标准 | ✅ Skill 已写「拿到 `review_id` 才算做完」 | 达标 |
| 4 副作用前验收 | 🟡 `validate.py` 有 R1/R2/R3；`gate.py` 有门禁 | 缺"发布前 preflight"统一函数；门禁只在评论链路 |
| 5 先归档再删源 | ❌ 发布后只置任务终态，没有归档记录 | **完全没有归档概念**，发布成功的历史无处可查 |
| 6 恢复计划 | ❌ 无断点续跑 | 进程中断后只能人工判断 |

另有两处结构性问题：

| 问题 | 我们的现状 | RedBeacon 的做法 |
|---|---|---|
| CLI 传结构化数据 | 🟡 只在 `publish_job.py` 用了 `--file` 传正文（今天误发后修的） | `[源码] routers/_json_input.py:1-5` 统一提供 `--json-file` / `--json -`，理由写明「Windows shells and .cmd shims are fragile」 |
| 状态转换集中 | ❌ `services/approval/src/approval/service.py` 的转换散落各处 | `[源码]` 用 `transition_item(expected_status=..., target_status=...)` 逐处断言（也是弱点，见 §6） |

---

## 5. 优先采纳的三条

按"投入小、收益直接"排序。

### 5.1 先用文件传结构化数据（半天）

**问题**：今天已发生一次真实事故——多行正文拼进命令行，Windows `cmd` 把换行当命令分隔符，误发了一条截断动态。

**做法**：为所有接受多行文本或 JSON 的脚本统一 `--file` 入参，禁止内联长参数。

**验证**：用一条含换行的正文跑一次 `--dry-run`，确认输出的 `text` 与源文件逐字一致。

**落地范围**：`services/content/scripts/*`、`services/feishu/scripts/*`、`services/engagement/scripts/*`、`services/approval/scripts/*`。

### 5.2 引入"内容工作包"（1–2 天）

**问题**：现在模型写正文、调 `send_draft.py` 送审，中间没有冻结层。重试或换会话时，文案、配图、标题可能不一致，而审核绑定的只是最终产物。

**做法**：新增最小工作包——程序先生成一份冻结的 `work.json`（含 topic/plan/prompt/paths/generation_id），模型只填正文与图片路径，`send_draft.py` 校验 `generation_id` 与工作包摘要后才允许送审。

**验证**：同一 `generation_id` 重复送审返回同一 `review_id`（幂等）；篡改工作包后送审被拒。

**注意**：这是新增契约面，按 GOV-04 应先提 CHANGE 再实现。

### 5.3 补"归档"这一环（半天）

**问题**：发布成功后只有 `PublishJob` 状态变化，没有独立的归档记录。查历史只能翻 `.local/approval/*.json` 的任务表。

**做法**：发布成功后写一条归档记录（标题、正文、图片、平台 ID、链接、发布时间、批准它的 `review_id`），再置任务终态。顺序按 RedBeacon 的铁律：**先写归档，成功后再置终态**；归档失败时任务保持可核对状态，不标记为完成。

**验证**：制造归档写入失败（如只读目录），确认任务不被标记为 PUBLISHED，且提示"已发布但归档未完成"。

---

## 6. 我们暂不采纳的部分

### 商业化相关（当前阶段明确不做）

`[源码]` 原项目有三段式计费（`platform_account/publish_billing.py:3-4`：reserve 预留 → complete 结算 / cancel 回补）和按账号聚合的 AI 调度（`platform_account/scheduler.py`）。

**为什么不采纳**：本项目当前目标是验证自动化运营是否跑得通，不是验证付费模型。加入计费会引入平台账号、套餐、对账、退款等一整套与当前目标无关的复杂度。

**存档一句**：它把「发布」这个不可绕开的动作做成收费点，把「生成」做成可绕开的收费点（优先用宿主 AI 时平台调用为 0）。**这只是它的商业结构，不是我们的设计输入。**

### 技术上也暂不采纳

| 项 | 为什么暂不采纳 |
|---|---|
| 跨进程 FIFO 生成队列（`services/generation_queue.py`） | 我们是单机单进程起步；真要并发再引入，否则是无收益复杂度 |
| 数据库结构核验 + 迁移演练（`services/database_upgrade.py`） | 我们的状态存 JSON，没有 schema 迁移问题；换成 SQLite 时再考虑 |
| 多账号隔离与运行时通道隔离 | 当前单账号；但**账号 ID 已经贯穿**，将来加多账号不必重构 |
| 22 KB 主 Skill 的对话编排风格 | 我们的 Skill 面向"跑通流程"，不是面向"像下属一样服务用户"，体量应控制在可维护范围 |

---

## 7. 如果要深挖，按这个顺序读

| 顺序 | 文件 | 看什么 |
|---|---|---|
| 1 | `examples/offline_workflow.py` | 先跑一遍，知道规则在干什么 |
| 2 | `core/usecases/review.py`（337 行，最短最完整） | 规则在用例、IO 在端口 |
| 3 | `core/usecases/publish.py:274 publish_one()` | 顺序红线、重试、归档 |
| 4 | `core/usecases/generate.py:297 parse_copy()` | 副作用前的闸门 |
| 5 | `core/domain.py` 的 `CreationWorkPackage` / `TopicReservation` | 工作包与预留 |
| 6 | `core/usecases/creation.py:142 prepare_batch()` → `:934 commit_host_result()` | 批次与原子入审 |
| 7 | `routers/_runtime.py` + `_json_input.py` | CLI 输出契约与文件传参 |
| 8 | `composition.py` | 唯一组装点 |

原项目路径：`D:\github\小红书\RedBeacon-Learning-20261024`（教学脱敏副本，非生产代码）。

---

## 8. 已知弱点（不照抄）

读它的同时也要看到它的问题，避免把缺陷一起搬过来。

| 弱点 | 证据 | 我们的对策 |
|---|---|---|
| 重试宽泛捕获 + 在 core 里 `sleep` | `publish.py:421` `except Exception`；`:426` `time.sleep(delay)`；`:61` 硬编码延迟 | 区分可重试/不可重试异常；等待策略从端口注入，core 不阻塞 |
| 状态值是中文字符串，且与英文混用 | `review.py:31-35` `{"approve": "通过"}`；`domain.py:950` `PUBLISH_OK="published"` | 我们用稳定英文枚举，展示文案放适配器 |
| 状态转换无集中表 | `transition_item(expected_status=..., target_status=...)` 逐处传参 | 抽一张 `TRANSITIONS` 表 + 启动自检 |
| CLI JSON 契约无 schema 校验 | `_json_input.py:89-92` 只校验 object/array | 入参出参加 JSON Schema 校验 |
| 格式预审 ≠ 事实准确性 | `review_preflight_issues()` 只查长度/非空/图片数 | 我们明确定位：格式校验在代码，事实与立场靠人工审核 |

---

## 9. 一句话结论

> **把 AI 的自由度限制在内容创作上，把业务约束全部收进确定性代码。**

对「内卷树懒」当前阶段的直接含义：先把**入参纪律（文件传数据）**和**冻结层（工作包）**补上，再补**归档**，其余（队列、迁移、计费）等真的需要时再说。

## 相关文档

- [工具研究](creator-tools-analysis.md)：bili-cli、my-code 与直播链路分析（另一份外部项目调研）
- [阶段评审与变更记录](../specs/governance.md)：新增契约面须走 CHANGE 流程
- [接入准备](integration-readiness.md)：我们的真实依赖验证记录
