@echo off
setlocal

echo ==========================================
echo CorridorKey Studio - Uninstaller (Windows)
echo ==========================================
echo.

set SCRIPT_DIR=%~dp0
set /p CONFIRM="Uninstall CorridorKey Studio? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo Uninstallation cancelled.
    pause
    exit /b 0
)

echo [1/4] Removing desktop and start menu shortcuts...
if exist "%USERPROFILE%\Desktop\CorridorKey Studio.lnk" del /f /q "%USERPROFILE%\Desktop\CorridorKey Studio.lnk"
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\CorridorKey Studio.lnk" del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\CorridorKey Studio.lnk"

echo [2/4] Removing user configuration...
if exist "%APPDATA%\CorridorKey Studio" rd /s /q "%APPDATA%\CorridorKey Studio"

echo [3/4] Removing virtual environment...
if exist "%SCRIPT_DIR%venv" rd /s /q "%SCRIPT_DIR%venv"

echo [4/4] Cleaning application files...
if exist "%SCRIPT_DIR%weights" (
    set /p RM_WEIGHTS="Delete downloaded model weights (~1.5 GB)? (Y/N): "
    if /i "%RM_WEIGHTS%"=="Y" rd /s /q "%SCRIPT_DIR%weights"
)

if exist "%SCRIPT_DIR%gui" rd /s /q "%SCRIPT_DIR%gui"
if exist "%SCRIPT_DIR%corridorkey" rd /s /q "%SCRIPT_DIR%corridorkey"
if exist "%SCRIPT_DIR%launch_gui.bat" del /f /q "%SCRIPT_DIR%launch_gui.bat"
if exist "%SCRIPT_DIR%.build_version" del /f /q "%SCRIPT_DIR%.build_version"

echo.
echo CorridorKey Studio has been completely uninstalled.
echo You can now delete this folder if desired: %SCRIPT_DIR%
pause
