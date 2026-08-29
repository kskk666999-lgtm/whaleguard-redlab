@echo off
setlocal
chcp 65001 >nul
title WhaleGuard AI RedLab - Doctor
"%__APPDIR__%WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\doctor.ps1"
set "WG_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %WG_EXIT%
