@echo off
setlocal

cd /d "%~dp0"
title SAM.gov Search

echo.
echo SAM.gov Search Launcher
echo =======================
echo Launches the unified responsive UI with Website/Internal, Official API,
echo Hybrid modes, settings, sortable columns, advanced result filtering,
echo exclusion filtering, SQLite local index, cache manager, enrichment view,
echo retry settings, fast prompt-free attachment ZIP downloads, optional initial
echo search match validation, and live wildcard attachment filtering.
echo.

set "PYTHON_CMD="
set "APP_SCRIPT=samgovsearch_pro_initial_match_toggle.py"

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    echo ERROR: Python was not found.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/
    echo Make sure "Add python.exe to PATH" is checked during install.
    echo.
    pause
    exit /b 1
)

if not exist "%APP_SCRIPT%" (
    echo ERROR: %APP_SCRIPT% was not found next to this BAT file.
    echo Run git pull, then try again.
    echo.
    pause
    exit /b 1
)

if not defined SAM_API_KEY (
    echo SAM_API_KEY is not set. That is OK for Website/Internal Search mode.
    echo You can add it from Settings inside the app for Official API mode and Hybrid enrichment.
    echo.
)

echo Starting SAM.gov Search using %APP_SCRIPT%...
%PYTHON_CMD% "%APP_SCRIPT%"

set "APP_EXIT=%ERRORLEVEL%"
echo.
if not "%APP_EXIT%"=="0" (
    echo SAM.gov Search closed with error code %APP_EXIT%.
) else (
    echo SAM.gov Search closed.
)
echo.
pause
exit /b %APP_EXIT%
