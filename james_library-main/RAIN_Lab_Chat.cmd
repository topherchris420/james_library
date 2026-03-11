@echo off
setlocal
set "REPO_ROOT=%~dp0"
cd /d "%REPO_ROOT%"

set "VENV_PY=%REPO_ROOT%.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [R.A.I.N. launcher] Local environment missing. Running installer...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%INSTALL_RAIN.ps1" -SkipPreflight
  if errorlevel 1 (
    echo [R.A.I.N. launcher] Installer failed.
    echo [R.A.I.N. launcher] Tip: run INSTALL_RAIN.cmd again or use python rain_lab.py --mode validate after fixing Python.
    pause
    exit /b 1
  )
)

if not exist "%VENV_PY%" (
  echo [R.A.I.N. launcher] Python runtime still missing at "%VENV_PY%".
  pause
  exit /b 1
)

"%VENV_PY%" "%REPO_ROOT%rain_lab.py" --mode chat --ui auto %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [R.A.I.N. launcher] Session ended with exit code %EXIT_CODE%.
  echo [R.A.I.N. launcher] Tip: run R.A.I.N. Lab Validate or python rain_lab.py --mode validate.
  pause
)
exit /b %EXIT_CODE%
