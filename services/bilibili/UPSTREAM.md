# 上游来源

- 项目：[kukemc/bili-cli](https://github.com/kukemc/bili-cli)
- 固定版本：`v1.1.2`
- Git 提交：`e603eeb86cc0c43c362d7d0a3be6327dba54c375`
- Python 包：`bili-agent==1.1.2`
- 许可证：MIT；原始许可文本位于 `upstream/LICENSE`
- 上游源码未做本地修改；本服务只在目录外增加入口和安装配置。

本目录中的 `upstream/` 是固定在 `v1.1.2` 的浅克隆源码，当前处于该 tag 对应的 detached HEAD；运行时不依赖联网获取源码。升级时先选定并记录新 tag 与 commit，再更新源码检出和独立运行环境，之后验证版本、账号读取和 DSH 调用。
