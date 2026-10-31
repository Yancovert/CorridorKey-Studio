@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo error: python is not installed or not on PATH.
    pause
    exit /b 1
)

python install_gui.py %*
if %ERRORLEVEL% neq 0 (
    echo GUI installer failed, launching CLI installer...
    python install.py %*
)
pause
endlocal
