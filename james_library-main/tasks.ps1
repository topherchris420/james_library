# Vers3Dynamics R.A.I.N. Lab — Windows Development Commands
# Usage: .\tasks.ps1 <command>
#
# Run `.\tasks.ps1 help` for a full list of commands.

param(
    [Parameter(Position=0)]
    [string]$Command = "help"
)

$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$Cargo  = if ($env:CARGO)  { $env:CARGO }  else { "cargo" }

function Show-Help {
    Write-Host ""
    Write-Host "  R.A.I.N. Lab Task Runner (Windows)" -ForegroundColor Cyan
    Write-Host "  ===================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  install          " -NoNewline -ForegroundColor Green; Write-Host "Install core Python dependencies"
    Write-Host "  install-all      " -NoNewline -ForegroundColor Green; Write-Host "Install all Python dependencies (core + optional extras)"
    Write-Host "  install-dev      " -NoNewline -ForegroundColor Green; Write-Host "Install dev dependencies (pytest, ruff, coverage)"
    Write-Host "  lint             " -NoNewline -ForegroundColor Green; Write-Host "Run all linters (Python + Rust)"
    Write-Host "  lint-py          " -NoNewline -ForegroundColor Green; Write-Host "Lint Python with ruff"
    Write-Host "  lint-rs          " -NoNewline -ForegroundColor Green; Write-Host "Lint Rust with clippy"
    Write-Host "  fmt              " -NoNewline -ForegroundColor Green; Write-Host "Format all code (ruff + cargo fmt)"
    Write-Host "  test             " -NoNewline -ForegroundColor Green; Write-Host "Run all tests (Python + Rust)"
    Write-Host "  test-py          " -NoNewline -ForegroundColor Green; Write-Host "Run Python tests"
    Write-Host "  test-rs          " -NoNewline -ForegroundColor Green; Write-Host "Run Rust tests"
    Write-Host "  build            " -NoNewline -ForegroundColor Green; Write-Host "Build Rust binary (release)"
    Write-Host "  run              " -NoNewline -ForegroundColor Green; Write-Host "Launch R.A.I.N. Lab chat mode"
    Write-Host "  preflight        " -NoNewline -ForegroundColor Green; Write-Host "Run environment preflight checks"
    Write-Host "  health           " -NoNewline -ForegroundColor Green; Write-Host "Run launcher-native health snapshot"
    Write-Host "  validate         " -NoNewline -ForegroundColor Green; Write-Host "Run full launcher-native readiness validation"
    Write-Host "  first-run        " -NoNewline -ForegroundColor Green; Write-Host "Run guided first-run onboarding"
    Write-Host "  check            " -NoNewline -ForegroundColor Green; Write-Host "Full quality gate (lint + test)"
    Write-Host "  clean            " -NoNewline -ForegroundColor Green; Write-Host "Remove build artifacts and caches"
    Write-Host ""
}

function Invoke-Install      { & $Python -m pip install -r requirements.txt }
function Invoke-InstallAll   { & $Python -m pip install -e ".[all]" }
function Invoke-InstallDev   { & $Python -m pip install -e ".[dev,all]" }

function Invoke-LintPy       { & $Python -m ruff check . }
function Invoke-LintRs       { & $Cargo clippy --all-targets -- -D warnings }
function Invoke-Lint          { Invoke-LintPy; Invoke-LintRs }

function Invoke-Fmt {
    & $Python -m ruff format .
    & $Python -m ruff check --fix .
    & $Cargo fmt --all
}

function Invoke-TestPy       { & $Python -m pytest tests/ -q }
function Invoke-TestRs       { & $Cargo test }
function Invoke-Test          { Invoke-TestPy; Invoke-TestRs }

function Invoke-Build         { & $Cargo build --release }

function Invoke-Run           { & $Python rain_lab.py --mode chat }
function Invoke-Preflight     { & $Python rain_lab.py --mode preflight }
function Invoke-Health        { & $Python rain_lab.py --mode health }
function Invoke-Validate      { & $Python rain_lab.py --mode validate }
function Invoke-FirstRun      { & $Python rain_lab.py --mode first-run }

function Invoke-Check         { Invoke-Lint; Invoke-Test }

function Invoke-Clean {
    & $Cargo clean 2>$null
    Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Recurse -Directory -Filter ".ruff_cache"  | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Recurse -Directory -Filter ".pytest_cache" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Cleaned." -ForegroundColor Green
}

switch ($Command) {
    "help"        { Show-Help }
    "install"     { Invoke-Install }
    "install-all" { Invoke-InstallAll }
    "install-dev" { Invoke-InstallDev }
    "lint"        { Invoke-Lint }
    "lint-py"     { Invoke-LintPy }
    "lint-rs"     { Invoke-LintRs }
    "fmt"         { Invoke-Fmt }
    "test"        { Invoke-Test }
    "test-py"     { Invoke-TestPy }
    "test-rs"     { Invoke-TestRs }
    "build"       { Invoke-Build }
    "run"         { Invoke-Run }
    "preflight"   { Invoke-Preflight }
    "health"      { Invoke-Health }
    "validate"    { Invoke-Validate }
    "first-run"   { Invoke-FirstRun }
    "check"       { Invoke-Check }
    "clean"       { Invoke-Clean }
    default       { Write-Host "Unknown command: $Command" -ForegroundColor Red; Show-Help }
}
