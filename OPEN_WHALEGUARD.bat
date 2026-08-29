@echo off
setlocal
chcp 65001 >nul
"%__APPDIR__%WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open-whaleguard.ps1"
set "WG_EXIT=%ERRORLEVEL%"
if not "%WG_EXIT%"=="0" pause
exit /b %WG_EXIT%
