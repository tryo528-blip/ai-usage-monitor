@echo off
rem Rebuild, install to %LOCALAPPDATA%\Programs\AIUsageMonitor and register at login.
rem Add -Uninstall to remove:  install.bat -Uninstall
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
pause
