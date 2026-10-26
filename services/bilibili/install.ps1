$ErrorActionPreference = 'Stop'

$serviceRoot = $PSScriptRoot
$upstreamRoot = Join-Path $serviceRoot 'upstream'
$runtimeRoot = Join-Path $serviceRoot '.runtime'
$uvToolDir = Join-Path $runtimeRoot 'uv-tools'
$uvToolBinDir = Join-Path $runtimeRoot 'bin'

if (-not (Test-Path (Join-Path $upstreamRoot 'pyproject.toml'))) {
    throw "Pinned bili-cli source is missing: $upstreamRoot"
}

$env:UV_TOOL_DIR = $uvToolDir
$env:UV_TOOL_BIN_DIR = $uvToolBinDir

uv tool install --force --python 3.12 --with 'mcp>=2.3' --directory $upstreamRoot .
if ($LASTEXITCODE -ne 0) {
    throw "uv tool install failed with exit code $LASTEXITCODE"
}

$bili = Join-Path $uvToolBinDir 'bili.exe'
if (-not (Test-Path $bili)) {
    throw "Bilibili CLI was not installed at the service-local path: $bili"
}

& $bili --version
if ($LASTEXITCODE -ne 0) {
    throw "Installed Bilibili CLI returned exit code $LASTEXITCODE"
}
