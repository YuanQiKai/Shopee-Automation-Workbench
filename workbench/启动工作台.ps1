param([switch]$NoBrowser)
& (Join-Path $PSScriptRoot 'start-workbench.ps1') -NoBrowser:$NoBrowser
exit $LASTEXITCODE
