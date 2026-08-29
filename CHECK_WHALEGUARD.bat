@echo off
setlocal
chcp 65001 >nul
title WhaleGuard AI RedLab - Doctor
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\doctor.ps1"
set "WG_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %WG_EXIT%
