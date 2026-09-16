param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
$taskLogs = Join-Path $taskRoot 'data/logs'
New-Item -ItemType Directory -Force -Path $taskLogs | Out-Null
if (-not (Test-Path -LiteralPath $taskPython)) {
    Write-Host 'Local Python is missing. Please restore the workbench runtime.'
    exit 1
}
$taskStartLog = Join-Path $taskLogs 'startup.log'
Add-Content -LiteralPath $taskStartLog -Value ("`r`n--- Launch " + (Get-Date -Format s) + ' ---') -Encoding UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$OutputEncoding = [Console]::OutputEncoding
& $taskPython -X utf8 (Join-Path $taskRoot 'scripts/start_local.py') 2>&1 |
    Tee-Object -FilePath (Join-Path $taskLogs 'startup-latest.log')
$taskExit = $LASTEXITCODE
Get-Content -LiteralPath (Join-Path $taskLogs 'startup-latest.log') |
    Add-Content -LiteralPath $taskStartLog -Encoding UTF8
if ($taskExit -ne 0) {
    Write-Host 'Startup failed. Details: workbench/data/logs/startup-latest.log'
    exit $taskExit
}
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:3010' }
exit 0
