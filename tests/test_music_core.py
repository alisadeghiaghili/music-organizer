#!/usr/bin/env python3
"""Tests for music_core.py — core functionality."""

import os
import sys
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from music_core import (
    safe, normalize_album_key, normalize_artist_key, folder_score, destination,
    collect_audio_files, collect_mp3s, read_tags,
    strip_track_prefix, merge_duplicate_artists, _clean_title,
)


class TestSafeFilename:
    def test_strips_illegal_chars(self):
        # Each illegal char is replaced individually with _
        result = safe('Hello<>:"/\\|?*World')
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert result.startswith("Hello")
        assert result.endswith("World")

    def test_strips_leading_trailing_dots(self):
        assert safe("..hello..") == "hello"

    def test_empty_becomes_unknown(self):
        assert safe("") == "Unknown"

    def test_max_length(self):
        result = safe("A" * 100, maxlen=20)
        assert len(result) == 20

    def test_unicode_preserved(self):
        result = safe("日本語テスト")
        assert "日本語テスト" in result

    def test_spaces_trimmed(self):
        assert safe("  hello  ") == "hello"


class TestNormalizeAlbumKey:
    def test_strips_year_prefix(self):
        assert normalize_album_key("2020 - My Album") == "myalbum"

    def test_lowercases(self):
        assert normalize_album_key("The Beatles") == "thebeatles"

    def test_removes_non_alphanumeric(self):
        assert normalize_album_key("Album (Deluxe)") == "albumdeluxe"

    def test_no_year(self):
        assert normalize_album_key("Greatest Hits") == "greatesthits"


class TestNormalizeArtistKey:
    def test_brackets_do_not_split_artist(self):
        assert normalize_artist_key("Shajarian") == normalize_artist_key("Shajarian (فرض)")

    def test_case_space_insensitive(self):
        assert normalize_artist_key("Metallica") == normalize_artist_key(" metallica ")

    def test_distinct_artists(self):
        assert normalize_artist_key("Raha Derakhsh") != normalize_artist_key("Raha")


class TestStripTrackPrefix:
    def test_dashes(self):
        assert strip_track_prefix("01 - Song") == "Song"
        assert strip_track_prefix("1 - Song") == "Song"

    def test_dot_and_paren(self):
        assert strip_track_prefix("3. Intro") == "Intro"
        assert strip_track_prefix("12) Outro") == "Outro"

    def test_em_dash(self):
        assert strip_track_prefix("07 — Title") == "Title"

    def test_leading_number_without_separator_kept(self):
        # A title that just starts with a number is left alone.
        assert strip_track_prefix("8 Mile") == "8 Mile"
        assert strip_track_prefix("1969") == "1969"

    def test_idempotent_and_empty(self):
        assert strip_track_prefix("") == ""
        once = strip_track_prefix("01 - Song")
        assert strip_track_prefix(once) == "Song"


class TestFolderScore:
    def test_with_year_prefix(self):
        assert folder_score("2020 - Album") == 1

    def test_without_year_prefix(self):
        assert folder_score("Album Name") == 0


class TestDestination:
    def test_basic_mp3(self, tmp_dir):
        meta = {
            "artist": "Test Artist",
            "album": "Test Album",
            "year": "2024",
            "track": "1",
            "title": "Song One",
            "_extension": ".mp3",
        }
        result = destination(tmp_dir, meta)
        assert result.name == "01 - Song One.mp3"
        assert "Test Artist" in str(result)
        assert "2024 - Test Album" in str(result)

    def test_flac_preserves_extension(self, tmp_dir):
        meta = {
            "artist": "Test Artist",
            "album": "Test Album",
            "year": "2024",
            "track": "1",
            "title": "Flac Song",
            "_extension": ".flac",
        }
        result = destination(tmp_dir, meta)
        assert result.suffix == ".flac"

    def test_no_year_folder(self, tmp_dir):
        meta = {
            "artist": "Artist",
            "album": "Album",
            "year": "",
            "track": "1",
            "title": "Song",
            "_extension": ".mp3",
        }
        result = destination(tmp_dir, meta)
        assert "Album" in str(result)
        assert " - " not in result.parent.name  # no " - " without year

    def test_unknown_fallbacks(self, tmp_dir):
        meta = {"_extension": ".mp3"}
        result = destination(tmp_dir, meta)
        assert "Unknown Artist" in str(result)
        assert "Unknown Album" in str(result)
        assert "Unknown Title" in result.name

    def test_track_padding(self, tmp_dir):
        meta = {
            "artist": "A", "album": "B", "year": "2024",
            "track": "5", "title": "Song", "_extension": ".mp3",
        }
        result = destination(tmp_dir, meta)
        assert result.name.startswith("05 -")


