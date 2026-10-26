<#
.SYNOPSIS
Open the running local DSH in the default desktop browser with authentication.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$logPath = Join-Path $projectRoot '.local\logs\dsh.stdout.log'
if (-not (Test-Path -LiteralPath $logPath)) {
    throw 'No DSH startup log found. Start DSH with the project launcher first.'
}

$startupLog = Get-Content -LiteralPath $logPath -Raw -Encoding UTF8
$entryMatches = [regex]::Matches($startupLog, 'http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_-]+')
if ($entryMatches.Count -eq 0) {
    throw 'No authentication entry found. Wait for DSH startup to finish.'
}
$entryUrl = $entryMatches[$entryMatches.Count - 1].Value
$entryUri = [uri]$entryUrl
$tcpClient = New-Object System.Net.Sockets.TcpClient
try {
    $connectTask = $tcpClient.ConnectAsync($entryUri.Host, $entryUri.Port)
    if (-not $connectTask.Wait(2000) -or -not $tcpClient.Connected) {
        throw 'DSH is not listening. Start DSH with the project launcher first.'
    }
}
catch {
    throw 'DSH is not listening. Start DSH with the project launcher first.'
}
finally { $tcpClient.Dispose() }

try { Start-Process -FilePath $entryUrl -ErrorAction Stop }
catch { throw 'Could not open the default desktop browser.' }
Write-Host 'Opened authenticated DSH entry in the default desktop browser.'
