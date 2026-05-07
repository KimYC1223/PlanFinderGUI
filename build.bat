@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

if not exist ".venv" (
    echo === Creating virtual environment ===
    uv venv
    if errorlevel 1 exit /b %errorlevel%
)

echo === Installing build deps ===
uv pip install -e ".[build]"
if errorlevel 1 exit /b %errorlevel%

echo === Building with PyInstaller ===
.venv\Scripts\pyinstaller.exe plan_finder_gui.spec --noconfirm
if errorlevel 1 exit /b %errorlevel%

echo.
echo === Done: dist\PlanFinder\PlanFinder.exe ===

endlocal
