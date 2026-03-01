@echo off
setlocal
set "REPO_ROOT=%~dp0"
cd /d "%REPO_ROOT%"

set "VENV_PY=%REPO_ROOT%.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [R.A.I.N. launcher] Local environment missing. Running installer...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%INSTALL_RAIN.ps1"
  if errorlevel 1 (
    echo [R.A.I.N. launcher] Installer failed.
    pause
    exit /b 1
  )
)

if not exist "%VENV_PY%" (
  echo [R.A.I.N. launcher] Python runtime still missing at "%VENV_PY%".
  pause
  exit /b 1
)

"%VENV_PY%" "%REPO_ROOT%rain_lab.py" --mode first-run %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [R.A.I.N. launcher] First-run checks completed.
) else (
  echo [R.A.I.N. launcher] First-run checks failed with exit code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
