Set-Location $PSScriptRoot\..
pyinstaller --noconsole --onefile --paths src src\ai_usage_monitor\__main__.py --name AIUsageMonitor
