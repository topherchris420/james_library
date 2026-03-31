param(
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

function Resolve-UvPath {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCommand) {
        return $uvCommand.Source
    }

    $localUv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $localUv) {
        return $localUv
    }

    return $null
}

function Install-Uv {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curl) {
        throw "curl.exe is required to install uv."
    }

    $installerPath = Join-Path $env:TEMP "install-uv.ps1"
    & $curl.Source -LsSf "https://astral.sh/uv/install.ps1" -o $installerPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to download the uv installer."
    }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installerPath
    if ($LASTEXITCODE -ne 0) {
        throw "uv installer exited with code $LASTEXITCODE"
    }
}

function Ensure-Uv {
    $uvPath = Resolve-UvPath
    if ($uvPath) {
        return [string]$uvPath
    }

    Write-Host "[installer] Installing uv..." -ForegroundColor Yellow
    Install-Uv | Out-Null

    $env:PATH = "$($env:USERPROFILE)\.local\bin;$env:PATH"
    $uvPath = Resolve-UvPath
    if (-not $uvPath) {
        throw "uv installation completed but uv.exe was not found."
    }

    return [string]$uvPath
}

function Invoke-Uv {
    param(
        [Parameter(Mandatory = $true)][string]$UvPath,
        [Parameter(Mandatory = $true)][string[]]$Args
    )

    Write-Host "[installer] $UvPath $($Args -join ' ')" -ForegroundColor Yellow
    & $UvPath @Args
    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed with exit code $LASTEXITCODE"
    }
}

function Ensure-UvLock {
    param(
        [Parameter(Mandatory = $true)][string]$UvPath
    )

    $runtimeRequirements = Join-Path $repoRoot "requirements-pinned.txt"
    $lockPath = Join-Path $repoRoot ".uv-pip.lock"
    if (Test-Path $lockPath) {
        Remove-Item $lockPath -Force
    }
    Invoke-Uv -UvPath $UvPath -Args @("pip", "compile", $runtimeRequirements, "-o", $lockPath)
    return $lockPath
}

function Ensure-RainEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$UvPath
    )

    $venvDir = Join-Path $repoRoot ".venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"

    if ($RecreateVenv -and (Test-Path $venvDir)) {
        Write-Host "[installer] Removing existing virtual environment..." -ForegroundColor Yellow
        Remove-Item $venvDir -Recurse -Force
    }

    Invoke-Uv -UvPath $UvPath -Args @("python", "install", "3.12")
    Invoke-Uv -UvPath $UvPath -Args @("venv", $venvDir, "--python", "3.12")
    $pipLockPath = Ensure-UvLock -UvPath $UvPath
    Invoke-Uv -UvPath $UvPath -Args @("pip", "sync", "--python", $venvPython, $pipLockPath)

    return $venvPython
}

function Invoke-Bootstrap {
    param(
        [Parameter(Mandatory = $true)][string]$UvPath,
        [Parameter(Mandatory = $true)][string]$VenvPython
    )

    $bootstrapArgs = @("run", "--python", $VenvPython, "bootstrap_local.py")
    if ($SkipPreflight) {
        $bootstrapArgs += "--skip-preflight"
    }
    Invoke-Uv -UvPath $UvPath -Args $bootstrapArgs
}

function Invoke-Greet {
    param(
        [Parameter(Mandatory = $true)][string]$UvPath,
        [Parameter(Mandatory = $true)][string]$VenvPython
    )

    Invoke-Uv -UvPath $UvPath -Args @("run", "--python", $VenvPython, "chat_with_james.py", "--greet")
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "R.A.I.N. Lab Local Installer" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

if ($NoDev) {
    Write-Host "[installer] Note: -NoDev is kept for compatibility and is ignored by the new uv runtime flow." -ForegroundColor DarkYellow
}

$uvPath = Ensure-Uv
$venvPython = Ensure-RainEnvironment -UvPath $uvPath
Invoke-Bootstrap -UvPath $uvPath -VenvPython $venvPython

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
Write-Host "[installer] Handing off to James..." -ForegroundColor Green
Invoke-Greet -UvPath $uvPath -VenvPython $venvPython
