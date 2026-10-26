<#
.SYNOPSIS
Start the pinned DSH checkout with a project-local data directory.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 3080,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dshRoot = Join-Path $projectRoot 'dsh'
$runtimeHome = Join-Path $projectRoot '.local\dsh'
$previousDshHome = [Environment]::GetEnvironmentVariable('DSH_HOME', 'Process')
$previousBiliHome = [Environment]::GetEnvironmentVariable('BILI_CLI_HOME', 'Process')
$previousPythonEncoding = [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
$previousPath = $env:PATH

if (-not (Test-Path -LiteralPath (Join-Path $dshRoot 'apps\cli\lib\bin.js'))) {
    throw 'DSH is not built. Run corepack pnpm install --frozen-lockfile and corepack pnpm run build inside dsh.'
}
if (-not (Get-Command corepack.cmd -ErrorAction SilentlyContinue)) {
    throw 'corepack.cmd was not found. Install a Node.js version supported by DSH.'
}

New-Item -ItemType Directory -Path $runtimeHome -Force | Out-Null
try {
    $env:DSH_HOME = $runtimeHome
    $env:BILI_CLI_HOME = Join-Path $projectRoot '.local\bili-cli'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PATH = (Join-Path $projectRoot '.local\bin') + ';' + $previousPath
    Push-Location -LiteralPath $dshRoot
    try {
        $launchArgs = @('pnpm', 'dsh', 'web', '--host', '127.0.0.1', '--port', [string]$Port)
        if ($NoOpen) { $launchArgs += '--no-open' }
        Write-Host "Cyber Sloth DSH: http://127.0.0.1:$Port"
        Write-Host "Runtime data: $runtimeHome"
        & corepack.cmd @launchArgs
        if ($LASTEXITCODE -ne 0) { throw "DSH exited with code $LASTEXITCODE" }
    }
    finally { Pop-Location }
}
finally {
    [Environment]::SetEnvironmentVariable('DSH_HOME', $previousDshHome, 'Process')
    [Environment]::SetEnvironmentVariable('BILI_CLI_HOME', $previousBiliHome, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONIOENCODING', $previousPythonEncoding, 'Process')
    $env:PATH = $previousPath
}
