Set-Location $PSScriptRoot\..
pyinstaller --noconsole --onefile src\ai_usage_monitor\__main__.py --name AIUsageMonitor
