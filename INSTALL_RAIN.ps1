param(
    [string]$Python = "python",
    [switch]$NoDev,
    [switch]$SkipPreflight,
    [switch]$RecreateVenv,
    [switch]$NoShortcuts,
    [switch]$NoDesktopShortcut,
    [switch]$NoStartMenuShortcut
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

function New-RainShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$ShortcutPath,
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [string]$WorkingDirectory = "",
        [string]$Description = "",
        [string]$IconLocation = ""
    )

    $shortcutDir = Split-Path -Parent $ShortcutPath
    if (-not (Test-Path $shortcutDir)) {
        New-Item -ItemType Directory -Path $shortcutDir -Force | Out-Null
    }

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $TargetPath
    if ($WorkingDirectory) {
        $shortcut.WorkingDirectory = $WorkingDirectory
    }
    if ($Description) {
        $shortcut.Description = $Description
    }
    if ($IconLocation) {
        $shortcut.IconLocation = $IconLocation
    }
    $shortcut.Save()
}

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

if (-not $NoShortcuts) {
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $startMenuRoot = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\R.A.I.N. Lab"
    $chatCmd = Join-Path $repoRoot "RAIN_Lab_Chat.cmd"
    $firstRunCmd = Join-Path $repoRoot "RAIN_Lab_First_Run.cmd"
    $healthCmd = Join-Path $repoRoot "RAIN_Lab_Health_Check.cmd"
    $iconPath = Join-Path $env:SystemRoot "System32\shell32.dll"
    $iconLocation = "$iconPath,220"

    if (-not (Test-Path $chatCmd)) {
        throw "Missing launcher script: $chatCmd"
    }
    if (-not (Test-Path $firstRunCmd)) {
        throw "Missing launcher script: $firstRunCmd"
    }
    if (-not (Test-Path $healthCmd)) {
        throw "Missing launcher script: $healthCmd"
    }

    if (-not $NoDesktopShortcut) {
        New-RainShortcut `
            -ShortcutPath (Join-Path $desktopPath "R.A.I.N. Lab Chat.lnk") `
            -TargetPath $chatCmd `
            -WorkingDirectory $repoRoot `
            -Description "Launch R.A.I.N. Lab chat mode (auto UI)." `
            -IconLocation $iconLocation
    }

    if (-not $NoStartMenuShortcut) {
        New-RainShortcut `
            -ShortcutPath (Join-Path $startMenuRoot "R.A.I.N. Lab Chat.lnk") `
            -TargetPath $chatCmd `
            -WorkingDirectory $repoRoot `
            -Description "Launch R.A.I.N. Lab chat mode (auto UI)." `
            -IconLocation $iconLocation

        New-RainShortcut `
            -ShortcutPath (Join-Path $startMenuRoot "R.A.I.N. Lab Health Check.lnk") `
            -TargetPath $healthCmd `
            -WorkingDirectory $repoRoot `
            -Description "Run local health checks for LM Studio, UI, and launcher logs." `
            -IconLocation $iconLocation

        New-RainShortcut `
            -ShortcutPath (Join-Path $startMenuRoot "R.A.I.N. Lab First Run.lnk") `
            -TargetPath $firstRunCmd `
            -WorkingDirectory $repoRoot `
            -Description "Run R.A.I.N. Lab guided first-run checks." `
            -IconLocation $iconLocation
    }

    Write-Host "[installer] Shortcuts created." -ForegroundColor Green
}

Write-Host ""
Write-Host "[installer] Success." -ForegroundColor Green
Write-Host "[installer] Next: double-click 'R.A.I.N. Lab Chat' on your Desktop or Start Menu." -ForegroundColor Green
