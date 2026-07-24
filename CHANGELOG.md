# Changelog

All notable changes to this project are documented here.

---

## [2.1.0] — 2026-07-24

### Added

- **Lyrics fetching** — LRCLIB integration (free, no API key) fetches synced LRC lyrics and plain text lyrics
- **Lyrics written to files** — USLT/SYLT ID3 frames for MP3, `lyrics` Vorbis tag for FLAC/OGG, `\xa9lyr` for MP4
- **Cover art for all formats** — FLAC (METADATA_BLOCK_PICTURE), OGG (base64 METADATA_BLOCK_PICTURE), MP4 (covr atom)
- **`--no-lyrics` CLI flag** — skip lyrics fetching
- **Fetch lyrics option** — available in GUI checkbox and CLI interactive mode
- **`_is_confident_match()`** — smart title correction that checks release_id + title/album consistency before overwriting

### Fixed

- **Album detection** — removed exact-match quotes from MusicBrainz queries for fuzzy matching; studio albums now preferred over compilations
- **Multi-disc track lookup** — searches all media to find which disc contains the matched recording (was only reading disc 1)
- **Title correction too aggressive** — now checks confidence before overwriting existing non-empty tags; logs when keeping existing values
- **Cover art overwrite** — `save_folder_cover()` now supports overwrite parameter; folder cover.jpg updates when `overwrite_art` is set
- **Destructive tag clearing** — FLAC/OGG writers no longer call `tags.clear()` which wiped all Vorbis comments; now only updates managed keys
- **Cover art fetching** — always fetches art when release_id is known (was skipping files that already had embedded art)

---

## [2.0.0] — 2026-07-24

### Added

- **Multi-format support** — MP3, FLAC, OGG/Vorbis, M4A/MP4, WAV, AIFF, Opus, APE, WMA (previously MP3-only)
- **Centralized configuration** — `config.py` with `~/.music-organizer/config.json` and `MUSIC_ORG_*` environment variable overrides
- **Format-aware tag reading** — specialized readers for each audio format (ID3, VorbisComment, MP4Tags)
- **Format-aware tag writing** — writes metadata in the native format of each file type
- **`collect_audio_files()`** — replaces `collect_mp3s()`, discovers all supported audio formats (backward-compatible alias kept)
- **File extension preservation** — organized files keep their original format (.flac stays .flac, etc.)
- **Test suite** — 37 pytest tests covering config, tag reading, filename handling, file collection, and destination paths
- **`pyproject.toml`** — modern Python packaging configuration

### Changed

- `read_tags()` now dispatches to format-specific readers (ID3, FLAC, VorbisComment, MP4) with generic fallback
- `write_tags()` now dispatches to format-specific writers for each audio format
- `destination()` preserves original file extension instead of hardcoding `.mp3`
- All hardcoded API keys and URLs moved to `config.py` defaults
- `safe()` now reads max length from configuration
- `process_file()` injects `_extension` into metadata for downstream use

---

## [1.1.0] — 2026-06-24

### Added

- **Album art support** — downloads and embeds cover art into MP3 tags; saves `cover.jpg` in each album folder
- **Genre enrichment** — fetches genre tags from metadata databases; displayed in GUI table and CLI results
- **Last.fm genre fallback** — optional extra source for genre when the primary lookup returns none (requires API key)
- **`--no-art` / `--replace-art` CLI flags** — fine-grained control over album art behaviour
- **`fetch_art` / `overwrite_art` options** — available in both CLI interactive mode and GUI checkboxes
- **GUI: Pause / Resume / Stop** — full thread control during the organize phase
- **GUI: dual progress bars** — separate Scan bar and Organize bar
- **GUI: same-folder move warning** — prompts confirmation before reorganizing files in-place
- **GUI: fingerprinting auto-enable** — after download completes, `Deep metadata lookup` checkbox is activated automatically
- **`label`, `composer`, `disc`, `disc_total`, `total_tracks`** — all now fetched from online metadata and written to ID3 tags
- **`has_art` field in `read_tags()`** — prevents overwriting existing embedded art unless `overwrite_art` is set
- **`_mb_lock` thread lock in `mb_get()`** — prevents rate-limit collisions when GUI background threads fire simultaneously
- **Cover art archive fallback URL** — tries both `/front-large` and `/front` before giving up

### Fixed

- **`find_fpcalc()` in PyInstaller builds** — now checks `sys._MEIPASS` (temp extraction directory) before disk and PATH; fixes "fingerprinting unavailable" in `.exe` builds
- **`fpcalc_installer.py` download path** — resolved `sys.argv[0]` bug that placed the binary in the wrong directory; added `_archive_suffix` detection and `finally` cleanup for partial downloads
- **`build.bat` fpcalc bundling** — `--add-binary fpcalc.exe;.` and `--hidden-import` flags ensure the binary is correctly embedded and discovered at runtime
- **`write_tags()` now accepts `cover_bytes`** — cover art is embedded in the same tag-write pass, avoiding a second file open
- **Log filter extended** — album art fetch messages (🖼, ⚠ Album art) are suppressed from the GUI log and CLI non-verbose output

### Changed

- `search_mb()` now requests `genres+tags` in the MusicBrainz recording query and fetches full release detail (labels, genres, media) in one additional call
- `acoustid_lookup()` adds `+compress` to the meta parameter and returns `release_id` for downstream art and genre fetching
- `process_file()` now handles the full pipeline: metadata → art fetch → tag write → copy/move — all in one pass
- `read_tags()` returns a complete dict with defaults (never raises); includes `genres`, `label`, `composer`, `total_tracks`, `disc_total`, `has_art`
- `merge_duplicate_albums()` now also migrates `cover.*` image files when merging folders
- CLI and GUI log filters updated to hide internal debug prefixes (🖼, ⟳, ✓ lookup lines) unless `--verbose` is set

---

## [1.0.0] — 2026-06-01

### Added

- Initial release
- GUI (Tkinter dark theme) and CLI (Rich) frontends
- Online metadata lookup with title, artist, album, year, track enrichment
- Audio fingerprinting fallback for untagged files, with auto-installer (~2 MB)
- Duplicate album folder detection and merge
- Copy / move mode, dry-run, overwrite options
- `build.bat` — one-command Windows EXE builder via PyInstaller
- Original release year selection (oldest known release)
