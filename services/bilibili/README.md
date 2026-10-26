# Bilibili 服务

`services/bilibili/` 是 B 站服务的独立项目根目录。服务源码、版本信息、安装脚本和入口都在这里；本地运行环境也由本服务单独管理。它不依赖共享的 `.local/uv-tools`。

## 目录

```text
services/bilibili/
├─ upstream/       # bili-cli v1.1.2 上游源码，未修改
├─ .runtime/       # uv tool 环境和可执行文件，生成目录，不提交
├─ bili.cmd        # 本服务入口；每次调用启动独立 CLI 进程
├─ install.ps1     # 从本地固定版本源码安装本服务运行环境
├─ UPSTREAM.md     # 上游版本、提交和许可证
└─ README.md
```

账号凭据和本地操作记录继续保存在项目根目录 `.local/bili-cli/`，由 `BILI_CLI_HOME` 指定。它们是私有运行数据，不属于服务源码或 Docker 镜像。

## 安装与运行

在项目根目录执行：

```powershell
.\services\bilibili\install.ps1
.\services\bilibili\bili.cmd --version
.\services\bilibili\bili.cmd auth status
```

兼容入口仍可用：

```powershell
.\bili.cmd auth status
```

DSH 项目级 Skill 目前在根目录 `.agents/skills/bili-cli/`；它是 Agent 的使用说明，不是服务实现。当前 DSH 仍通过 CLI + Skill 调用。上游 `bili mcp serve` 提供 stdio MCP，但尚未注册到 DSH，也没有 Streamable HTTP 服务。

## 独立运行与容器边界

每次 `bili.cmd` 调用都会启动本服务自己的 CLI 进程，并从本服务 `.runtime/` 加载依赖，不读取其他服务的 Python 环境。未来 Docker 镜像应从本目录构建，只复制本服务源码和锁定的构建输入；账号数据应通过独立卷或 Secret 注入。

当前版本仍是命令行服务适配器，不是常驻 HTTP 服务。若要让独立容器中的 DSH 通过 Streamable HTTP 调用，需要在本服务内增加 HTTP MCP 传输入口并单独验收；不能把现有 stdio 支持标记成 HTTP 已就绪。

源码细节从 [`upstream/src/bili_cli/`](upstream/src/bili_cli/) 阅读；版本与许可证见 [UPSTREAM.md](UPSTREAM.md)。
