param(
    [string]$Model = "qwen2.5-7b-instruct",
    [string]$BaseUrl = "http://127.0.0.1:1234/v1"
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "[1/4] Checking Python..."
try {
    python --version | Out-Null
} catch {
    throw "Python was not found on PATH."
}

Write-Host "[2/4] Bootstrapping local environment (.venv, dependencies, embedded ZeroClaw when available)..."
python bootstrap_local.py --skip-preflight

$pythonExe = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment python not found at $pythonExe"
}

Write-Host "[3/4] Setting LM Studio defaults for this shell..."
$env:LM_STUDIO_BASE_URL = $BaseUrl
$env:LM_STUDIO_MODEL = $Model

Write-Host "[4/4] Running health snapshot..."
try {
    & $pythonExe rain_lab.py --mode health
} catch {
    Write-Host "Health snapshot returned non-zero status. Continue after starting LM Studio."
}

@"

Quickstart complete.

Canonical next steps:
1) Start LM Studio and load a model.
2) Validate the full stack:
   .\.venv\Scripts\python.exe rain_lab.py --mode validate
3) Run guided first-run:
   .\.venv\Scripts\python.exe rain_lab.py --mode first-run
4) Optional: validate embedded ZeroClaw runtime directly:
   .\.venv\Scripts\python.exe rain_lab.py --mode status
   .\.venv\Scripts\python.exe rain_lab.py --mode models
5) Start chat:
   .\.venv\Scripts\python.exe rain_lab.py --mode chat --ui auto --topic "hello from LM Studio"

"@ | Write-Host
