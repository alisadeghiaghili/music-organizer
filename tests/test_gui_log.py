#!/usr/bin/env python3
"""Tests for the log-line colouring logic (pure, no display required).

``_log_tag`` maps a log message to a colour tag by its leading marker. These
tests pin the mapping so a colour regression (e.g. a success line falling back
to the default grey) is caught without a display.
"""

import music_organizer_gui as g


class TestLogTag:
    def test_success_lines_are_green(self):
        assert g._log_tag("  ✓ Identified: Artist — Title") == "ok"
        assert g._log_tag("  ✓ Album art fetched (120 KB)") == "ok"
        assert g._log_tag("  ✓ Genres found: Rock, Pop") == "ok"

    def test_lyrics_found_is_success(self):
        assert g._log_tag("  📝 Lyrics found") == "ok"

    def test_in_progress_lines_are_info(self):
        assert g._log_tag("  ⟳ Fingerprinting audio…") == "info"
        assert g._log_tag("  🖼 Fetching album art…") == "info"

    def test_scanned_summary_is_info(self):
        assert g._log_tag("Scanned 'C:\\Music' — 42 audio file(s) found") == "info"

    def test_written_file_is_accent(self):
        assert g._log_tag("  → C:\\Music\\Artist\\Album\\01 - Song.flac") == "acc"

    def test_dry_run_destination_is_accent(self):
        assert g._log_tag("  [DRY] → C:\\Music\\Artist\\Album\\01 - Song.flac") == "acc"

    def test_warnings_are_amber(self):
        assert g._log_tag("  ⚠ Fingerprinting unavailable — using basic lookup") == "warn"
        assert g._log_tag("  ⚠ Album art not found in Cover Art Archive") == "warn"
        assert g._log_tag("  ! Tag write failed: PermissionError") == "warn"

    def test_errors_are_red(self):
        assert g._log_tag("  ✗ Could not identify — using existing tags") == "err"
        assert g._log_tag("  ✗ Error: boom") == "err"

    def test_skipped_and_kept_are_muted(self):
        assert g._log_tag("  ↷ Skipped (exists): 01 - Song.flac") == "muted"
        assert g._log_tag("  — No lyrics available") == "muted"
        assert g._log_tag("  ~ Keeping existing artist: Someone") == "muted"

    def test_merge_summary_is_success(self):
        assert g._log_tag("  ✅ Merged 3 duplicate album folder(s)") == "ok"

    def test_unknown_lines_fall_back_to_text(self):
        assert g._log_tag("Stopping…") == "warn"
        assert g._log_tag("some random line with no marker") == "text"

    def test_leading_whitespace_is_ignored(self):
        # Messages arrive indented; the tag must not depend on the indentation.
        assert g._log_tag("   ✓ Identified: A — B") == "ok"