class TestCleanTitle:
    """_clean_title strips aggregator watermarks / stray brackets but keeps real
    names and legit parentheticals."""

    def test_removes_domain_watermark_bracket(self):
        assert _clean_title("Khor Ava [SevilMusic.Com]") == "Khor Ava"

    def test_unwraps_name_and_removes_watermark(self):
        assert _clean_title("[Royaye Man] ~[SevilMusic.Com]~") == "Royaye Man"

    def test_unwraps_bracketed_artist(self):
        assert _clean_title("[Salar Aghili]") == "Salar Aghili"

    def test_drops_stray_tildes(self):
        # '~' separators are removed and spaces collapsed.
        assert _clean_title("Song ~ y") == "Song y"

    def test_keeps_non_wrapped_qualifier(self):
        # A bracket that is NOT the whole value (a qualifier) is left alone.
        assert _clean_title("Song (Remix)") == "Song (Remix)"

    def test_keeps_clean_value(self):
        assert _clean_title("Khor Ava") == "Khor Ava"

    def test_preserves_feat_credit_and_edition(self):
        # 'feat. X' (dot + space) and '(Remix)' are not watermarks.
        assert _clean_title("Artist feat. X") == "Artist feat. X"
        assert _clean_title("Song (Remix)") == "Song (Remix)"

    def test_never_empties_noise_only_input(self):
        assert _clean_title("[SevilMusic.Com]") == "[SevilMusic.Com]"

    def test_empty_passes_through(self):
        assert _clean_title("") == ""
        assert _clean_title(None) is None


class TestCollectAudioFiles:
    def test_finds_mp3_files(self, tmp_dir):
        for name in ["a.mp3", "b.flac", "c.ogg", "d.txt", "e.jpg"]:
            Path(tmp_dir, name).touch()
        files = collect_audio_files(tmp_dir)
        basenames = [os.path.basename(f) for f in files]
        assert "a.mp3" in basenames
        assert "b.flac" in basenames
        assert "c.ogg" in basenames
        assert "d.txt" not in basenames
        assert "e.jpg" not in basenames

    def test_recursive(self, tmp_dir):
        sub = os.path.join(tmp_dir, "sub")
        os.makedirs(sub)
        Path(sub, "nested.mp3").touch()
        files = collect_audio_files(tmp_dir)
        assert any("nested.mp3" in f for f in files)

    def test_collect_mp3s_is_alias(self, tmp_dir):
        Path(tmp_dir, "test.mp3").touch()
        assert collect_mp3s(tmp_dir) == collect_audio_files(tmp_dir)


class TestReadTags:
    def test_read_mp3_tags(self, sample_mp3):
        tags = read_tags(sample_mp3)
        assert tags["title"] == "Test Song"
        assert tags["artist"] == "Test Artist"
        assert tags["album"] == "Test Album"
        assert tags["year"] == "2024"
        assert tags["track"] == "1"
        assert tags["total_tracks"] == "10"
        assert "Rock" in tags["genres"]

    def test_read_tags_strips_track_prefix_from_title(self, tmp_dir):
        """A leading 'NN -' in the title tag must be stripped at read time, so
        the scan view (and MB queries) never show the redundant prefix."""
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK
        path = str(Path(tmp_dir) / "03 - Song.mp3")
        tags = ID3()
        tags.add(TIT2(encoding=3, text=["03 - Song"]))
        tags.add(TPE1(encoding=3, text=["Artist"]))
        tags.add(TALB(encoding=3, text=["Album"]))
        tags.add(TRCK(encoding=3, text=["3/10"]))
        tags.save(path)
        frame = bytes([0xFF, 0xFB, 0x90, 0x00]) + b"\x00" * 413
        with open(path, "ab") as f:
            f.write(frame * 3)

        got = read_tags(path)
        assert got["title"] == "Song"
        assert got["track"] == "3"

    def test_read_nonexistent_file(self):
        tags = read_tags("/nonexistent/file.mp3")
        assert tags["title"] == ""
        assert tags["artist"] == ""
        assert tags["has_art"] is False

    def test_read_flac_tags(self, sample_flac):
        """FLAC tag reading — verifies read_tags doesn't crash on FLAC files."""
        tags = read_tags(sample_flac)
        # The manually-constructed FLAC binary may not be fully parseable by mutagen
        # but read_tags should not crash — it should return a valid dict
        assert isinstance(tags, dict)
        assert "title" in tags
        assert "artist" in tags
        assert "genres" in tags

    def test_read_ogg_tags(self, sample_ogg):
        tags = read_tags(sample_ogg)
        assert tags["title"] == "Ogg Song"
        assert tags["artist"] == "Ogg Artist"
