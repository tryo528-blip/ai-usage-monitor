# Build only (dist\AIUsageMonitor.exe + dist\AIUsageMonitor-cli.exe).
# To build, install and register at login, use scripts\install.ps1 instead.
Set-Location $PSScriptRoot\..
$Common = @(
    "--noconfirm", "--clean", "--onefile",
    "--paths", "src",
    "--runtime-hook", "scripts\qt_runtime_hook.py",
    "--add-data", "src\ai_usage_monitor\ui\assets;ai_usage_monitor\ui\assets"
)
pyinstaller @Common --noconsole --name AIUsageMonitor src\ai_usage_monitor\__main__.py
pyinstaller @Common --console --name AIUsageMonitor-cli src\ai_usage_monitor\__main__.py
