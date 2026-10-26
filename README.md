# 内卷树懒

基于 DeepSeek Harness（DSH）的 AI 创作者学习项目。先读 [项目手册](manual/README.md)，使用方法见 [DSH 与 B站上手指南](manual/docs/bilibili-quickstart.md)。

```text
robot/
├─ manual/             # 手册、设计规格、共享契约、实测记录
├─ dsh/                # 官方 DSH 独立源码仓库
├─ services/           # 其他服务与工具接入模块，各自独立目录
│  └─ bilibili/        # B站服务源码、独立运行环境入口与说明
├─ scripts/            # 项目启动与维护脚本
├─ .agents/skills/     # 项目级技能
├─ .local/             # 本机私有数据：账号凭据、DSH 会话、日志与备份
├─ 启动DSH.cmd         # 一键启动 DSH
├─ 打开DSH.cmd         # 已运行时，用认证入口打开桌面浏览器
└─ bili.cmd            # B站命令兼容入口
```

双击 [启动DSH.cmd](启动DSH.cmd) 启动；服务已经运行时双击 [打开DSH.cmd](打开DSH.cmd)，在桌面浏览器完成认证并打开界面。B站命令仍可在根目录运行 `.\bili.cmd auth status`。DSH `0.2.1-rc.3` 和 bili-cli `1.1.2` 已验证；B站账号读取和评论预览已实测，`video watch` 当前复测遇到本地 `seen.json` 写权限错误，详见[测试记录](manual/docs/bilibili-demo-result.md)。抖音投稿与飞书审核业务仍处于规格草案阶段。

[目录与迁移说明](manual/directory-layout.md) · [各服务说明](services/README.md) · [B站源码与运行说明](services/bilibili/README.md) · [B站实测记录](manual/docs/bilibili-demo-result.md)
