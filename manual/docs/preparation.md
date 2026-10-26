# 前期准备工作

本文记录把「内卷树懒」从空目录跑成可运行环境所需的全部准备步骤，以及每步的验证方式。
飞书侧的具体配置单独写在 [飞书配置指南](feishu-setup.md)。

> 状态：2026-10-26 在本机实测走通的路径。文中命令均为实际执行过的形式。
> 未在本机验证的项会明确标注，不把「照着做应该可以」写成「已验证」。

## 1. 目标形态

```
DSH 起草内容 → 服务层存草稿 → 飞书卡片送审 → 人点按钮 → 状态机落批准
                                                        ↓
                                                  发布任务（QUEUED）
                                                        ↓
                                              受信执行器调平台 → 核对回执
```

准备工作的目标就是让这条链路的每一段都可独立运行、可单独验证。

## 2. 环境要求

| 项 | 要求 | 本机实际 |
|---|---|---|
| 操作系统 | Windows（脚本用 `.cmd`） | Windows |
| Python | ≥ 3.12 | 3.12 / uv 自带 3.13 |
| 包管理 | `uv`（自建 Python 工具统一用它） | 已装 |
| DSH | 官方检出，位于 `dsh/` | `dsh-v0.2.1-rc.3` |
| 网络 | 可访问 B站、飞书开放平台、火山方舟 | 通 |
| 磁盘 | 预留 `.local/` 放凭据、状态和素材 | — |

检查：

```powershell
uv --version
python --version
Test-Path .\dsh\
```

## 3. 目录约定

| 路径 | 用途 | 是否进版本库 |
|---|---|---|
| `manual/` | 手册、规格、契约 | 是 |
| `dsh/` | DSH 上游独立检出，保持干净 | 否（`.gitignore`） |
| `services/<服务名>/` | 各服务独立项目与运行环境 | 是 |
| `.local/` | 凭据、状态、素材、备份 | 否（`.gitignore`） |

各服务**各自独立**，有自己 `pyproject.toml` 与 `.runtime/`，面向后续独立 Docker 部署。
不要把一个服务的运行环境塞进另一个服务。

当前服务：

| 服务 | 职责 | 依赖 |
|---|---|---|
| `services/bilibili/` | B站账号接入（封装 bili-cli） | bili-cli 1.1.2 |
| `services/feishu/` | 飞书卡片发送、回调验证、长连接 | `lark-oapi` |
| `services/approval/` | 草稿/审核/发布任务状态机 | 无（纯 Python） |
| `services/content/` | 内容生产：生图、渲染、校验 | `pillow` |

## 4. 各服务安装与验证

每个服务都能单独跑测试，互不依赖：

```powershell
# 状态机（无外部依赖，最快）
cd services\approval
uv run --with pytest --no-project python -m pytest tests\ -q

# 飞书适配器（需要 lark-oapi）
cd services\feishu
uv run --with pytest --no-project python -m pytest tests\ -q

# 内容生产（需要 pillow）
cd services\content
uv run --with pytest --with pillow --no-project python -m pytest tests\ -q
```

预期：`services/approval` 46 项、`services/feishu` 43 项、`services/content` 30 项，全部通过。

> 用 `uv run --with ... --no-project` 是为了不污染全局环境；
> 需要锁定依赖时在各服务目录执行 `uv lock`。

## 5. 凭据管理

**所有密钥只放一处**：`.local/dsh/.credentials.yaml`（`.local/` 已 gitignore）。

当前用到的键：

| 键 | 用途 |
|---|---|
| `FEISHU_APP_ID` | 飞书自建应用 App ID |
| `FEISHU_APP_SECRET` | 飞书自建应用 App Secret |
| `FEISHU_REVIEW_CHAT_ID` | 审核群 `chat_id`（`oc_` 开头） |
| `FEISHU_REVIEWER_OPEN_ID` | 审核人 `open_id`（`ou_` 开头） |
| `FEISHU_TENANT_KEY` | 组织标识，用于回调来源校验 |
| `VOLC_API_KEY` | 火山方舟生图（豆包 Seedream） |

读取方式：脚本里用 `feishu.credentials.load_from_file()` 自动补进环境变量，
只补缺失项，不覆盖已有环境变量。

**硬规则**（来自项目工作规则）：

- 不把密钥写进文档、测试、代码、日志或模型上下文。
- 截图里出现密钥等同于泄露；`.local/` 之外任何位置出现都要立刻清理。
- 密钥一旦出现在对话或截图里，视为已暴露，应到平台轮换。

## 6. B站账号接入

B站能力通过 `bili-cli` 提供，项目根目录的 `bili.cmd` 是兼容转发入口。

```powershell
.\bili.cmd --version          # 期望输出版本号
.\bili.cmd auth status        # 期望 logged_in: true
```

首次登录需要**真人扫码**，无法代劳：

1. `.\bili.cmd auth login` → 拿到二维码图片路径或链接
2. 用 B站 App 扫码
3. `.\bili.cmd auth status --wait 120`

### 已知坑：`.local` 写不进去

`bili-cli` 的解释器在 `.local/` 下有写限制（继承的 `Everyone DENY (S,DC)`），
表现为写操作返回 `internal_error: PermissionError: ...ratelimit.tmp`，
**但平台侧其实已经成功**。

处置：把 `BILI_CLI_HOME` 指向可写位置（当前是 `services/bilibili/.runtime/bili-home`），
见 `services/bilibili/bili.cmd`。

**遇到这类报错时先核对平台证据，不要重发。**

## 7. 生图能力

用火山方舟的豆包 Seedream，走 **Agent Plan 专用入口**：

```
https://ark.cn-beijing.volces.com/api/plan/v3/images/generations
```

⚠️ 和 ModelArk 的 `/api/v3` **不是同一个入口**。用错会返回 **401**，
看起来像 key 失效，实际是路径不对。

模型名：`doubao-seedream-5-0-pro`（`-flash` 更便宜更快）。

实测限制：即使负面提示词写了 `text, letters, typography`，
模型仍可能在画面里加英文标语。**出图后必须人工检查**。

## 8. 验证清单

准备就绪的判断标准：

| 检查 | 命令 | 期望 |
|---|---|---|
| DSH 可启动 | 双击 `启动DSH.cmd` | Web 界面打开 |
| B站已登录 | `.\bili.cmd auth status` | `logged_in: true` |
| 状态机测试 | `services\approval` 跑 pytest | 全过 |
| 飞书适配器测试 | `services\feishu` 跑 pytest | 全过 |
| 飞书凭证有效 | `whoami.py --list-chats` | 列出群 |
| 长连接可收事件 | 启动 `run_listener.py` 后点卡片 | 收到 `DECISION` 日志 |

飞书这几步的具体做法见 [飞书配置指南](feishu-setup.md)。

## 9. 尚未完成

- `services/douyin/` 未创建；抖音适配器未实现。
- DSH 插件形态的业务入口未实现，当前靠脚本驱动。
- `executePublish` 只有 B站动态一条路径；视频、抖音均未接。
- 定时任务、通知回执未实现。
