# 视频生产服务端 SDD

## 1. 文档头

| 项目 | 内容 |
| --- | --- |
| 标识 / 文档版本 | SDD-BE-VP / `0.1.0-draft.1` |
| 行为基线 | 候选 `0.1.0`，未锁定 |
| 状态 | 待评审；阶段一–三已实现，阶段四（模板系统）未开工 |
| PRD / UI | [PRD-CS](../common/prd.md)、[UI-CS](../common/ui_notes.md)，均为 `0.1.0-draft.1` |
| 共享 Schema | [cyber-sloth.schema.json](../../contracts/cyber-sloth.schema.json)，候选 `0.1.0` |
| 变更依据 | [CHANGE-002](../governance.md)（视频入契约）、[CHANGE-003](../governance.md)（视觉表现改造） |
| 负责人 / 评审人 | 项目开发者 |
| 更新日期 | 2026-10-26 |
| 确认依据 | 用户 2026-10-26 指示「BC 都做一下，然后帮我先实现视觉表现形式前三个阶段」 |

### 变更与评审日志

| 文档版本 | 日期 | 阶段 / 范围 | 摘要 | 结论与依据 |
| --- | --- | --- | --- | --- |
| 0.1.0-draft.1 | 2026-10-26 | 阶段一–三 | 版式、运镜、转场、逐条出现、多姿势的配套候选契约 | 待开发者评审；自查不等于批准 |

## 2. 目标与范围

### VP-SCOPE-01 能力目标

把一份**分镜数据**（storyboard JSON）渲染成可投稿的 mp4：逐场截图、逐步合成、可选配音，并在合成阶段加入运镜与转场。

覆盖 CHANGE-003 的阶段一至阶段三。**不覆盖**：阶段四模板系统、多语言字幕、语音驱动口型、真人素材混剪。

### VP-SCOPE-02 与平台契约的边界

分镜 JSON 是**生产侧中间产物**，不是对平台的发布契约：

| 归属 | 内容 |
| --- | --- |
| 平台契约 `cyber-sloth.schema.json` | `PublicationManifest`（title/body/assets/visibility/…） |
| 生产规格（本文档） | 分镜结构、版式、运镜、转场、时长 |

因此本文档新增的字段**不需要**修改共享 Schema；改的是 `content.video.scenes.Scene`。

## 3. 渲染管线

```
storyboard.json
   ↓ ① 展开 card_reveal（一屏拆多屏）
   ↓ ② 逐场渲染 HTML → PNG（Playwright / Chromium）
   ↓ ③ 逐场生成运动片段（ffmpeg zoompan）
   ↓ ④ 串联片段（ffmpeg xfade）
   ↓ ⑤ 混入音轨（ffmpeg）
video.mp4
```

### VP-PIPE-01 渲染层可替换

`content.video.renderer.Renderer` 是协议；当前实现 `PlaywrightRenderer`。
换排版方案只替换实现，不动 ①②④⑤。

### VP-PIPE-02 浏览器来源

使用 **Playwright 自带的 Chromium**，不依赖系统浏览器——容器里没有系统浏览器。
浏览器缓存落在 `services/content/.runtime/ms-playwright/`（已 gitignore）；
容器内由 `playwright install --with-deps chromium` 安装到默认位置。

**中文字体**：容器必须安装（Debian/Ubuntu 用 `fonts-noto-cjk`），否则中文渲染成方框。

## 4. 场景模型

### VP-DATA-01 Scene 字段

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `hold_ms` | int ≥ 0 | 必填 | 该屏时长；**0 表示由配音决定**（见 VP-RULE-03） |
| `caption` | str | `""` | 底部字幕；不念则留空 |
| `card` | Card? | null | 卡片内容 |
| `title_block` | dict? | null | 大字标题（`title`/`main`/`sub`） |
| `outro` / `outro_sub` | str | `""` | 片尾主副标题，存在时覆盖字幕条 |
| `badge` | str | `""` | 左上角标，如「测试 01」 |
| `pose` | str | `""` | 立绘预设名，必须在 `assets` 中定义 |
| `layout` | enum | `card` | 版式，见 VP-DATA-02 |
| `card_reveal` | int[]? | null | 卡片逐条出现的行数进度，见 VP-RULE-04 |
| `motion` | enum? | null | 运镜，见 VP-DATA-03；null 按版式自动选 |
| `transition` | enum? | null | 转场，`fade` / `none`；null 用 `fade` |

### VP-DATA-02 版式

| `layout` | 结构 | 用途 |
| --- | --- | --- |
| `card` | 左卡片 + 右立绘 + 底字幕 | 默认，信息承载 |
| `headline` | 全屏大字，无卡片无立绘 | 强调、章节转换 |
| `closeup` | 立绘放大占右 55%，左侧单句 | 情绪、转折 |
| `center_card` | 卡片居中，无立绘 | 信息密集、清单 |

要求：**同一视频内至少使用 2 种版式**，否则退化为单调（见 VP-RULE-05）。

### VP-DATA-03 运镜

| `motion` | 效果 |
| --- | --- |
| `zoom_in` | 1.00 → 1.06，中心放大 |
| `zoom_out` | 1.06 → 1.00 |
| `pan_left` | 保持 1.05 倍，画面左移 |
| `pan_right` | 保持 1.05 倍，画面右移 |
| `none` | 静止 |

