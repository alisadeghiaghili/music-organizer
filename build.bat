@echo off
chcp 65001 >nul
title Music Organizer — Build Script
setlocal enabledelayedexpansion
echo.
echo  ================================================
echo   Music Organizer  ^|  Build Script
echo  ================================================
echo.

:: check python launcher
py --version >nul 2>&1
if errorlevel 1 (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] Python not found. Install Python 3.10+ and enable 'py' launcher.
        pause
        exit /b 1
    )
    set PYEXE=python
) else (
    set PYEXE=py -3
)

:: create venv if missing
if not exist ".venv\Scripts\python.exe" (
    echo  [1/6] Creating virtual environment...
    %PYEXE% -m venv .venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo  [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

echo  [2/6] Upgrading pip...
python -m pip install --upgrade pip -q

echo  [3/6] Installing dependencies...
python -m pip install mutagen rich pyinstaller -q
if errorlevel 1 (
    echo  [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

echo  [4/6] Building GUI (MusicOrganizer-GUI.exe)...
pyinstaller --noconfirm --clean --onefile --windowed ^
    --name "MusicOrganizer-GUI" ^
    --add-data "music_core.py;." ^
    --add-data "fpcalc_installer.py;." ^
    music_organizer_gui.py
if errorlevel 1 (
    echo  [ERROR] GUI build failed.
    pause
    exit /b 1
)

echo.
echo  [5/6] Building CLI (MusicOrganizer-CLI.exe)...
pyinstaller --noconfirm --clean --onefile --console ^
    --name "MusicOrganizer-CLI" ^
    --add-data "music_core.py;." ^
    --add-data "fpcalc_installer.py;." ^
    music_organizer_cli.py
if errorlevel 1 (
    echo  [ERROR] CLI build failed.
    pause
    exit /b 1
)

echo.
echo  [6/6] Cleaning build artifacts...
rmdir /s /q build 2>nul
del /q *.spec 2>nul
echo  Cleaned.

echo.
echo  ================================================
echo   Done! Executables are in: dist\
echo  ================================================
echo.
dir dist\*.exe 2>nul

echo.
echo  To rebuild later:
echo    call .venv\Scripts\activate.bat
echo    build.bat

echo.
pause
