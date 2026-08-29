@echo off
setlocal
chcp 65001 >nul
title WhaleGuard AI RedLab - Reset Demo
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\reset-demo.ps1"
set "WG_EXIT=%ERRORLEVEL%"
if not "%WG_EXIT%"=="0" pause
exit /b %WG_EXIT%
