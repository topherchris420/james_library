param(
    [string]$Model = "qwen2.5-7b-instruct",
    [string]$BaseUrl = "http://127.0.0.1:1234/v1"
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "[1/5] Checking Python..."
try {
    python --version | Out-Null
} catch {
    throw "Python was not found on PATH."
}

Write-Host "[2/5] Creating virtual environment (.venv)..."
python -m venv .venv

$pythonExe = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment python not found at $pythonExe"
}

Write-Host "[3/5] Installing dependencies..."
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r requirements.txt

Write-Host "[4/5] Setting LM Studio defaults for this shell..."
$env:LM_STUDIO_BASE_URL = $BaseUrl
$env:LM_STUDIO_MODEL = $Model

Write-Host "[5/5] Running health check..."
try {
    & $pythonExe rain_health_check.py
} catch {
    Write-Host "Health check returned non-zero status. Continue after starting LM Studio."
}

@"

Quickstart complete.

Next steps:
1) Start LM Studio and load a model.
2) Run preflight:
   .\.venv\Scripts\python.exe rain_lab.py --mode preflight
3) Start chat:
   .\.venv\Scripts\python.exe rain_lab.py --mode chat --topic "hello from LM Studio"

"@ | Write-Host
