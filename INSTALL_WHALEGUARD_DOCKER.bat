@echo off
setlocal
cd /d "%~dp0"
"%__APPDIR__%WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup-whaleguard-docker.ps1"
set "WG_EXIT=%ERRORLEVEL%"
if not "%WG_EXIT%"=="0" (
  echo.
  if "%WG_EXIT%"=="3010" (
    echo Windows must be restarted once. Setup will resume after sign-in.
  ) else if "%WG_EXIT%"=="194" (
    echo Windows must be restarted once. Setup will resume after sign-in.
  ) else (
    echo WhaleGuard Docker setup failed with exit code %WG_EXIT%.
  )
  echo See .local\setup-logs for details.
  pause
)
exit /b %WG_EXIT%
