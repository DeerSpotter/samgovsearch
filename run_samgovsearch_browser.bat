@echo off
setlocal
cd /d "%~dp0"
title SAM.gov Browser Search

echo.
echo SAM.gov Browser Search Launcher
echo This mode uses an internal browser and does not require SAM_API_KEY.
echo.

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo ERROR: Python was not found.
    pause
    exit /b 1
)

if not exist "samgovsearch_browser.py" (
    echo ERROR: samgovsearch_browser.py was not found next to this BAT file.
    pause
    exit /b 1
)

%PYTHON_CMD% -c "import PyQt6; import PyQt6.QtWebEngineWidgets" >nul 2>nul
if errorlevel 1 (
    echo Missing browser dependencies.
    echo Run this once:
    echo %PYTHON_CMD% -m pip install -r requirements-browser.txt
    echo.
    pause
    exit /b 1
)

echo Starting SAM.gov Browser Search...
%PYTHON_CMD% "samgovsearch_browser.py"
set "APP_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %APP_EXIT%
