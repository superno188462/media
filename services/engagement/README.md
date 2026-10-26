# engagement · 互动分流

评论处理分**四层**，成本递增。前三层便宜，只有值得的少数才花模型和人工。

```
评论（可能几百条）
   ↓ ① 服务端过滤：comment list --unreplied          免费
未回复的（几十条）
   ↓ ② 水位线增量：只取 last_rpid 之后的             免费
新增的（几条）
   ↓ ③ 意图识别：**大模型为主，正则为辅**             便宜
值得回的（Top N）
   ↓ ④ 起草回复
   ↓ ⑤ 发送前门禁：**大模型独立把关**                 必过
   ↓ ⑥ 发送
真正回复（2–5 条）
```

> 状态：**前置契约的原型**。评论回复尚未进入 `Draft / ReviewRequest /
> PublishJob` 体系（待 CHANGE-003）。

## 两层判定

| 层 | 模块 | 回答 | 实现 |
|---|---|---|---|
| 第一层 | `intent.py` | **要不要回** | 大模型（正则只做硬拒绝预筛） |
| 第二层 | `policy.py` | **怎么发**（直发/批量/单条） | 确定性规则 |

顺序不能颠倒：先判要不要回，再判怎么发。

## 意图识别：模型为主，正则为辅

分工明确：

| 谁 | 做什么 | 为什么 |
|---|---|---|
| **正则** | 只硬拒绝**明显**的垃圾（纯表情、广告、辱骂、沙发） | 省钱：命中就不调模型 |
| **大模型** | 真正的语义判断：提问？技术讨论？值得回吗？ | 正则读不懂「我在测链路，换行被截断」这种技术陈述 |
| **兜底** | 模型挂了退回正则，`source` 标注 `regex-fallback` | 不静默降级，能看出这次没模型 |

**兜底原则不变：拿不准就不回。**

## 发送前门禁（结构强制）

`reply.py` 的发送路径上有一道**过不去的关卡**：没有 `GateDecision(allows_send=True)`
就走不到 `comment reply`。

设计要点：

1. **独立判断** —— 门禁只收到「对方原评论 + 待发回复」，**不给它起草时的理由**，
   避免模型为自己的措辞辩护。
2. **fail closed** —— 门禁不可用、调用失败、返回不合法，一律 **deny**。
   不是「失败就放行」。
3. **可审计** —— 决定、风险、理由全部落盘到 `extra.gate_*`。

门禁清单（写进 system prompt）：

1. 是否冒充真人经历或情感
2. 是否包含承诺、时间点、金额、数量
3. 是否包含未经核实的事实断言
4. 是否包含链接、联系方式、隐私
5. 是否涉及争议、负面、对立
6. 语气是否可能被截图断章取义
7. 是否与「AI 运营、过程公开、不装人」一致
8. 是否与对方原评论相关（答非所问也不合格）

三种结果：`approve` 可发 / `escalate` 待人确认 / `deny` 不能发。

## 真实门禁效果（deepseek-chat 实测）

| 待发回复 | 门禁 | 命中 |
|---|---|---|
| 「谢谢记录。根因是多行正文被换行截断，已改成用文件传。」 | ✅ approve / low | — |
| 「下周就上线修复版本，保证解决」 | ❌ deny / high | 时间承诺、保证性承诺、未核实断言、断章取义风险 |
| 「我当年也是这么踩坑的，熬了三天才搞明白」 | ❌ deny / high | 冒充真人经历、具体数字、答非所问、装人 |
| 「今天天气不错，出去走走吧」 | ❌ deny / medium | 答非所问、敷衍、与账号定位不符 |

注意第 3 条——它同时抓出了「冒充真人」和「编造数字」，这正是纯正则做不到的。

## 防止「收集所有评论」

| 手段 | 作用 |
|---|---|
| `--unreplied` | 服务端先筛掉已回复的 |
| **水位线** | 每评论区记 `last_rpid`，只处理更新的；被拒的也推进，不反复检查 |
| `max_pages` | 翻页上限，默认 2 页 |
| 短页即停 | 不足一页视为最后一页 |
| `limit` | 候选上限，默认 10 条 |
| 正则硬拒绝 | 明显垃圾不进模型，省 token |

## 用法

```bash
cd services/engagement

# 漏斗（模型识别意图）
uv run python scripts/triage.py --oid 413402056 --type draw

# 只用正则，不调模型（省钱/离线）
uv run python scripts/triage.py --oid 413402056 --no-llm

# 调试：连已回复的一起看分类
uv run python scripts/triage.py --oid 413402056 --include-replied

# 发送（必过门禁）
uv run python scripts/reply.py --oid <oid> --rpid <rpid> \
    --file reply.txt --source-file source.txt

# 只判第二层，不发送
uv run python scripts/reply.py --assess-only ...

# 验证 fail-closed：禁用模型后一定发不出去
uv run python scripts/reply.py --no-llm ...
```

## 审计

`.local/engagement/audit.jsonl`：

```json
{"event_id":"...","risk":"low","route":"direct","rule":"template:thanks",
 "outcome":"sent","platform_rpid":321952387456,
 "extra":{"gate_decision":"approve","gate_risk":"low","gate_source":"llm","model_gate":true}}
```

`outcome` 取值：`sent` / `held`（第二层拦下）/ `gate_denied`（门禁拦下）/ `failed`。

## 模型配置

`llm.py` 从 `.local/dsh/.credentials.yaml` 读 `DEEPSEEK_API_KEY`，
默认 `https://api.deepseek.com/v1` + `deepseek-chat`。

拿不到 key → 门禁不可用 → **拒绝一切发送**（这是故意的）。

## 实现注意

**正文一律用 `--file` 传，不拼命令行。** 曾因 `shell=True` + 多行正文，
Windows `cmd` 把换行当命令分隔符，只发出第一行、`--image` 与 `--dry-run`
全部失效，误发过一条截断动态。

## 测试

```bash
uv run --with pytest --no-project python -m pytest tests/ -q   # 100 个
```

模型相关的测试全部用 `FakeLlm`，不联网。

## 未完成

- 批量 / 单条卡片通道（飞书）
- 自动起草回复（当前需人工提供文本）
- 定时巡检（`fetch_new` 已就绪，未挂调度）
- 评论回复契约（CHANGE-003）
