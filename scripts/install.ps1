# Rebuild AI Usage Monitor, install it under %LOCALAPPDATA%\Programs, and start it at login.
#
# Written for PowerShell 7 (pwsh):
#   pwsh -ExecutionPolicy Bypass -File scripts\install.ps1            # build + install
#   pwsh -ExecutionPolicy Bypass -File scripts\install.ps1 -Uninstall # remove
# or double-click install.bat in the repository root.
#
# Nothing is placed on the desktop; old desktop copies are removed.

#Requires -Version 7
param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

$AppName = "AIUsageMonitor"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$StartupDir = [Environment]::GetFolderPath("Startup")
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$StartupLink = Join-Path $StartupDir "AI Usage Monitor.lnk"

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
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
    Remove-DesktopCopies
    Write-Host "Uninstalled. Settings and history in %APPDATA%\$AppName were kept."
    exit 0
}

# 1. Python environment (reuse .venv when present).
$Python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "Creating .venv ..."
    py -3.11 -m venv .venv
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

# 3. Install.
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item "dist\$AppName.exe" $InstallDir -Force
Copy-Item "dist\$AppName-cli.exe" $InstallDir -Force
$AppExe = Join-Path $InstallDir "$AppName.exe"

# 4. Start at login, straight into the taskbar tray.
$Shell = New-Object -ComObject WScript.Shell
$Link = $Shell.CreateShortcut($StartupLink)
$Link.TargetPath = $AppExe
$Link.Arguments = "--tray"
$Link.WorkingDirectory = $InstallDir
$Link.Description = "AI Usage Monitor"
$Link.Save()

Remove-DesktopCopies

Write-Host ""
Write-Host "Installed : $AppExe"
Write-Host "Diagnose  : $(Join-Path $InstallDir "$AppName-cli.exe") --claude-raw"
Write-Host "At login  : $StartupLink"

# 5. Launch now.
Start-Process -FilePath $AppExe -WorkingDirectory $InstallDir
