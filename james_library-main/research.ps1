# research.ps1 - Vers3Dynamics Research Launcher
# Bridges ZeroClaw (Rust) with James Library (Python) for acoustic physics research

param(
    [Parameter(Mandatory=$true)]
    [string]$Topic
)

$ErrorActionPreference = "Stop"

# =============================================================================
# Path Configuration
# =============================================================================

# Try to find Miniconda Python, fallback to system python
$MinicondaPath = "$env:USERPROFILE\miniconda3\python.exe"
$PythonPath = $null

if (Test-Path $MinicondaPath) {
    $PythonPath = $MinicondaPath
    Write-Host "[RESEARCH] Found Miniconda at: $MinicondaPath" -ForegroundColor Green
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonPath = (Get-Command python).Source
    Write-Host "[RESEARCH] Using system Python: $PythonPath" -ForegroundColor Yellow
}
else {
    Write-Error "Python not found. Please install Miniconda or add Python to PATH."
    exit 1
}

# Find rain_lab.py - check multiple possible locations
$PossiblePaths = @(
    "$PSScriptRoot\rain_lab.py",
    "$PSScriptRoot\james_library\rain_lab.py",
    "$env:USERPROFILE\Downloads\files\rain_lab.py",
    "$PSScriptRoot\..\james_library\rain_lab.py"
)

$RainLabPath = $null
foreach ($path in $PossiblePaths) {
    $resolvedPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($path)
    if (Test-Path $resolvedPath) {
        $RainLabPath = $resolvedPath
        break
    }
}

if (-not $RainLabPath) {
    Write-Error "rain_lab.py not found. Searched in:`n  - $PSScriptRoot`n  - $PSScriptRoot\james_library`n  - $env:USERPROFILE\Downloads\files"
    exit 1
}

Write-Host "[RESEARCH] Found rain_lab.py at: $RainLabPath" -ForegroundColor Green
Write-Host "[RESEARCH] Starting research on: $Topic" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# =============================================================================
# Execution
# =============================================================================

# Pass through environment variables for shell compatibility
$env:PYTHONUNBUFFERED = "1"

# Execute rain_lab.py in RLM mode (Recursive Lab Meeting)
# Pipe stdout and stderr directly for real-time analysis
& $PythonPath $RainLabPath --mode rlm --topic $Topic 2>&1 | ForEach-Object {
    $_
}

$exitCode = $LASTEXITCODE

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "[RESEARCH] Completed with exit code: $exitCode" -ForegroundColor $(if ($exitCode -eq 0) { "Green" } else { "Red" })

exit $exitCode
