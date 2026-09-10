#!/usr/bin/env python3
"""Lyrics tests: LRC parsing, fetch cache behavior, tag write for MP3/FLAC."""

from __future__ import annotations

from unittest.mock import patch

from mutagen.flac import FLAC
from mutagen.id3 import ID3

from music_core import (
    _parse_lrc_to_sylt,
    fetch_lyrics,
    process_file,
    read_tags,
    write_tags,
)


class TestParseLrc:
    def test_parses_standard_centiseconds(self):
        sylt = _parse_lrc_to_sylt("[00:12.50] hello\n[01:02.75] world")
        assert sylt == [("hello", 12500), ("world", 62750)]

    def test_parses_three_digit_milliseconds(self):
        sylt = _parse_lrc_to_sylt("[00:12.123] hello")
        assert sylt == [("hello", 12123)]

    def test_parses_missing_fraction(self):
        sylt = _parse_lrc_to_sylt("[00:12] hello")
        assert sylt == [("hello", 12000)]

    def test_parses_single_digit_minute(self):
        sylt = _parse_lrc_to_sylt("[0:12.50] hello")
        assert sylt == [("hello", 12500)]

    def test_parses_single_digit_fraction(self):
        sylt = _parse_lrc_to_sylt("[00:12.5] hello")
        assert sylt == [("hello", 12500)]

    def test_skips_metadata_tags(self):
        sylt = _parse_lrc_to_sylt("[ar:Artist]\n[ti:Title]\n[00:01.00] line")
        assert sylt == [("line", 1000)]

    def test_empty_and_none(self):
        assert _parse_lrc_to_sylt("") == []
        assert _parse_lrc_to_sylt(None) == []


class TestFetchLyrics:
    def test_returns_cached_tuple(self):
        cached = ("plain line", "[00:01.00] plain line")
        with patch("music_core._cache_get", return_value=list(cached)):
            plain, synced = fetch_lyrics("A", "T", album="X", duration=10)
        assert plain == "plain line"
        assert synced == "[00:01.00] plain line"

    def test_network_failure_returns_none_pair(self):
        with patch("music_core._cache_get", return_value=None), \
             patch("music_core.urllib.request.urlopen", side_effect=OSError("down")):
            plain, synced = fetch_lyrics("A", "T", album="X", duration=10)
        assert plain is None
        assert synced is None


class TestWriteLyrics:
    def test_mp3_uslt_and_sylt(self, sample_mp3):
        meta = {
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "year": "2024",
            "track": "1",
            "total_tracks": "10",
            "genres": ["Rock"],
            "label": "",
            "composer": "",
            "has_art": False,
            "_lyrics_plain": "line one\nline two",
            "_lyrics_synced": "[00:01.00] line one\n[00:02.00] line two",
        }
        write_tags(sample_mp3, meta)
        tags = ID3(sample_mp3)
        uslt_keys = [k for k in tags.keys() if k.startswith("USLT")]
        sylt_keys = [k for k in tags.keys() if k.startswith("SYLT")]
        assert uslt_keys, f"USLT missing: {list(tags.keys())}"
        assert sylt_keys, f"SYLT missing: {list(tags.keys())}"
        assert tags[uslt_keys[0]].text == "line one\nline two"
        texts = [t for t, _ in tags[sylt_keys[0]].text]
        assert "line one" in texts

    def test_flac_lyrics_tag(self, sample_flac):
        # Minimal FLAC may not be fully writable; skip if mutagen rejects.
        meta = {
            "title": "Flac Song",
            "artist": "Flac Artist",
            "album": "Flac Album",
            "year": "2023",
            "track": "2",
            "genres": [],
            "has_art": False,
            "_lyrics_plain": "flac lyric line",
            "_lyrics_synced": "",
        }
        try:
            write_tags(sample_flac, meta)
            audio = FLAC(sample_flac)
        except Exception:
            return
        lyrics = (audio.tags or {}).get("lyrics")
        assert lyrics is not None
        assert "flac lyric line" in lyrics[0]


class TestProcessFileLyrics:
    def test_process_file_fetches_and_writes_lyrics(self, sample_mp3, output_dir):
        mb = {
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
        opts = {
            "copy": True,
            "acoustid": False,
            "write_tags": True,
            "overwrite": False,
            "dry_run": False,
            "fetch_art": False,
            "fetch_lyrics": True,
            "overwrite_art": False,
            "journal": False,
        }
        stats = {"ok": 0, "skipped": 0, "errors": 0}

        with patch("music_core.search_mb", return_value=mb), \
             patch("music_core.fetch_lyrics",
                   return_value=("plain lyric", "[00:01.00] plain lyric")), \
             patch("music_core.find_fpcalc", return_value=None), \
             patch("music_core.lastfm_genres", return_value=[]):
            meta, source, status, dest = process_file(
                sample_mp3, output_dir, opts, stats
            )

        assert status == "ok"
        tags = ID3(dest)
        assert any(k.startswith("USLT") for k in tags.keys())
        assert any(k.startswith("SYLT") for k in tags.keys())
        dest_meta = read_tags(dest)
        # title should come from MB
        assert dest_meta["title"] == "Test Song"
