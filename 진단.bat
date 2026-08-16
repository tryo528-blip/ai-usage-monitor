@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
echo ===============================================
echo  AI Usage Monitor - Claude CLI locator
echo ===============================================
echo.
echo USERPROFILE = %USERPROFILE%
echo APPDATA     = %APPDATA%
echo LOCALAPPDATA= %LOCALAPPDATA%
echo.
echo --- where claude ---
where claude 2>nul || echo   (not on PATH)
where claude.cmd 2>nul || echo   (claude.cmd not on PATH)
where claude.exe 2>nul || echo   (claude.exe not on PATH)
echo.
echo --- scanning known roots ---
for %%D in (
  "%APPDATA%\Claude\claude-code"
  "%LOCALAPPDATA%\Claude\claude-code"
  "%APPDATA%\npm"
  "%LOCALAPPDATA%\Programs\claude"
  "%USERPROFILE%\.claude\bin"
  "%USERPROFILE%\.local\bin"
) do (
  if exist %%D (
    echo [FOUND DIR] %%D
    dir /b %%D 2>nul
  ) else (
    echo [missing  ] %%D
  )
)
echo.
echo --- deep search for claude.exe under user profile ---
dir /s /b "%USERPROFILE%\claude.exe" 2>nul
dir /s /b "%APPDATA%\claude.exe" 2>nul
dir /s /b "%LOCALAPPDATA%\claude.exe" 2>nul
echo   (deep search done)
echo.
echo --- running the monitor CLI ---
"C:\marco\ai_usage_monitoring\dist\AIUsageMonitor-cli.exe" --print
echo.
echo ===============================================
pause
