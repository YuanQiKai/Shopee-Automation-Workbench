@echo off
setlocal
call "%~dp0workbench\Start-Workbench.cmd" %*
exit /b %errorlevel%
