# B站首轮自动流程实测

日期：2026-10-26。执行主体：DSH 会话“B站自动流程演示”；账号：内卷树懒。工具：bili-cli 1.1.2；模型：当前 MiniMax-M3 路由。

## 结果

已完成“人类扫码 → DSH 检查账号 → 读取推荐 → 自主选择视频 → 获取资料 → 生成分析与未发送草稿”。本次使用上游 CLI + Skill，未新增业务插件或 MCP 封装。

| 环节 | 实际证据 |
| --- | --- |
| 登录 | `auth status` 返回 `logged_in=true`，账号名“内卷树懒” |
| 推荐 | `feed recommend --count 5` 成功；实际返回 4 条，未追加翻页 |
| 选择 | DSH 自主选择 [本地模型开发 FPS 视频](https://www.bilibili.com/video/BV1NDtm6QEdF)，简介明确提及 DSH |
| 首次聚合读取 | `video watch ... --frames 0 --comments 3 --max-chars 1800 --no-danmaku` 因创建本地 `seen.json` 被拒绝而失败 |
| 自动恢复 | DSH 查看帮助，改用 `video info`、`video subtitle --text`、`comment list --sort hot`、`video summary`、`video chapters`，均成功 |
| 可用内容 | 简介、AI 中文字幕、平台 AI 摘要和热评；章节为空；未抓取视频画面 |
| 输出 | DSH 会话中生成三个内容要点和未发送评论草稿 |
| 完整权限复验 | 用户选择完整权限后，原生会话投影为 `danger-full-access`；DSH 用 `video watch ... --frames 0 --peaks 0 --comments 3 --max-chars 1000 --no-danmaku` 一次成功，返回简介、摘要、字幕和恰好 3 条热评；本地 `seen.json` 已生成 |
| 平台副作用 | 未调用评论、私信、动态、上传、点赞、投币或关注命令；没有使用写入观看历史的 `--record` |

## 限制与学习点

- 模型回答、CLI 可运行、平台登录和业务发布是不同验收项。本轮只证明账号连接与读取分析流程，未验证投稿、审核闭环或定时运营。
- 请求数量不保证返回数量；列表应以真实结果为准。`comment list` 按页返回，实际读取多于 3 条；聚合命令的 `--comments 3` 没有适用于该子命令的同名参数。
- 首轮 `video watch` 在原沙箱配置下无法写本地已看列表。用户随后自行选择完整权限，复验已成功；助手核对时未进一步修改权限、ACL 或配置。此前的写入限制已不适用于当前会话。
- AI 字幕可能有转写错误，平台摘要可能遗漏内容。没有画面，不能声称完整观看了视频。
- DSH 首版总结对其他推荐标题、成本及显存可运行性有过度推断，已追加校正任务。作者主张与本机验证必须区分，草稿不能直接当作已审核发布稿。
- 原始工具事件保存在被忽略的 `.local/bilibili-demo-progress.json`、`.local/bilibili-demo-result.json`、`.local/bilibili-demo-final.json` 与 `.local/bilibili-watch-permission-retest.json`；平台凭据不进入公开文档。

## 第二轮只读冒烟测试

2026-10-26 追加核对：账号 `auth status` 仍为已登录，`feed inbox` 未读为 0；`feed recommend --count 5` 实际返回 4 条。选择其中一条 DeepSeek Harness 相关视频 `BV1Hgao6yEDL` 做单项接口验证：

| 检查 | 结果 |
| --- | --- |
| `video info` | 成功，返回简介、分区、统计和单 P 信息 |
| `video subtitle --text` | 成功，返回 B 站 AI 中文字幕；机器转写有明显专名错误，需结合简介校正 |
| `video summary` | 返回 `not_found`，该视频没有可用的平台 AI 总结 |
| `video watch` | 失败：写入 `.local/bili-cli/seen.json` 时 `PermissionError`；未重复调用，未修改 ACL |
| `comment post --dry-run` | 成功返回 `dry_run=true` 和预览参数；未发送评论 |
| `bili mcp --help` | 确认上游提供 stdio `mcp serve`，但仍未注册进 DSH |

当前 CLI 环境下 `Get-Acl` 显示运行目录和 `seen.json` 有继承的 Modify 权限，文件也没有只读属性；因此 EACCES 根因尚未定位。先保留单项读取接口作为绕行路径，不将 `video watch` 标注为当前稳定通过。该轮没有投稿、评论、私信或更改账号设置。

这轮证明了账号连接、推荐、视频元信息、字幕读取和评论预览可用；不代表素材制作、投稿、发布后核验或自动回复已经打通。

## 在 DSH 复现

回到浏览器中的 DSH，选择 `robot` 工作区与“B站自动流程演示”会话，查看 `pwsh` 工具调用和结果。后续可以直接输入：

> 用 bili-cli 搜索与 DSH 插件开发相关的视频，选 1 条，读取简介和可用字幕，解释哪些方法适合内卷树懒项目。只读取和生成本地草稿。

登录和命令用法见 [上手指南](bilibili-quickstart.md)。
