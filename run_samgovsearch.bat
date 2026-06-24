@echo off
setlocal

cd /d "%~dp0"
title SAM.gov Search

echo.
echo SAM.gov Search Launcher
echo =======================
echo Starting SAM.gov Search with conditional NAICS query/filter support.
echo.

set "PYTHON_CMD="
set "APP_SCRIPT=samgovsearch_pro_naics_q_filter.py"

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
    echo Install Python 3.10 or newer and make sure it is on PATH.
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
