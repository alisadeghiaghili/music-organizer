# 🎸 Music Organizer

Automatically organize your MP3 library using **MusicBrainz** metadata lookup and **AcoustID** audio fingerprinting.

## Features

- 🔍 Looks up tags via MusicBrainz API
- 🎵 Falls back to AcoustID audio fingerprinting (fpcalc)
- ⬇️ **Auto-installs fpcalc** if missing (with progress bar in GUI and CLI)
- 🔀 Merges duplicate album folders after organizing
- 🗓️ Always picks the oldest/original release year
- 🖥️ GUI (Tkinter) and CLI (Rich) frontends
- 📦 Supports copy or move mode, dry-run, overwrite

## Project Structure

```
music-organizer/
├── music_core.py              ← shared logic
├── music_organizer_gui.py     ← GUI (Tkinter)
├── music_organizer_cli.py     ← CLI (Rich)
├── fpcalc_installer.py        ← fpcalc auto-downloader
├── requirements.txt
└── build.bat
```

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
# GUI
python music_organizer_gui.py

# CLI interactive
python music_organizer_cli.py

# CLI with args
python music_organizer_cli.py "D:/Music" "D:/Out"
python music_organizer_cli.py "D:/Music" "D:/Out" --move --verbose
python music_organizer_cli.py "D:/Music" "D:/Out" --dry-run
python music_organizer_cli.py "D:/Music" "D:/Out" --no-merge
```

## Build EXE

```bat
build.bat
```

> `build.bat` creates a clean `.venv`, installs dependencies, and builds both GUI and CLI executables into `dist\`.

## Output Structure

```
Output/
└── Artist Name/
    └── 2006 - Album Name/
        ├── 01 - Track Title.mp3
        └── 02 - Track Title.mp3
```
