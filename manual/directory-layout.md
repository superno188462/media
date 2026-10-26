# 目录结构与迁移约定

日期：2026-10-26。用户要求按手册、DSH、服务分目录，并明确每个服务目录包含自身源码、运行环境和独立进程部署边界；本次整理 B 站服务模块，不改变业务行为契约。

| 目录 | 职责 |
| --- | --- |
| `manual/` | 统一手册入口，`docs/` 保存使用说明和实测，`specs/` 保存 PRD/UI/SDD，`contracts/` 保存声明式 Schema 和示例 |
| `dsh/` | 官方 DSH 独立 Git 仓库，保留上游锁文件、源码和构建产物；按固定版本准备，不混入自研服务 |
| `services/<模块名>/` | 每个服务的独立项目根目录：源码、依赖/锁文件、配置模板、启动入口和 Docker 构建文件均归属该服务；运行环境在服务目录内隔离 |
| `scripts/` | 项目统一启动与维护脚本 |
| `.agents/skills/` | 可被 DSH 和当前项目发现的项目级技能 |
| `.local/` | 被 Git 忽略的本机私有状态：账号凭据、DSH 会话、缓存、日志和备份；不放服务源码或服务依赖环境 |

## 当前已有的模块

`services/bilibili/` 是 B 站服务的项目根目录。上游 `bili-cli` 固定版本源码位于 `upstream/`，服务专属 uv tool 环境位于被忽略的 `.runtime/`，入口为 `bili.cmd`。账号凭据与操作记录保存在根目录 `.local/bili-cli/`，避免混入源码或镜像。

当前服务通过 CLI 命令作为独立进程运行，DSH 使用 CLI + Skill；这还不是长驻的 Streamable HTTP 微服务。上游 MCP 入口是 stdio。后续若要容器间通过 HTTP MCP 通信，应在该服务目录内实现或配置 HTTP 传输入口，再由 DSH 连接；不能把 stdio 能力误记成已有 HTTP 服务。

抖音、飞书、记忆等微服务后续实现时，分别放到 `services/douyin/`、`services/feishu/`、`services/memory/`。这些是放置约定，当前没有为未实现服务创建空项目。自建 DSH 插件可单独放 `plugins/<插件名>/`，不修改 `dsh/` 上游源码。

自建 Python 服务使用各自的 `pyproject.toml`、`uv.lock` 和隔离虚拟环境。第三方服务源码仍归入对应服务目录，并按上游支持的工具链安装到该服务专属环境；Docker 镜像只复制服务代码和明确需要的构建输入，不复制本机账号数据。

## 本次路径映射

| 旧路径（相对项目根目录） | 新路径 |
| --- | --- |
| `docs/` | `manual/docs/` |
| `specs/` | `manual/specs/` |
| `contracts/` | `manual/contracts/` |
| 原根目录完整 README | `manual/README.md`，根目录另保留简短入口 |
| `vendor/deepseek-harness/` | `dsh/` |
| 原 `bili.cmd` 的实际包装逻辑 | `services/bilibili/bili.cmd`，根目录保留转发入口 |

`manual/specs/` 与 `manual/contracts/` 分别是原规格目录与契约目录的等价映射，字段与行为基线保持原版本。`.local/` 和工作区根路径 `D:\github\robot` 保持原处，因此 B站账号、DSH 会话和工作区身份沿用既有数据。

## 启动与恢复

根目录 `启动DSH.cmd` 仍调用 `scripts/start-dsh.ps1`，后者进入新的 `dsh/` 源码目录。移动上游仓库后，需在 `dsh/` 重新执行官方 `corepack pnpm install --frozen-lockfile`，使依赖链接指向当前位置；构建缺失时执行 `corepack pnpm run build`。

服务已运行时双击根目录 `打开DSH.cmd`，由 `scripts/open-dsh.ps1` 使用本机认证入口打开桌面浏览器；避免只输入裸地址出现认证提示，或重复启动服务导致端口冲突。

运行记录保存在 `manual/docs/`；本机迁移前路径映射与凭据指纹保存在被忽略的 `.local/directory-migration.json`。凭据本身不复制进手册或源码目录。

## 迁移后实测

- 官方 `pnpm install --frozen-lockfile` 成功，依赖链接指向 `dsh/`，1725 条锁文件条目通过供应链校验。离线尝试因缺少包元数据未完成，随后使用常规联网安装完成；未修改上游锁文件。
- DSH 在新路径返回版本 `0.2.1-rc.3`，上游 `git status --porcelain` 为空。
- 后台服务重启后认证入口 HTTP 200，原“B站自动流程演示”会话、工作区路径和用户选择的完整权限均保留。
- DSH 实际调用新模块入口查询账号，返回已登录“内卷树懒”；调用根目录兼容入口返回 bili-cli `1.1.2`。
- 凭据文件 SHA-256 与迁移前一致。原始验证事件位于 `.local/directory-migration-dsh-check.json`。
