@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-workbench.ps1" %*
set "taskExit=%errorlevel%"
if not "%taskExit%"=="0" pause
exit /b %taskExit%
