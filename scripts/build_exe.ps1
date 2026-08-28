Set-Location $PSScriptRoot\..
pyinstaller --noconsole --onefile --paths src --runtime-hook scripts\qt_runtime_hook.py --add-data "src\ai_usage_monitor\ui\assets;ai_usage_monitor\ui\assets" src\ai_usage_monitor\__main__.py --name AIUsageMonitor
