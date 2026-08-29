@echo off
setlocal
chcp 65001 >nul
title WhaleGuard AI RedLab - Stop
"%__APPDIR__%WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-whaleguard.ps1"
set "WG_EXIT=%ERRORLEVEL%"
if not "%WG_EXIT%"=="0" pause
exit /b %WG_EXIT%
