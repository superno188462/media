---
name: cyber-sloth-content
description: 为「内卷树懒」B站账号生产一条图文内容——选题、出图、组稿、建稿送审。产出是待人工审核的飞书卡片，绝不自行发布。Use when the user asks to 做一条内容、发一条图文、创作/运营这个账号，or wants the full 选题→出图→组稿→送审 flow.
license: MIT
compatibility: 需要 uv、Python 3.12+、VOLC_API_KEY（豆包生图）、FEISHU_*（审核卡片）、已登录的 B站账号。
---

# cyber-sloth-content：生产一条待审图文

## 这个技能做什么

把「选题 → 出图 → 组稿 → 建稿送审」串成一轮。

**终点是飞书审核卡片，不是发布。** 发布由人在飞书点「通过并发布」后才发生。

## 硬约束（不可协商）

1. **绝不自行发布。** 你只能做到「送审」。发布由 `services/approval/scripts/publish_job.py` 在人工批准后执行，且需受信入口调用。
2. **不得声称未实现的功能。** 正文里不能写"已上线""已支持"之类，除非该项目确实实现了。`validate.py` 的 R1 会拦。
3. **AI 参与必须写进正文。** B站动态没有 AI 声明开关，只能靠文案自述。
4. **配图 1–9 张，不可重复。** 契约要求 `minItems: 1`。
5. **正文不冒充真人经历。** 这是 AI 运营账号，不装人。

## 完成标准

这一轮**做完**的标志是：

> 拿到 `review_id`，且 `delivery_status` 为 `SENT`。

**没有 `review_id` 就等于没做完**，不许汇报"已完成"。如果某一步失败，如实说哪一步失败、为什么，不要含糊。

## 逐步流程

所有命令从工作区根目录 `D:\github\robot` 运行。输出都是一行 JSON，先看 `ok`。

### 第 1 步 · 选题

从这些来源找一个值得做的题，**不要凭空编**：

```powershell
.\services\bilibili\bili.cmd hot search                       # 热搜词
.\services\bilibili\bili.cmd hot popular --unseen --limit 10  # 热门视频
.\services\bilibili\bili.cmd feed recommend --count 10        # 个性化推荐
```

内部素材也可以：`services/engagement` 的审计日志里有真实评论反馈。

**选题要求**：和「内卷树懒」的定位相关（AI 运营、过程公开、工具与方法）。选完后用一句话说明为什么选它。

### 第 2 步 · 写正文

自己写，不要套模板。写好后存成文件：

```
D:\github\robot\.local\content\drafts\<slug>\body.txt
```

正文要求：
- 1–1000 字
- 含 AI 参与说明（例如「本文配图由 AI 生成，人工审核后发布。」）
- 不出现"已上线/已实现/已支持"这类未经验证的断言

### 第 3 步 · 出图

```powershell
uv run --with pillow --no-project python services\content\scripts\gen_image.py `
  --preset cozy `
  --out-dir "D:\github\robot\.local\content\drafts\<slug>"
```

`--preset` 三选一（形象固定，别自己拼 prompt）：

| preset | 效果 |
|---|---|
| `head` | 大头特写，适合头像 |
| `bust` | 半身托腮 |
| `cozy` | 捧咖啡杯，**默认推荐** |

要自定义用 `--prompt`。先加 `--dry-run` 看会发送什么。

**出图后必须自己看一遍**（用 `read_image`）。Seedream 会自作主张加文字，即使负面提示词写了 `text`。发现画面里有文字就重出。

返回 `data.paths` —— 这是本地图片路径，第 4 步要用。

### 第 4 步 · 组稿

```powershell
uv run --with pillow --no-project python services\content\scripts\render_post.py `
  --title "内卷树懒 · <标题>" `
  --body-file "D:\github\robot\.local\content\drafts\<slug>\body.txt" `
  --image "<第 3 步返回的路径>" `
  --out "D:\github\robot\.local\content\drafts\<slug>\post.jpg"
```

多条 `--image` 的顺序就是发布顺序。返回 `data.path`、`width`、`height`。

**建议也看一眼成稿**，确认排版没有溢出或重叠。

### 第 5 步 · 建稿送审

```powershell
uv run --with lark-oapi --no-project python services\feishu\scripts\send_draft.py `
  --title "内卷树懒 · <标题>" `
  --body-file "D:\github\robot\.local\content\drafts\<slug>\body.txt" `
  --image "D:\github\robot\.local\content\drafts\<slug>\post.jpg" `
  --account-id "bilibili:383714514"
```

这一步会：
1. 在审核状态机里建草稿（`create_draft`）
2. 建立审核（`request_review`，有效期 24 小时）
3. 上传配图到飞书，拿 `img_key`
4. 发审核卡片到审核群

**成功标志**：输出里有 `review_id` 且 `投递状态: SENT`。

### 第 6 步 · 汇报

告诉用户：

```
草稿 draft-xxxx v1
审核 rv-xxxx（PENDING，有效期至 …）
飞书消息 om_xxxx
```

然后**停下来等人审核**。不要催，也不要自己去批准。

## 出错怎么办

| 现象 | 处理 |
|---|---|
| `NO_CREDENTIAL` | 缺 `VOLC_API_KEY`，查 `.local/dsh/.credentials.yaml` 或环境变量 |
| `IMAGE_FAILED` | 生图失败。看 `hint`，可能是配额或模型名 |
| `ASSET_MISSING` | 配图路径错，回第 3 步确认返回的 `paths` |
| `TOO_LARGE` | 成稿超长边上限，减小 `--width` 或减少配图 |
| 飞书 `99991672` | 缺权限，见 `services/feishu/README.md` 的权限表 |
| `VALIDATION_ERROR` | 内容没过契约校验，读 error message；**不要绕过**，改内容 |

**不要为了让流程走下去而删除校验、跳过送审或伪造 `approved`。**

## 不归这个技能管

| 事情 | 去哪 |
|---|---|
| 发布已批准的内容 | `services/approval/scripts/publish_job.py`（需人工批准后） |
| 评论互动 | `services/engagement`（poll / triage / reply） |
| 视频 | 契约还不支持（CHANGE-002 待评审） |

## 相关文档

- 契约：`manual/contracts/cyber-sloth.schema.json`
- 后端规格：`manual/specs/backend/approval-publishing.spec.md`
- 内容模块：`services/content/README.md`
- 角色设定：`services/content/src/content/imagegen/prompts/neijuan_sloth.md`
