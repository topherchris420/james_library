@echo off
setlocal
set "REPO_ROOT=%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%INSTALL_RAIN.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [installer] Failed with exit code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
