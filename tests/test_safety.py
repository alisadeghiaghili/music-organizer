#!/usr/bin/env python3
"""Safety tests: dry-run purity, source immutability, merge sidecars, journal.

These tests encode the Phase A contract:
  - dry_run must not mutate any file on disk
  - copy mode must not rewrite tags on the source file
  - merge must not delete non-audio sidecar files
  - journal must record each filesystem mutation
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from mutagen.id3 import ID3

from music_core import (
    merge_duplicate_albums,
    process_file,
    read_tags,
)


MB_OK = {
    "title": "Test Song",
    "artist": "Test Artist",
    "album": "Test Album",
    "year": "2024",
    "track": "1",
    "disc": "",
    "total_tracks": "10",
    "disc_total": "",
    "genres": ["Rock"],
    "label": "",
    "composer": "",
    "release_id": "rel-1",
}


def _read_id3_raw(path: str) -> dict[str, str]:
    """Return a stable snapshot of ID3 text frames for mutation comparison."""
    try:
        tags = ID3(path)
    except Exception:
        return {}
    snap: dict[str, str] = {}
    for key in tags.keys():
        frame = tags[key]
        text = getattr(frame, "text", None)
        if text:
            snap[key] = str(text[0])
    return snap


def _opts(**overrides) -> dict:
    base = {
        "copy": True,
        "acoustid": False,
        "write_tags": True,
        "overwrite": False,
        "dry_run": False,
        "fetch_art": False,
        "fetch_lyrics": False,
        "overwrite_art": False,
        "write_to_source": False,
        "journal": True,
    }
    base.update(overrides)
    return base


@pytest.fixture
def mb_mock():
    with patch("music_core.search_mb", return_value=dict(MB_OK)), \
         patch("music_core.acoustid_lookup", return_value=None), \
         patch("music_core.lastfm_genres", return_value=[]), \
         patch("music_core.fetch_lyrics", return_value=(None, None)), \
         patch("music_core.fetch_cover_art", return_value=None), \
         patch("music_core.find_fpcalc", return_value=None):
        yield


class TestDryRunPurity:
    """dry_run=True must leave the filesystem byte-identical for the source."""

    def test_dry_run_does_not_write_source_tags(self, sample_mp3, output_dir, mb_mock):
        before = _read_id3_raw(sample_mp3)
        mtime_before = os.path.getmtime(sample_mp3)

        stats = {"ok": 0, "skipped": 0, "errors": 0}
        meta, source, status, dest = process_file(
            sample_mp3, output_dir, _opts(dry_run=True), stats
        )

        assert status == "dry-run"
        after = _read_id3_raw(sample_mp3)
        assert after == before, (
            "dry_run must not rewrite source tags. "
            f"before={before!r} after={after!r}"
        )
        assert os.path.getmtime(sample_mp3) == mtime_before

    def test_dry_run_creates_no_output_tree(self, sample_mp3, output_dir, mb_mock):
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        process_file(sample_mp3, output_dir, _opts(dry_run=True), stats)

        created = [p for p in Path(output_dir).rglob("*")]
        assert created == [], f"dry_run created filesystem entries: {created}"

    def test_dry_run_does_not_create_journal_file(self, sample_mp3, output_dir, mb_mock):
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        process_file(sample_mp3, output_dir, _opts(dry_run=True, journal=True), stats)

        journal = Path(output_dir) / "organize-journal.jsonl"
        assert not journal.exists()


class TestSourceImmutability:
    """Copy mode must never rewrite tags on the original file."""

    def test_copy_mode_leaves_source_tags_untouched(self, sample_mp3, output_dir, mb_mock):
        before = _read_id3_raw(sample_mp3)
        mtime_before = os.path.getmtime(sample_mp3)
        # Same album → confident match → a buggy writer would rewrite source.
        mb = dict(MB_OK)
        mb["title"] = "Renamed By MB"
        mb["label"] = "Some Label"

        with patch("music_core.search_mb", return_value=mb):
            stats = {"ok": 0, "skipped": 0, "errors": 0}
            meta, source, status, dest = process_file(
                sample_mp3, output_dir, _opts(), stats
            )

        assert status == "ok"
        after = _read_id3_raw(sample_mp3)
        assert after == before, (
            "copy mode mutated the source file. "
            f"before={before!r} after={after!r}"
        )
        assert os.path.getmtime(sample_mp3) == mtime_before

    def test_copy_mode_writes_tags_on_destination(self, sample_mp3, output_dir, mb_mock):
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        meta, source, status, dest = process_file(
            sample_mp3, output_dir, _opts(), stats
        )
        assert status == "ok"
        assert Path(dest).exists()
        dest_tags = read_tags(dest)
        assert dest_tags["title"] == "Test Song"
        assert dest_tags["album"] == "Test Album"
        assert dest_tags["artist"] == "Test Artist"


class TestMergeSidecars:
    """merge_duplicate_albums must not rmtree sidecar files."""

    def _make_album(
        self, root: Path, artist: str, album: str, *, sidecar: str | None = None
    ) -> Path:
        album_dir = root / artist / album
        album_dir.mkdir(parents=True)
        (album_dir / "01 - Song.mp3").write_bytes(b"\x00" * 8)
        (album_dir / "rip.cue").write_text('FILE "audio.wav" WAVE\n')
        (album_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        if sidecar:
            (album_dir / sidecar).write_text(f"unique:{sidecar}\n")
        return album_dir

    def test_merge_preserves_non_audio_files(self, tmp_dir):
        root = Path(tmp_dir) / "out"
        root.mkdir()
        self._make_album(root, "Artist", "Album", sidecar="loser-only.nfo")
        self._make_album(root, "Artist", "2020 - Album")

        merge_duplicate_albums(str(root))

        winner = root / "Artist" / "2020 - Album"
        assert winner.exists()
        assert (winner / "rip.cue").exists(), "merge deleted .cue sidecar"
        assert (winner / "loser-only.nfo").exists(), (
            "merge deleted unique sidecar from loser folder"
        )
        assert (winner / "cover.jpg").exists()

    def test_merge_leaves_no_empty_loser_dir(self, tmp_dir):
        root = Path(tmp_dir) / "out"
        root.mkdir()
        loser = root / "Artist" / "Album"
        loser.mkdir(parents=True)
        # Only unique names so every file can be absorbed without conflicts.
        (loser / "02 - Bonus.mp3").write_bytes(b"\x01" * 8)
        (loser / "only-in-loser.nfo").write_text("unique\n")
        self._make_album(root, "Artist", "2020 - Album")

        merge_duplicate_albums(str(root))

        assert not loser.exists()
        dirs = {p.name for p in (root / "Artist").iterdir() if p.is_dir()}
        assert dirs == {"2020 - Album"}
        winner = root / "Artist" / "2020 - Album"
        assert (winner / "02 - Bonus.mp3").exists()
        assert (winner / "only-in-loser.nfo").exists()

    def test_merge_keeps_loser_when_name_conflicts_remain(self, tmp_dir):
        """If winner already has the same filenames, do not rmtree the loser."""
        root = Path(tmp_dir) / "out"
        root.mkdir()
        loser = self._make_album(root, "Artist", "Album")
        self._make_album(root, "Artist", "2020 - Album")
        # Extra file only in loser with a name that also exists in winner? No —
        # use identical layout; all moves skip; loser must survive.
        merge_duplicate_albums(str(root))
        assert loser.exists(), "rmtree removed a folder that still held skipped files"


class TestJournal:
    """Filesystem mutations must be journaled when journal is enabled."""

    def test_journal_created_on_copy(self, sample_mp3, output_dir, mb_mock):
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        process_file(sample_mp3, output_dir, _opts(journal=True), stats)

        journal = Path(output_dir) / "organize-journal.jsonl"
        assert journal.exists(), "journal file was not created"
        lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
        actions = {entry.get("action") for entry in lines}
        assert "copy" in actions or "tag" in actions
        for entry in lines:
            assert "ts" in entry
            assert "src" in entry or "dst" in entry

    def test_journal_disabled_writes_nothing(self, sample_mp3, output_dir, mb_mock):
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        process_file(sample_mp3, output_dir, _opts(journal=False), stats)
        journal = Path(output_dir) / "organize-journal.jsonl"
        assert not journal.exists()
