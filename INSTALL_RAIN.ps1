param(
    [string]$Python = "python",
    [switch]$NoDev,
    [switch]$SkipPreflight,
    [switch]$RecreateVenv
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "R.A.I.N. Lab Local Installer" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

$argsList = @("bootstrap_local.py")
if ($NoDev) { $argsList += "--no-dev" }
if ($SkipPreflight) { $argsList += "--skip-preflight" }
if ($RecreateVenv) { $argsList += "--recreate-venv" }

Write-Host "[installer] Running: $Python $($argsList -join ' ')" -ForegroundColor Yellow
& $Python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "Installer failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "[installer] Success." -ForegroundColor Green
Write-Host "[installer] Next: python rain_lab.py --mode chat --topic `"your topic`"" -ForegroundColor Green
