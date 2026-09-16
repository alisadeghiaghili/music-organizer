# Changelog

All notable changes to this project are documented here.

---

## [2.6.2] — 2026-09-16

### Fixed

- **Songs no longer vanish into a stray `[bracket]` artist folder.** Dirty
  source tags — a bracketed artist (`[Salar Aghili]` vs `Salar Aghili`) and
  site watermarks in the title (e.g. `[Royaye Man] ~[SevilMusic.Com]~`) — used
  to split one artist's songs across two folders, so a song appeared to be
  missing. Names are now normalised before filing: site watermarks
  (`[SevilMusic.Com]`) are stripped, a name wrapped entirely in brackets is
  unwrapped (`[Royaye Man]` → `Royaye Man`), and stray `~` separators are
  dropped — while legitimate qualifiers like `(Remix)` and credits like
  `feat. X` are preserved. The same clean names are used for the MusicBrainz
  lookup, the scan view, the destination path, and the written tags.

---

## [2.6.1] — 2026-09-14

### Fixed

- **No more silent data loss on filename collisions** — two *different* files
  that normalise to the same output filename (e.g. two distinct songs of the
  same title, or two artists folded together by a loose online match) are no
  longer dropped as a false "duplicate". The second file is now written to its
  own `Name (N).ext` path so every song survives. True duplicates (identical
  bytes) are still skipped, and `--overwrite` still replaces the existing file.
- **Per-file rows are now coloured while processing** — in the webview GUI the
  row currently being organized is highlighted (amber) with a "⏳ processing…"
  status, so you can see exactly which file is in flight. Previously the row
  only updated after the file finished, so nothing looked "in progress".
- **In-page header icon renders in the frozen build** — the app icon in the UI
  header no longer depends on Pillow, which isn't bundled. The bundled PNG is
  embedded as a data URI directly, so the logo shows in the released binaries
  (it already worked in the OS window titlebar).

---

## [2.6.0] — 2026-09-14

### Added

