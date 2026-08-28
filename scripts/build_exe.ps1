Set-Location $PSScriptRoot\..
pyinstaller --noconsole --onefile --paths src --runtime-hook scripts\qt_runtime_hook.py src\ai_usage_monitor\__main__.py --name AIUsageMonitor
