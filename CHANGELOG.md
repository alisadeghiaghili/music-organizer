# Changelog

All notable changes to this project are documented here.

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
