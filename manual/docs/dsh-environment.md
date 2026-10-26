# DSH 本机环境与迁移记录

日期：2026-10-26。范围：按用户要求迁入当前项目、升级并清理旧扩展；不包含内卷树懒业务插件的实现或真实发布。

## 当前环境

| 项目 | 已核实结果 |
| --- | --- |
| 源码目录 | `D:\github\robot\dsh` |
| 上游 | [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) |
| 固定版本 | 官方源码标签 `dsh-v0.2.1-rc.3` |
| Commit | `1f81c047fc48fa190a683e469daa699857e9afe8` |
| Node.js | `24.19.0` |
| 构建包管理器 | Corepack 按上游 packageManager 使用 `pnpm 11.28.5` |
| 数据目录 | `D:\github\robot\.local\dsh`，由启动脚本设置进程级 `DSH_HOME` |
| 运行 profile | `web`；官方 `dsh-base`、`dsh-web-app` 两个组合包 |
| 额外安装依赖 | profile 的 `dependencies` 为空，没有安装社区运营或美化插件 |
| 业务状态 | 飞书、抖音尚未接入；已安装独立 bili-cli 与项目 Skill，B站账号“内卷树懒”已扫码登录 |

调查时 npm `latest` 指向 `0.2.1-rc.2`，官方最新源码标签为 `0.2.1-rc.3`。本次采用后者，从源码构建；不是声称 npm 已发布同一版本。上游仍为预览版。源码固定在标签对应提交，未自动跟随 master。

上游是独立 Git 仓库。主项目通过 `.gitignore` 排除这份检出和 `.local/`，复现依据为本文件中的远程、标签、commit 和上游锁文件；本次未创建主项目 Git 仓库或子模块。

## 启动

双击项目根目录的 [启动DSH.cmd](../../启动DSH.cmd)，会在本机 `127.0.0.1:3080` 启动并打开官方 Web 界面。关闭服务可在启动窗口按 Ctrl+C。

也可以在当前项目 PowerShell 中运行：

```powershell
.\scripts\start-dsh.ps1
# 不自动打开浏览器，或换端口：
.\scripts\start-dsh.ps1 -NoOpen -Port 3081
```

认证入口使用 DSH 当次打印的完整地址；裸地址可能返回“需要认证”，这是访问控制生效。不要把带 token 的地址放进文档或提交到仓库。端口被其他实例占用时，先结束旧启动窗口或换端口。

服务已运行时，双击根目录 [打开DSH.cmd](../../打开DSH.cmd) 可从本机日志获取当前认证入口并打开默认桌面浏览器。应用内浏览器与桌面浏览器不共享 Cookie，因此另一浏览器可用并不意味着新浏览器已经认证。

首次打开后在工作区选择 `D:\github\robot`。宿主源码位于 `dsh/`，业务规格位于 `manual/`，其他服务或工具接入模块位于 `services/<模块名>/`。

## 已迁移与未迁移

- 从原 `C:\Users\JZK\.dsh` 复制模型设置和凭据到项目私有数据目录；未输出内容。新宿主已执行旧 `settings.yaml` 导入，并保留 `settings.yaml.imported`。
- 原用户级 DSH 数据目录未删除，旧会话、附件与凭据仍在原处；它不作为当前项目的运行目录。
- 旧项目额外加入的 `dsh-client-ui-voice` 及其 app-boot、Web bundle、tsconfig 修改均未带入新环境。官方依赖按上游锁文件保留，没有从源码中硬删官方模块。
- 原项目已从 `D:\azkjiao\git-fun\deepseek-harness` 移到 `D:\github\robot\.local\backups\deepseek-harness-0.1.0-rc.5-20261026`。原路径已不存在；Git 历史、5 个已修改文件、未跟踪语音插件与操作记录仍在备份里。
- 备份不参与新环境加载。旧目录内原先的绝对链接可能需要恢复原路径或重装依赖才能运行，因此“文件已备份”不等于备份在新位置可直接启动。

## 实际验证

| 检查 | 结果及边界 |
| --- | --- |
| 官方标签与 commit | 匹配 |
| `pnpm install --frozen-lockfile` | 成功，保留上游锁文件；首次安装由现有 pnpm 11.25.0 完成 |
| `corepack pnpm run build` | 成功，使用 11.28.5；9 项全部通过，含 Host/Client 编译、聚合类型检查和 Web 构建 |
| `corepack pnpm dsh --version` | `0.2.1-rc.3` |
| 项目启动脚本 | Windows PowerShell 5 语法检查通过；CMD 包装入口实际启动成功 |
| 本机 Web 访问 | 认证入口、建立会话后的首页及前端 JavaScript 均 HTTP 200；裸地址要求认证 |
| 新源码修改 | `git status --porcelain` 为空 |
| 运营工具与平台账号 | bili-cli 1.1.2 与项目 Skill 已安装，B站扫码登录成功；未发布内容 |
| 模型推理 | 通过 DSH 会话实际请求 MiniMax-M3，收到成功回复 |
| DSH 工具执行 | 修复项目根目录权限后，DSH 的 pwsh 实际执行 `.\bili.cmd --version` 返回 1.1.2，工具结果无错误 |
| B站聚合读取复验 | 用户选择完整权限后，会话投影确认 `danger-full-access`；DSH 实际执行 `video watch` 成功，`seen.json` 正常写入 |

安装时出现首次构建前 CLI bin 尚不存在的警告，随后完整构建和 CLI 启动成功。未为这些警告修改上游源码或依赖锁文件。

首次迁移检查用的临时实例已停止；后续 B站演示已在 `127.0.0.1:3080` 启动后台实例，并在应用内浏览器打开。正在运行时不要重复启动同一端口。进程信息与日志在 `.local/` 中；停止后可用项目启动入口重新启动。

B站连接方法、演示边界和 Windows 工作区权限修复见 [上手指南](bilibili-quickstart.md)。认证 token、平台凭据只保存在被忽略的本机数据目录中。

## 复现与回退

重新准备源码时，使用上述官方仓库与标签，并核对 commit。在检出目录依次运行 `corepack pnpm install --frozen-lockfile`、`corepack pnpm run build`，再回到当前项目使用启动脚本。

需要回退旧版时，先停止新版服务，再把备份目录恢复到原路径，重新检查原依赖链接，并使用原用户级 DSH 数据目录。不要把新版数据文件直接覆盖到旧版会话存储中。