- **Linux release builds** — the release workflow now also builds the webview
  GUI + CLI for Linux (`MusicOrganizer-Linux.tar.gz`), bringing the app to all
  three major desktop platforms. On Linux the GUI uses GTK3 + WebKit2GTK
  (pywebview's `[gtk]` backend).

### Changed

- **Cleaner header** — the in-page header shows only the version, without the
  framework name.

---

## [2.5.0] — 2026-09-14

### Added

- **New webview GUI (primary frontend)** — a modern pywebview (WebView2 on
  Windows, WKWebView on macOS) frontend replacing the Tkinter GUI as the app
  that ships in releases. Same `music_core` engine and Scan / Organize workflow,
  but a crisp web-based UI. The Tkinter frontend (`music_organizer_gui.py`)
  remains as a lightweight, dependency-free fallback.
- **Light / dark / system theming** — the webview GUI has a Light / Dark /
  System theme switcher in the header; the choice is remembered in
  `~/.music-organizer/config.json` (`theme`) and the window background is
  pre-tinted to the resolved theme so there's no flash on launch.
- **App icon everywhere** — a new vinyl-on-slate app icon (`icon.png` /
  `app.ico` / `app.icns`) is embedded in the released binaries, shown in the OS
  window titlebar, and drawn in the in-page header next to the app name.

### Changed

- **Release builds now package the webview GUI** — the Windows and macOS
  release workflows build `music_organizer_web.py` (PyInstaller) with the
  pywebview + pythonnet/PyObjC runtime bundled, so the shipped
  `MusicOrganizer-GUI` is the webview app. `fpcalc` is still embedded, and the
  CLI build is unchanged.

---

## [2.4.4] — 2026-09-14

### Fixed

- **Leading `NN -` prefix stripped at tag-read time** — 2.4.3 only cleaned the
  title in the Organize path, so the **Scan** view (and the CLI preview) still
  showed a redundant `01 -` prefix in the Title column next to the real track
  number. The strip now happens in `read_tags`, the single choke point every
  frontend reads through, so the Scan view, Organize view, CLI preview, and
  MusicBrainz queries all see a clean title and the Title / Trk columns are
  consistent.

---

## [2.4.3] — 2026-09-13

### Fixed

- **Responsive results table** — the table had no horizontal scrollbar, so the
  right-hand columns (Art, Year, Track) were unreachable whenever the window was
  narrow. A slim horizontal scrollbar is now paired with the vertical one, so
  wide tables scroll in both directions on any window size.
- **Stray characters no longer split an artist into two folders** — an artist
  whose name picked up a bracket, stray mark, or a parenthetical annotation
  (e.g. `Shajarian (فرض)` vs `Shajarian`) used to be filed under two separate
  top-level folders. The new `normalize_artist_key` folds case, spacing,
  punctuation, and bracketed annotations, so such variants collapse to one
  folder during the post-organize merge (`merge_duplicate_artists`).
- **Duplicated track numbers in filenames** — a title tag (or a ripped filename
  stem) that already carried a leading `01 -` prefix produced a doubled number
  in the output name (`03 - 03 - Song.mp3`). The redundant prefix is now
  stripped; the filename is always `NN - Title` where `NN` is the real album
  track number from the `TRACK` tag.

### Added

- **Browse buttons on both folder rows** — the Source and Output folder fields
  each now have a Browse button, so you can pick either folder without
  retyping its path.
- **Standalone GUI in releases** — in addition to the per-platform zips, the
  release workflow now also attaches the bare, unzipped GUI binary
  (`MusicOrganizer-GUI.exe` on Windows, `MusicOrganizer-GUI` on macOS) so you
  can grab the GUI without unzipping.
- **Tests** — `normalize_artist_key` and `strip_track_prefix` coverage in
  `test_matching.py` / `test_music_core.py`, plus `merge_duplicate_artists`
  safety tests and an end-to-end no-double-prefix check in `test_safety.py`.

---

## [2.4.2] — 2026-09-13

### Changed

- **Single "slate" theme** — the GUI dropped light/dark theme switching for one
  hand-picked cool-gray palette. Theme-switching caused a Tk background-repaint
  glitch on some scaled displays; with a single theme every widget is built once
  and never recoloured at runtime, so the glitch can't occur.
- **Card alignment** — the folder, option, and log panels now share common
  left/right edges, and the two option cards sit in a regular 12px gutter.
- **Slim, flat scrollbars** — custom `Slim` ttk scrollbar style removes the
  default arrow buttons and 3-D look (table + log); the log's legacy
  `ScrolledText` 3-D bar was replaced with a `tk.Text` + flat `ttk.Scrollbar`.

### Added

- **Native horizontal table scrolling** — the cluttering bottom scrollbar is
  gone; wide columns scroll via mouse wheel over the table, Shift+wheel,
  touchpad pan, or ←/→.
- **Rotating empty-state** — the idle results table shows a rotating stage-side
  one-liner that clears as soon as rows appear.
- **Art-found status** — the table's "Art" column now reflects whether album art
  was actually found during organize (not just whether it was attempted).
- **Cross-platform release builds** — a GitHub Actions workflow builds the
  standalone GUI + CLI for Windows (`.exe`) and macOS and attaches them to each
  release; `fpcalc` is embedded so fingerprinting works out of the box.
- **Tests** — `test_gui_theme.py` (palette shape), `test_gui_log.py` (log colour
  mapping), `test_gui_sort.py` (header sort), and `test_entry_points.py`
  (installed scripts resolve).

### Fixed

- **Stuck hover highlight** — a `<Leave>` event dropped while a modal folder
  picker is open could leave a button stuck in its hover/press colour; hover
  state is now re-derived from the real pointer position on motion and on
  window focus return.

---

## [2.4.1] — 2026-09-13

### Fixed

- **fpcalc auto-download** — the in-app "Enable fingerprinting" download pointed at the dead `acoustid.org/files/chromaprint/...` path (HTTP 404), so enabling audio fingerprinting always failed partway through the download. URLs now come from the live GitHub release assets.
- **fpcalc version** — bumped the downloaded binary to `1.6.1`; `fpcalc_installer.FPCALC_VERSION` is the single source of truth and the documented `config.fpcalc_urls` mirror was updated to match (and the non-existent `windows-arm64` / `linux-armv7hf` entries removed).

### Added

- **`tests/test_fpcalc_installer.py`** — offline regression tests that pin the fpcalc download URL shape and fail if a URL regresses to the dead `acoustid.org/files` host.

---

## [2.4.0] — 2026-07-24

### Fixed

- **LRC timestamp parser** — accepts `[MM:SS]`, `[M:SS]`, `[MM:SS.x]`, `[MM:SS.xx]`, `[MM:SS.xxx]` (previously only `[MM:SS.xx|xxx]`)
- Synced lyrics now survive common LRCLIB / player timestamp variants and are sorted by time

### Added

- **`tests/test_lyrics.py`** — LRC parse matrix, cache hit/miss, MP3 USLT+SYLT write, FLAC lyrics tag, end-to-end `process_file` lyric write
- **`music_organizer` package skeleton** — `__version__` single-sourced in `__about__.py`; `domain.matching` extracted; root `matching.py` kept as compatibility shim
- **Packaging** — correct `setuptools.build_meta` backend (was broken `_legacy:_Backend`)

### Changed

- CLI `--version` reads `music_organizer.__version__`

---

## [2.3.0] — 2026-07-24

### Added

- **`matching.py`** — pure, typed helpers for recording/release scoring and Unicode album keys
- **Album-centric MusicBrainz search** — scores up to 10 recording candidates; falls back when the album-constrained query misses
- **Release policy** — prefers the user's album title, then studio albums, then the **oldest** release year (matches README)
- **Acceptance thresholds** — `recording_min_score=0.82`, `album_min_score=55.0` (config keys reserved)

### Fixed

- **Release year policy** — no longer prefers the newest remaster; oldest studio album wins
- **Track numbers are never fabricated** — `media[0].track[0]` fallback removed; track stays empty unless the recording id matches
- **`normalize_album_key` is Unicode-safe** — Persian/Arabic/CJK album names no longer collapse into one empty merge bucket
- **Lucene query escaping** — quotes and special characters in artist/title/album terms

### Tests

- `tests/test_matching.py` — release policy, recording score, Unicode keys
- `tests/test_search_mb.py` — oldest studio, no fake track, album-query fallback, best-of-N candidates

---

## [2.2.0] — 2026-07-24

### Fixed (data-safety)

- **`--preview` / `dry_run` is side-effect free** — no longer writes tags, covers, copies, merges, or journal entries. Previously tags were written to source files *before* the dry-run check.
- **Source files are never tag-rewritten** — enriched metadata is written only to the destination after copy/move.
- **Album merge preserves sidecars** — `.cue`, `.log`, `.nfo`, and any other non-audio files are moved with the album; `rmtree` only runs after a fully absorbed folder. Name conflicts keep the loser folder instead of deleting data.

### Added

- **Journal** — `organize-journal.jsonl` in the output root records `copy` / `move` / `tag` / `merge` / `skip` actions (disable with `opts['journal']=False`).
- **Safety test suite** (`tests/test_safety.py`) — dry-run purity, source immutability, merge sidecars, journal.

### Changed

- GUI tooltip for “Keep originals” now matches actual copy/move behavior (was inverted).

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
