# 拉取固定版本的 bili-cli 上游源码。
#
# 上游是独立仓库（见 UPSTREAM.md），不纳入本项目版本库：
# 直接提交会变成没有 .gitmodules 的空子模块指针，克隆者拿到空目录。
# 这里按记录的 commit 检出，保证可复现。

$ErrorActionPreference = 'Stop'

$repo = 'https://github.com/kukemc/bili-cli.git'
$commit = 'e603eeb86cc0c43c362d7d0a3be6327dba54c375'  # v1.1.2
$upstream = Join-Path $PSScriptRoot 'upstream'

if (Test-Path (Join-Path $upstream 'pyproject.toml')) {
    Write-Host "上游源码已存在，跳过：$upstream"
} else {
    if (Test-Path $upstream) { Remove-Item $upstream -Recurse -Force }
    Write-Host "克隆 $repo"
    git clone $repo $upstream
    if ($LASTEXITCODE -ne 0) { throw "git clone 失败" }
}

Push-Location $upstream
try {
    $head = (git rev-parse HEAD 2>$null)
    if ($head -ne $commit) {
        Write-Host "检出 $commit（v1.1.2）"
        git checkout --force $commit
        if ($LASTEXITCODE -ne 0) { throw "git checkout $commit 失败" }
    }
} finally {
    Pop-Location
}

Write-Host "完成。接下来运行："
Write-Host "  pwsh -File `"$(Join-Path $PSScriptRoot 'install.ps1')`""
