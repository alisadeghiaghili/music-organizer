# Music Organizer

Automatically organize your music library by enriching metadata from online sources and audio fingerprinting — then sort everything into a clean folder structure.

---

## Features

| Feature | Details |
|---|---|
| **Multi-format support** | MP3, FLAC, OGG/Vorbis, M4A/MP4, WAV, AIFF, Opus, APE, WMA |
| **Online metadata lookup** | Fetches title, artist, album, year, track, disc, label, composer, and genre from MusicBrainz |
| **Audio fingerprinting fallback** | Identifies untagged or mis-tagged files by audio content (AcoustID/Chromaprint) |
| **Auto-installs fingerprinting tool** | Downloads and sets up the audio fingerprinting binary on demand (~2 MB) |
| **Album art** | Downloads and embeds cover art; saves `cover.jpg` in each album folder |
| **Genre enrichment** | Pulls genre tags from MusicBrainz + optional Last.fm fallback |
| **Lyrics fetching** | Downloads synced lyrics from LRCLIB (free, no API key required) |
| **Duplicate album merge** | Detects and merges split album folders after organizing |
| **Original release year** | Always picks the oldest known release date |
| **Rich metadata written to tags** | Saves enriched metadata back to each file in its native format |
| **GUI frontend** | Tkinter-based dark UI with Scan / Organize workflow, Pause/Resume/Stop |
| **CLI frontend** | Rich-powered terminal UI with interactive mode and full argument support |
| **Copy or Move mode** | Keep your originals or move files; overwrite or skip duplicates |
| **Dry-run / Preview** | See exactly what would happen without touching any files |
| **Centralized configuration** | `~/.music-organizer/config.json` with environment variable overrides |

---

## Why Music Organizer?

| Advantage | Details |
|---|---|
| **Free synced lyrics** | Uses LRCLIB — no API key, no preview limits, full synced lyrics |
| **Cross-platform GUI** | Works on Windows, macOS, Linux (unlike Mp3tag which is Windows-only) |
| **Pause/Resume/Stop** | Control batch operations — rare in open-source tools |
| **Multi-format write** | Writes tags to FLAC, OGG, M4A, WAV, AIFF (many tools only read) |
| **Auto-organize** | Sorts into `Artist/Year - Album/Track - Title` structure automatically |
| **Duplicate merge** | Detects and consolidates split album folders |
| **No install required** | Single Python script, or build to EXE with `build.bat` |

---

## Project Structure

```
music-organizer/
├── music_core.py            ← shared logic (metadata, fingerprinting, art, tags, filesystem)
├── music_organizer_gui.py   ← GUI frontend (Tkinter)
├── music_organizer_cli.py   ← CLI frontend (Rich)
├── fpcalc_installer.py      ← fingerprinting tool auto-downloader
├── config.py                ← centralized configuration system
├── requirements.txt
├── pyproject.toml
├── build.bat                ← Windows build script
├── tests/                   ← test suite (pytest)
├── README.md
└── CHANGELOG.md
```

---

## Installation

**Requirements:** Python 3.10+

```bash
pip install -r requirements.txt
```

### Development

```bash
pip install -r requirements.txt  # includes pytest, pytest-cov
python -m pytest tests/ -v       # run tests
```

---

## Usage

### GUI

```bash
python music_organizer_gui.py
```

1. **Browse** source and output folders
2. Toggle options (keep originals, album art, genre, preview mode, ...)
3. Click **Scan** to preview your library
4. Click **Organize!** — use Pause / Stop at any time

### CLI — interactive

```bash
python music_organizer_cli.py
```

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

# Skip lyrics fetching
python music_organizer_cli.py "D:/Music" "D:/Organized" --no-lyrics

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
| `--no-lyrics` | Skip lyrics fetching |
| `--replace-art` | Replace existing embedded album art |
| `--overwrite` | Overwrite existing output files |
| `--preview` | Dry-run — show changes without applying them |
| `--no-merge` | Skip merging duplicate album folders |
| `--verbose` / `-v` | Show detailed per-file processing log |
| `--install-deps` | Install required Python packages |

---

## Build Windows EXE

```bat
build.bat
```

Produces:

```
dist\
├── MusicOrganizer-GUI.exe   ← double-click, no Python needed
└── MusicOrganizer-CLI.exe   ← run from terminal
```

---

## Configuration

The tool uses a centralized configuration system. Default values work out of the box.

**Config file:** `~/.music-organizer/config.json` (overrides defaults)

**Environment variables:** `MUSIC_ORG_*` prefix (overrides file config)

```bash
# Example: set custom AcoustID API key
set MUSIC_ORG_ACOUSTID_API_KEY=your_key_here

# Example: set Last.fm API key
set MUSIC_ORG_LASTFM_API_KEY=your_key_here
```

### Supported configuration keys

| Key | Default | Description |
|---|---|---|
| `acoustid_api_key` | (built-in) | AcoustID API key for fingerprinting |
| `lastfm_api_key` | (empty) | Last.fm API key for genre enrichment |
| `user_agent` | `MusicOrganizer/2.0 (...)` | User-Agent for API requests |
| `mb_rate_limit_seconds` | `1.1` | Minimum gap between MusicBrainz requests |
| `output_template` | `{artist}/{year} - {album}/{track} - {title}.mp3` | Output path template |
| `supported_extensions` | `.mp3,.flac,.ogg,.m4a,.wav,...` | Audio file extensions to process |

---

## Output Structure

```
Output/
└── Artist Name/
    └── 2006 - Album Name/
        ├── 01 - Track Title.mp3
        ├── 02 - Track Title.flac
        └── cover.jpg
```

---

## License

MIT
