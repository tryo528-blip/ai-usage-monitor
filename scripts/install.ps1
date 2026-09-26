# Rebuild AI Usage Monitor, install it under %LOCALAPPDATA%\Programs, and start it at login.
#
# Works in PowerShell 7 (pwsh) and Windows PowerShell 5.1:
#   pwsh -ExecutionPolicy Bypass -File scripts\install.ps1            # build + install
#   pwsh -ExecutionPolicy Bypass -File scripts\install.ps1 -Uninstall # remove
# or double-click install.bat in the repository root.
#
# Nothing is placed on the desktop; old desktop copies are removed.

param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

$AppName = "AIUsageMonitor"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$StartupDir = [Environment]::GetFolderPath("Startup")
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$StartupLink = Join-Path $StartupDir "AI Usage Monitor.lnk"
$StartMenuLink = Join-Path ([Environment]::GetFolderPath("Programs")) "AI Usage Monitor.lnk"

function Stop-RunningApp {
    Get-Process -Name $AppName, "$AppName-cli" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

function Remove-DesktopCopies {
    foreach ($name in @("$AppName.exe", "$AppName-cli.exe", "$AppName.lnk", "AI Usage Monitor.lnk")) {
        $path = Join-Path $DesktopDir $name
        if (Test-Path $path) {
            Remove-Item $path -Force
            Write-Host "Removed from desktop: $name"
        }
    }
}

if ($Uninstall) {
    Stop-RunningApp
    if (Test-Path $StartupLink) { Remove-Item $StartupLink -Force }
    if (Test-Path $StartMenuLink) { Remove-Item $StartMenuLink -Force }
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
    Remove-DesktopCopies
    Write-Host "Uninstalled. Settings and history in %APPDATA%\$AppName were kept."
    exit 0
}

# 1. Python environment (reuse .venv when present).
$Python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    # First Python >= 3.11 found: py launcher (3.11, then newest 3.x), then python on PATH.
    $Base = $null
    foreach ($candidate in @(@("py", "-3.11"), @("py", "-3"), @("python"))) {
        $exe = $candidate[0]
        $launcherArgs = @($candidate | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        & $exe @launcherArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $Base = $candidate; break }
    }
    if (-not $Base) { throw "Python 3.11+ not found. Install it: winget install Python.Python.3.11" }
    Write-Host "Creating .venv with: $($Base -join ' ')"
    $exe = $Base[0]
    $launcherArgs = @($Base | Select-Object -Skip 1)
    & $exe @launcherArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv" }
}
& $Python -m pip install --quiet --upgrade pip
& $Python -m pip install --quiet -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed." }

# 2. Build the windowed app and the console diagnostics tool.
Stop-RunningApp
$Common = @(
    "--noconfirm", "--clean", "--onefile",
    "--paths", "src",
    "--runtime-hook", "scripts\qt_runtime_hook.py",
    "--add-data", "src\ai_usage_monitor\ui\assets;ai_usage_monitor\ui\assets"
)
& $Python -m PyInstaller @Common --noconsole --name $AppName src\ai_usage_monitor\__main__.py
if ($LASTEXITCODE -ne 0) { throw "Build failed: $AppName.exe" }
& $Python -m PyInstaller @Common --console --name "$AppName-cli" src\ai_usage_monitor\__main__.py
if ($LASTEXITCODE -ne 0) { throw "Build failed: $AppName-cli.exe" }

# 3. Install. Stop again: the build takes a while and the app may have been
# started meanwhile, which would lock the exe being replaced.
Stop-RunningApp
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item "dist\$AppName.exe" $InstallDir -Force
Copy-Item "dist\$AppName-cli.exe" $InstallDir -Force
$AppExe = Join-Path $InstallDir "$AppName.exe"

# 4. Start at login with only the taskbar readout showing, and add a Start menu
#    entry to open the window (a second launch shows the running instance).
$Shell = New-Object -ComObject WScript.Shell
foreach ($entry in @(@($StartupLink, "--hidden"), @($StartMenuLink, ""))) {
    $Link = $Shell.CreateShortcut($entry[0])
    $Link.TargetPath = $AppExe
    $Link.Arguments = $entry[1]
    $Link.WorkingDirectory = $InstallDir
    $Link.Description = "AI Usage Monitor"
    $Link.Save()
}

Remove-DesktopCopies

Write-Host ""
Write-Host "Installed : $AppExe"
Write-Host "Diagnose  : $(Join-Path $InstallDir "$AppName-cli.exe") --claude-raw"
Write-Host "At login  : $StartupLink"
Write-Host "Start menu: $StartMenuLink"

# 5. Launch now.
Start-Process -FilePath $AppExe -WorkingDirectory $InstallDir
