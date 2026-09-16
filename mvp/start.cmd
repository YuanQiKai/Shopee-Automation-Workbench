@echo off
setlocal
cd /d "%~dp0"
echo Meeya MVP - http://127.0.0.1:8765
echo Keep this window running. Press Ctrl+C to stop.
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" server.py %*
  goto finished
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3 server.py %*
  goto finished
)
where python >nul 2>&1
if not errorlevel 1 (
  python server.py %*
  goto finished
)
echo Python 3.11 or newer is required. No pip packages are needed.
:finished
if errorlevel 1 pause
