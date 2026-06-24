# 🎸 Music Organizer

Automatically organize your MP3 library by enriching metadata from online sources and audio fingerprinting — then sort everything into a clean folder structure.

---

## ✨ Features

| | Feature | Details |
|---|---|---|
| 🔍 | **Online metadata lookup** | Fetches title, artist, album, year, track, disc, label, composer, and genre automatically |
| 🎵 | **Audio fingerprinting fallback** | Identifies untagged or mis-tagged files by audio content |
| ⬇️ | **Auto-installs fingerprinting tool** | Downloads and sets up the audio fingerprinting binary on demand (~2 MB), with progress bar in both GUI and CLI |
| 🖼️ | **Album art** | Downloads and embeds cover art into MP3 tags; also saves `cover.jpg` in each album folder |
| 🎭 | **Genre enrichment** | Pulls genre tags from metadata databases and optional Last.fm fallback |
| 🔀 | **Duplicate album merge** | Detects and merges split album folders after organizing |
| 🗓️ | **Original release year** | Always picks the oldest known release date |
| 📋 | **Rich metadata written to tags** | Saves enriched title, artist, album, year, track, disc, genre, label, composer back to each file |
| 🖥️ | **GUI frontend** | Tkinter-based dark UI with Scan → Organize workflow, Pause/Resume/Stop, dual progress bars, and live results table |
| 💻 | **CLI frontend** | Rich-powered terminal UI with interactive mode and full argument support |
| 📦 | **Copy or Move mode** | Keep your originals or move files; overwrite or skip duplicates |
| 👁️ | **Dry-run / Preview** | See exactly what would happen without touching any files |

---

## 📁 Project Structure

```
music-organizer/
├── music_core.py            ← shared logic (metadata, fingerprinting, art, tags, filesystem)
├── music_organizer_gui.py   ← GUI frontend (Tkinter)
├── music_organizer_cli.py   ← CLI frontend (Rich)
├── fpcalc_installer.py      ← fingerprinting tool auto-downloader
├── requirements.txt
├── build.bat                ← Windows build script → dist\MusicOrganizer-GUI.exe + CLI.exe
└── CHANGELOG.md
```

---

## 🚀 Installation

**Requirements:** Python 3.10+

```bash
pip install -r requirements.txt
```

`requirements.txt` includes `mutagen` (tag reading/writing) and `rich` (CLI UI).

---

## 🎮 Usage

### GUI

```bash
python music_organizer_gui.py
```

1. **Browse** source and output folders
2. Toggle options (keep originals, album art, genre, preview mode, …)
3. Click **Scan** to preview your library
4. Click **Organize!** — use ⏸ Pause / ⏹ Stop at any time

### CLI — interactive

```bash
python music_organizer_cli.py
```

Answers a series of prompts, then shows a live progress bar and a final results table.

### CLI — arguments

```bash
# Basic
python music_organizer_cli.py "D:/Music" "D:/Organized"

# Move files instead of copying
python music_organizer_cli.py "D:/Music" "D:/Organized" --move

# Preview without making changes
python music_organizer_cli.py "D:/Music" "D:/Organized" --preview

# Skip album art download
python music_organizer_cli.py "D:/Music" "D:/Organized" --no-art

# Replace existing album art
python music_organizer_cli.py "D:/Music" "D:/Organized" --replace-art

# Detailed log
python music_organizer_cli.py "D:/Music" "D:/Organized" --verbose

# All options
python music_organizer_cli.py "D:/Music" "D:/Organized" \
    --move --no-deep --no-tags --no-art --overwrite --no-merge --verbose
```

#### All CLI flags

| Flag | Description |
|---|---|
| `--move` | Move files instead of copying |
| `--no-deep` | Skip deep metadata lookup (faster, less accurate) |
| `--no-tags` | Do not write enriched tags back to files |
| `--no-art` | Skip album art download |
| `--replace-art` | Replace existing embedded album art |
| `--overwrite` | Overwrite existing output files |
| `--preview` | Dry-run — show changes without applying them |
| `--no-merge` | Skip merging duplicate album folders |
| `--verbose` / `-v` | Show detailed per-file processing log |
| `--install-deps` | Install required Python packages |

---

## 🏗️ Build Windows EXE

```bat
build.bat
```

Creates a clean `.venv`, installs all dependencies, and produces:

```
dist\
├── MusicOrganizer-GUI.exe   ← double-click, no Python needed
└── MusicOrganizer-CLI.exe   ← run from terminal
```

> The audio fingerprinting binary is bundled automatically inside the EXE by `build.bat`.

---

## 📂 Output Structure

```
Output/
└── Artist Name/
    └── 2006 - Album Name/
        ├── 01 - Track Title.mp3
        ├── 02 - Track Title.mp3
        └── cover.jpg
```

---

## 🔧 Optional: Last.fm Genre Enrichment

For extra genre accuracy, set your Last.fm API key in `music_core.py`:

```python
LASTFM_KEY = "your_api_key_here"
```

Leave it empty to skip (default). All other metadata features work without it.

---

## 📝 License

MIT
