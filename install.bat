@echo off
rem Rebuild, install to %LOCALAPPDATA%\Programs\AIUsageMonitor and register at login.
rem Add -Uninstall to remove:  install.bat -Uninstall
where pwsh >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
)
pause
