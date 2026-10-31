@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
)

python -m gui.app %*
endlocal
