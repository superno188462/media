# content · 内容生产流水线

内卷树懒的内容生产模块：**选题 → 文案 → 配图 → 组稿 → 校验 → 人工审核 → 发布**。

模型负责产出，**人负责批准**。这条边界由代码强制，不靠自觉。

## 脚本入口

`scripts/` 下的命令都输出**一行 JSON**（与 bili-cli 同风格），供 Agent 调用：

| 脚本 | 作用 | 实测 |
|---|---|---|
| `gen_image.py` | 出图（豆包 Seedream，角色预设固定形象） | ✅ |
| `render_post.py` | 图文组稿（Pillow 排版） | ✅ |
| `tts.py` | 配音（豆包语音合成） | ✅ |

## 外部组件：ffmpeg

音视频探测与合成依赖 ffmpeg。二进制**不进版本库**，放在 `services/content/.runtime/ffmpeg/`
（`services/**/.runtime/` 已在 `.gitignore` 中）。

`content/ffmpeg.py` 的定位顺序：

1. `FFMPEG` 环境变量（容器或 CI 显式指定）
2. `services/content/.runtime/ffmpeg/ffmpeg.exe`（Windows）或 `ffmpeg`（POSIX）
3. 系统 `PATH`

**容器部署**：镜像内安装即可（Debian/Ubuntu 用 `apt-get install -y ffmpeg`），
此时走第 3 条。本地那份是带 DLL 的动态链接 Windows 构建（约 96 MB，32 位），
不要复制进镜像。

**许可证**：自带的 Windows 构建启用了 `--enable-gpl`，以镜像形式分发时需按 GPL 处理；
不想要这个约束就用发行版提供的 ffmpeg。

**沙箱限制（本机实测）**：ffmpeg 作为子进程**无法写入 `.local/`**（Permission denied），
但工作区其他位置可写。因此渲染中间产物请放到 `services/content/.runtime/` 下，
不要放 `.local/`。

## 职责边界

| 环节 | 谁做 | 落地位置 |
|---|---|---|
| 选题 | 人（或人从评论里挑） | `ContentItem.topic_id` |
| 文案 | 模型起草 | `ContentItem.body` |
| 配图 | 模型生成 | `imagegen/` 适配器 |
| 组稿 | 代码渲染 | `render.py` |
| 校验 | 代码强制 | `validate.py` |
| **批准** | **人** | `ContentItem.status` |
| 发布 | 代码执行 | `publish/bilibili.py`（需先 dry-run） |

## 快速上手

```bash
cd services/content

# 跑测试
uv run --with pytest --with pillow --no-project python -m pytest tests/ -q

# 端到端演练（只做到「待人工审核」，不会发布）
$env:VOLC_API_KEY = "<你的 key>"
$env:PYTHONPATH = "$PWD/src"
uv run --with pillow --no-project python examples/pipeline_demo.py
```

## 三条硬规则

在 `validate.py` 里实现，由 `tests/test_validate.py` 锁定。

### R1 · 未实现功能不得声称

正文出现"已上线/已开始运营"这类断言，而项目状态里没有对应实现时，**直接拦下**。

这条来自真实教训：第一条动态写的是"打算做一个由 AI 运营的账号"，
而项目实际只有调研和几个工具，措辞一旦飘了就是虚假宣传。

### R2 · AI 声明不可省

B 站的**动态和评论没有平台级「含 AI 生成内容」开关**（只有视频投稿有）。
所以 AI 参与只能靠正文自述。`ai_declaration` 字段必须填。

### R3 · 图片顺序即契约

`images` 的顺序就是发布顺序，每张图都要有对应的 `source_urls` 记录。
数量对不上就拦下——避免发出去的图和素材台账对不上。

## 审核闸门

`ContentItem.status` 走状态机：

```
draft ──→ pending_review ──→ approved ──→ published
             │
             └──→ draft（人工驳回）
```

`validate()` 里有一条 `GATE` 规则：**只有 `approved` 能通过**。
模型无法自己把自己置为 `approved`——那需要人工动作。

## 生图适配器

`services/content/src/content/imagegen/`：

- `base.py` —— `ImageGenerator` 协议，换后端不动业务代码
- `volcengine.py` —— 豆包 Seedream（当前实现）

### ⚠️ Base URL 陷阱

Agent Plan 个人版的 key 走 **`/api/plan/v3`**：

```
https://ark.cn-beijing.volces.com/api/plan/v3/images/generations
```

和 ModelArk 的 `/api/v3` **不是同一个入口**。用错会得到 **401**，
而且看起来很像 key 有问题——实际 key 是好的。

模型名：`doubao-seedream-5-0-pro`（`-flash` 更便宜更快）。

### 凭据

key 放环境变量 `VOLC_API_KEY`，**不要写进代码或文档**。
当前项目里放在 `.local/dsh/.credentials.yaml`（不进版本库）。

## 角色设定

`services/content/src/content/imagegen/prompts/neijuan_sloth.md`

账号「内卷树懒」的固定形象。**不要每次现编 prompt**——形象要稳定。

## 素材台账

`services/content/assets/SOURCES.md`

每张对外发布的图都要在这里有记录。没记录的图不得发布。

## 目录

```
services/content/
├── pyproject.toml
├── README.md
├── assets/
│   ├── SOURCES.md          # 素材来源台账
│   ├── avatar.png          # 账号头像
│   └── posts/              # 成稿
├── examples/
│   └── pipeline_demo.py    # 端到端演练
├── src/content/
│   ├── model.py            # ContentItem + 状态机
│   ├── validate.py         # R1/R2/R3 + GATE
│   ├── render.py           # Pillow 成稿渲染
│   └── imagegen/
│       ├── base.py         # ImageGenerator 协议
│       ├── volcengine.py   # 豆包 Seedream 适配器
│       └── prompts/
│           └── neijuan_sloth.md
└── tests/
    ├── test_model.py
    ├── test_validate.py
    └── test_render.py
```

## 与其他模块的关系

- `services/bilibili/` —— B 站接入；本模块的发布环节通过它落地
- `manual/contracts/cyber-sloth.schema.json` —— 公共字段的权威
- `manual/specs/` —— 行为规范；新增内容类型要先改 SDD 再实现

## 未完成

- `publish/bilibili.py` —— 发布适配器（dry-run → publish），**未实现**
- 飞书审核对接 —— 首期范围，**未实现**
- 选题池存储 —— 只有 `topic_id` 字段，没有池子本身
