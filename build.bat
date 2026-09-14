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

:: fpcalc.exe must exist in this folder to embed it into the exe
if not exist "fpcalc.exe" (
    echo  [ERROR] fpcalc.exe not found in project folder.
    echo  Download it from: https://github.com/acoustid/chromaprint/releases
    echo  and place fpcalc.exe next to build.bat, then run again.
    pause & exit /b 1
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
:: GUI is now the pywebview (WebView2) frontend, so it also needs pywebview +
:: pythonnet (the .NET bridge). CLI still only needs mutagen + rich.
python -m pip install mutagen rich pyinstaller pywebview pythonnet -q
if errorlevel 1 ( echo  [ERROR] Dependency install failed. & pause & exit /b 1 )

echo  [4/6] Building GUI (MusicOrganizer-GUI.exe, pywebview)...
:: The bundled pywebview + pythonnet PyInstaller hooks bundle the WebView2
:: runtime and clr automatically; we only add the platform module + icon.
:: Do NOT --collect-all webview (it imports the WinForms platform, which calls
:: clr.AddReference at analysis time and aborts the build).
if not exist "app.ico" (
    echo  [ERROR] app.ico not found (required for the GUI icon).
    pause & exit /b 1
)
pyinstaller --noconfirm --clean --onefile --windowed ^
    --name "MusicOrganizer-GUI" ^
    --icon "app.ico" ^
    --add-binary "fpcalc.exe;." ^
    --add-data "icon.png;." ^
    --add-data "app.ico;." ^
    --hidden-import "music_core" ^
    --hidden-import "fpcalc_installer" ^
    --hidden-import "config" ^
    --hidden-import "webview.platforms.winforms" ^
    --hidden-import "pythonnet" ^
    --collect-all "mutagen" ^
    music_organizer_web.py
if errorlevel 1 ( echo  [ERROR] GUI build failed. & pause & exit /b 1 )

echo.
echo  [5/6] Building CLI (MusicOrganizer-CLI.exe)...
pyinstaller --noconfirm --clean --onefile --console ^
    --name "MusicOrganizer-CLI" ^
    --add-data "music_core.py;." ^
    --add-data "fpcalc_installer.py;." ^
    --add-binary "fpcalc.exe;." ^
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
