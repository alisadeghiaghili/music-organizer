@echo off
chcp 65001 >nul
title Music Organizer — Build Script
setlocal enabledelayedexpansion
echo.
echo  ================================================
echo   Music Organizer  ^|  Build Script
echo  ================================================
echo.

:: check python
py --version >nul 2>&1
if errorlevel 1 (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] Python not found. Install Python 3.10+
        pause & exit /b 1
    )
    set PYEXE=python
) else (
    set PYEXE=py -3
)

:: create venv if missing
if not exist ".venv\Scripts\python.exe" (
    echo  [1/6] Creating virtual environment...
    %PYEXE% -m venv .venv
    if errorlevel 1 ( echo  [ERROR] venv failed. & pause & exit /b 1 )
)

call .venv\Scripts\activate.bat
if errorlevel 1 ( echo  [ERROR] venv activate failed. & pause & exit /b 1 )

echo  [2/6] Upgrading pip...
python -m pip install --upgrade pip -q

echo  [3/6] Installing dependencies...
python -m pip install mutagen rich pyinstaller -q
if errorlevel 1 ( echo  [ERROR] Dependency install failed. & pause & exit /b 1 )

echo  [4/6] Building GUI (MusicOrganizer-GUI.exe)...
pyinstaller --noconfirm --clean --onefile --windowed ^
    --name "MusicOrganizer-GUI" ^
    --add-data "music_core.py;." ^
    --add-data "fpcalc_installer.py;." ^
    --hidden-import "music_core" ^
    --hidden-import "fpcalc_installer" ^
    --hidden-import "mutagen" ^
    --hidden-import "mutagen.id3" ^
    --hidden-import "mutagen.mp3" ^
    --hidden-import "mutagen.flac" ^
    --hidden-import "mutagen.mp4" ^
    --hidden-import "mutagen.ogg" ^
    --hidden-import "rich" ^
    --hidden-import "rich.console" ^
    --hidden-import "rich.progress" ^
    --hidden-import "rich.table" ^
    --hidden-import "rich.panel" ^
    --hidden-import "rich.prompt" ^
    --collect-all "mutagen" ^
    --collect-all "rich" ^
    music_organizer_gui.py
if errorlevel 1 ( echo  [ERROR] GUI build failed. & pause & exit /b 1 )

echo.
echo  [5/6] Building CLI (MusicOrganizer-CLI.exe)...
pyinstaller --noconfirm --clean --onefile --console ^
    --name "MusicOrganizer-CLI" ^
    --add-data "music_core.py;." ^
    --add-data "fpcalc_installer.py;." ^
    --hidden-import "music_core" ^
    --hidden-import "fpcalc_installer" ^
    --hidden-import "mutagen" ^
    --hidden-import "mutagen.id3" ^
    --hidden-import "mutagen.mp3" ^
    --hidden-import "mutagen.flac" ^
    --hidden-import "mutagen.mp4" ^
    --hidden-import "mutagen.ogg" ^
    --hidden-import "rich" ^
    --hidden-import "rich.console" ^
    --hidden-import "rich.progress" ^
    --hidden-import "rich.table" ^
    --hidden-import "rich.panel" ^
    --hidden-import "rich.prompt" ^
    --collect-all "mutagen" ^
    --collect-all "rich" ^
    music_organizer_cli.py
if errorlevel 1 ( echo  [ERROR] CLI build failed. & pause & exit /b 1 )

echo.
echo  [6/6] Cleaning build artifacts...
rmdir /s /q build 2>nul
del /q *.spec 2>nul

echo.
echo  ================================================
echo   Done! Executables are in: dist\
echo  ================================================
echo.
dir dist\*.exe 2>nul
echo.
pause
