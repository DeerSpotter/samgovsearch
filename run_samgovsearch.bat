@echo off
setlocal

cd /d "%~dp0"
title SAM.gov Search

echo.
echo SAM.gov Search Launcher
echo =======================

set "PYTHON_CMD="

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL%==0 (
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

if not exist "samgovsearch.py" (
    echo ERROR: samgovsearch.py was not found next to this BAT file.
    echo Put this BAT file in the same folder as samgovsearch.py.
    echo.
    pause
    exit /b 1
)

if not defined SAM_API_KEY (
    echo SAM_API_KEY is not set in this Command Prompt environment.
    echo.
    echo Paste your SAM.gov API key for this launch only, or press Enter to quit.
    set /p "SAM_API_KEY=SAM_API_KEY: "
    if not defined SAM_API_KEY (
        echo.
        echo No API key entered. Exiting.
        pause
        exit /b 1
    )
)

echo.
echo Starting SAM.gov Search...
%PYTHON_CMD% "samgovsearch.py"

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
