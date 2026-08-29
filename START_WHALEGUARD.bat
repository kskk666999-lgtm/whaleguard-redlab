@echo off
setlocal
chcp 65001 >nul
title WhaleGuard AI RedLab - Start
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-whaleguard.ps1"
set "WG_EXIT=%ERRORLEVEL%"
if not "%WG_EXIT%"=="0" (
  echo.
  echo Startup failed. Review the message above, then press any key to close.
  pause >nul
)
exit /b %WG_EXIT%
