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

$createdShortcuts = @()
if (-not $NoShortcuts) {
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $startMenuRoot = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\R.A.I.N. Lab"
    $startCmd = Join-Path $repoRoot "RAIN_Lab_Start.cmd"
    $chatCmd = Join-Path $repoRoot "RAIN_Lab_Chat.cmd"
    $firstRunCmd = Join-Path $repoRoot "RAIN_Lab_First_Run.cmd"
    $healthCmd = Join-Path $repoRoot "RAIN_Lab_Health_Check.cmd"
    $validateCmd = Join-Path $repoRoot "RAIN_Lab_Validate.cmd"
    $iconPath = Join-Path $env:SystemRoot "System32\shell32.dll"
    $iconLocation = "$iconPath,220"

    if (-not (Test-Path $startCmd)) {
        throw "Missing launcher script: $startCmd"
    }
    if (-not (Test-Path $chatCmd)) {
        throw "Missing launcher script: $chatCmd"
    }
    if (-not (Test-Path $firstRunCmd)) {
        throw "Missing launcher script: $firstRunCmd"
    }
    if (-not (Test-Path $healthCmd)) {
        throw "Missing launcher script: $healthCmd"
    }
    if (-not (Test-Path $validateCmd)) {
        throw "Missing launcher script: $validateCmd"
    }

    if (-not $NoDesktopShortcut) {
        New-RainShortcut `
            -ShortcutPath (Join-Path $desktopPath "R.A.I.N. Lab.lnk") `
            -TargetPath $startCmd `
            -WorkingDirectory $repoRoot `
            -Description "Start R.A.I.N. Lab with guided setup on first launch." `
            -IconLocation $iconLocation
        $createdShortcuts += "Desktop: R.A.I.N. Lab"
    }

    if (-not $NoStartMenuShortcut) {
        New-RainShortcut `
            -ShortcutPath (Join-Path $startMenuRoot "R.A.I.N. Lab.lnk") `
            -TargetPath $startCmd `
            -WorkingDirectory $repoRoot `
            -Description "Start R.A.I.N. Lab with guided setup on first launch." `
            -IconLocation $iconLocation
        $createdShortcuts += "Start Menu: R.A.I.N. Lab"

        New-RainShortcut `
            -ShortcutPath (Join-Path $startMenuRoot "R.A.I.N. Lab Chat.lnk") `
            -TargetPath $chatCmd `
            -WorkingDirectory $repoRoot `
            -Description "Launch R.A.I.N. Lab chat mode (auto UI)." `
            -IconLocation $iconLocation
        $createdShortcuts += "Start Menu: R.A.I.N. Lab Chat"

        New-RainShortcut `
            -ShortcutPath (Join-Path $startMenuRoot "R.A.I.N. Lab Health Snapshot.lnk") `
            -TargetPath $healthCmd `
            -WorkingDirectory $repoRoot `
            -Description "Run the one-screen R.A.I.N. Lab system snapshot." `
            -IconLocation $iconLocation
        $createdShortcuts += "Start Menu: R.A.I.N. Lab Health Snapshot"

        New-RainShortcut `
            -ShortcutPath (Join-Path $startMenuRoot "R.A.I.N. Lab Validate.lnk") `
            -TargetPath $validateCmd `
            -WorkingDirectory $repoRoot `
            -Description "Run the full R.A.I.N. Lab readiness validation flow." `
            -IconLocation $iconLocation
        $createdShortcuts += "Start Menu: R.A.I.N. Lab Validate"

        New-RainShortcut `
            -ShortcutPath (Join-Path $startMenuRoot "R.A.I.N. Lab First Run.lnk") `
            -TargetPath $firstRunCmd `
            -WorkingDirectory $repoRoot `
            -Description "Run R.A.I.N. Lab guided first-run checks." `
            -IconLocation $iconLocation
        $createdShortcuts += "Start Menu: R.A.I.N. Lab First Run"
    }

    Write-Host "[installer] Shortcuts created." -ForegroundColor Green
    foreach ($label in $createdShortcuts) {
        Write-Host "  - $label" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "[installer] Success." -ForegroundColor Green
Write-Host "[installer] Recommended next steps:" -ForegroundColor Green
if ($createdShortcuts.Count -gt 0) {
    Write-Host "  1) Run 'R.A.I.N. Lab Validate' for a full readiness check." -ForegroundColor Green
    Write-Host "  2) Launch 'R.A.I.N. Lab' for guided first-run setup or normal start." -ForegroundColor Green
    Write-Host "  3) Use 'R.A.I.N. Lab Chat' for direct chat once you're happy with the setup." -ForegroundColor Green
    Write-Host "[installer] CLI equivalents: python rain_lab.py --mode validate, python rain_lab.py --mode first-run" -ForegroundColor Green
} else {
    Write-Host "  1) python rain_lab.py --mode validate" -ForegroundColor Green
    Write-Host "  2) python rain_lab.py --mode first-run" -ForegroundColor Green
    Write-Host "  3) python rain_lab.py --mode chat --ui auto --topic \"your research question\"" -ForegroundColor Green
}