自动选择规则（`motion` 为 null 时）：`card` → `zoom_in`；`headline` → `zoom_out`；
`closeup` → `pan_right`；`center_card` → `zoom_in`。

### VP-DATA-04 转场

`fade`：相邻片段 0.30 秒交叉淡化；首屏进入、末屏退出**不加**转场。

## 5. 行为规则

### VP-RULE-01 时长不变量（最重要）

**成片总时长必须等于各屏 `hold_ms` 之和（配音模式下为剧本规划值）。**

运镜与转场都不得改变总时长：

- 运镜只是对既有画面做缩放/位移，不增删帧
- 转场靠**片段加长 + 重叠**实现：第 i 段长度 = `hold_i + d`（最后一段不加），
  串联后总长 = Σ(hold) + (n−1)·d − (n−1)·d = Σ(hold)

任何实现都必须有断言保护，防止「画面比音轨短」（历史上出现过：26.9 秒的片子只有 23.0 秒画面）。

### VP-RULE-02 静帧渲染

每一屏渲染一次到 PNG，运动由合成阶段的 ffmpeg 滤镜生成，**不逐帧截图**。
原因：逐帧截图浏览器渲染成本高一个数量级，而当前画面的变化量不需要逐帧。

### VP-RULE-03 配音决定时长

`hold_ms = max(语音时长, 手写时长) + 留白`。见 `content.video.voice.plan`。
画面不得比语音短，否则话说一半就切走。

### VP-RULE-04 卡片逐条出现

`card_reveal = [1, 2, 3]` 表示这一屏依次显示 1、2、3 行。

- 该屏被**等分**成 `len(card_reveal)` 个子屏，时长均分（余数给最后一段）
- 未到出现时机的行**保留占位但完全透明**，卡片高度不变——
  否则卡片会长高，视觉上像页面在跳
- 缺省（null）时不拆分，整卡一次出现

### VP-RULE-05 反单调约束

CHANGE-003 的问题就是「每屏一样」。以下为软约束，`Storyboard.validate()` 只提示不阻断：

| 约束 | 阈值 |
| --- | --- |
| 版式种类 | ≥ 2 种 |
| 立绘姿势种类 | ≥ 2 个（且片长 > 20 秒时） |
| 连续同版式 | ≤ 3 屏 |

## 6. 合成参数

| 参数 | 值 | 理由 |
| --- | --- | --- |
| 帧率 | 30 | B站 常见；与 xfade 兼容 |
| 编码 | H.264 / yuv420p | 兼容性最好 |
| CRF | 20 | 静帧为主，画质足够且体积小 |
| `-tune` | stillimage | 静帧码率更省 |
| 转场时长 | 0.30 s | 短到不拖节奏，长到能感知 |
| 音轨 | AAC 128k | 语音够用 |

## 7. 质量约束与验证

### VP-VERIFY-01 自动化断言

| 断言 | 方式 |
| --- | --- |
| 总时长 = Σ hold | 合成后 ffmpeg 探测，误差 ≤ 50 ms |
| 视频流时长 ≈ 容器时长 | 防止音轨撑长容器、画面却短 |
| 分镜校验无错误 | `Storyboard.validate()` 返回空 |
| 反单调提示为空 | `layout.audit()` 返回空（软约束） |
| 关键帧可抽且不落在转场 | `transition_boundaries()` 避开 ±450 ms |
| **画面确实在动** | `scripts/measure_motion.py` 测量帧间差异 |

### VP-VERIFY-03 运动量基线

「画面不动」是可以用数字量化的，因此把它做成可回归的指标：

| 版本 | 非转场中位数差异 | 几乎静止占比 |
| --- | --- | --- |
| 静帧基线（无运镜、硬切） | 0.004 | **98.7%** |
| 运镜 + 淡入淡出（当前） | 2.63 | **13.7%** |

判定：静止占比 < 40% 视为「画面在动」。低于此值说明运镜没生效，
或分镜仍是纯静帧——回到本文档第 4 节检查 `motion` 与版式。

测量命令：

```bash
uv run --with pillow --no-project python scripts/measure_motion.py --video .runtime/test01.mp4
```

### VP-VERIFY-02 人工验收

视觉观感无法自动断言，必须人看。验收清单：

1. 运镜是否能感知但不晕
2. 转场是否自然、无闪白
3. 卡片逐条出现是否与口播节奏对得上
4. 不同版式之间是否有明显区别
5. 立绘姿势变化是否自然（同一角色的辨识度）
6. 运镜是否裁掉了边缘内容（角标/声明距边需大于裁切量）

## 8. 已知限制

| 限制 | 说明 |
| --- | --- |
| 立绘姿势数量 | 3 个（main / point / sleepy）；更多姿势需重新生成并保持角色一致性 |
| 角色一致性 | 新姿势由生图模型生成，可能与主立绘有细微差异，需人工比对 |
| 无口型同步 | 配音与画面无口型对应，字幕承担信息传递 |
| 逐帧动画 | 不支持；只有运镜与转场 |
| 字幕 | 整句显示，不做逐字动画 |
| 模板系统 | 未实现（阶段四）；当前所有视频共用一套版式集合 |

## 9. 与其它模块的接口

| 上游 | 接口 |
| --- | --- |
| `services/approval` | 视频 manifest 的 `video` 字段指向本模块产出的 mp4 |
| `services/feishu` | 关键帧由 `extract_keyframes()` 产出，作为审核卡片预览 |
| `scripts/render_video.py` | CLI 入口，输出一行 JSON |
