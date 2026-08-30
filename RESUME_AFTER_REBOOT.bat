@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.local\system-upgrade-resume-state.json" (
  "%__APPDIR__%WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\resume-after-system-upgrade.ps1" -AutoResume
) else (
  "%__APPDIR__%WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\resume-whaleguard-docker-setup.ps1"
)
set "WG_EXIT=%ERRORLEVEL%"
if not "%WG_EXIT%"=="0" (
  echo.
  echo WhaleGuard Docker setup did not complete. See .local\setup-logs.
  pause
)
exit /b %WG_EXIT%
