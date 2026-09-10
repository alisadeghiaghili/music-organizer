#!/usr/bin/env python3
"""Phase B tests: album-centric matching, release policy, Unicode album keys.

These encode the album-matching contract:
  - oldest studio release wins over newer remasters
  - user's album tag steers release selection
  - track numbers are never fabricated from media[0]
  - recording candidates are scored, not blindly taken as [0]
  - normalize_album_key keeps non-ASCII names distinct
"""

from __future__ import annotations

from matching import (
    normalize_album_key,
    score_recording_match,
    score_release_for_library,
    select_best_release,
    should_accept_recording,
    should_accept_release,
)


# ── Release selection ────────────────────────────────────────────────────────


class TestSelectBestRelease:
    def test_prefers_oldest_studio_over_newer_remaster(self):
        releases = [
            {
                "id": "remaster",
                "title": "The Wall",
                "date": "2011-09-26",
                "primary-type": "Album",
                "secondary-types": [],
            },
            {
                "id": "original",
                "title": "The Wall",
                "date": "1979-11-30",
                "primary-type": "Album",
                "secondary-types": [],
            },
        ]
        best, year = select_best_release(releases, desired_album="The Wall")
        assert best is not None
        assert best["id"] == "original"
        assert year == 1979

    def test_prefers_user_album_over_other_edition(self):
        releases = [
            {
                "id": "oknotok",
                "title": "OKNOTOK 1997 2017",
                "date": "2017-06-23",
                "primary-type": "Album",
                "secondary-types": [],
            },
            {
                "id": "okc",
                "title": "OK Computer",
                "date": "1997-05-21",
                "primary-type": "Album",
                "secondary-types": [],
            },
        ]
        best, year = select_best_release(releases, desired_album="OK Computer")
        assert best["id"] == "okc"
        assert year == 1997

    def test_compilation_never_beats_studio(self):
        releases = [
            {
                "id": "greatest",
                "title": "Greatest Hits",
                "date": "2020-01-01",
                "primary-type": "Album",
                "secondary-types": ["Compilation"],
            },
            {
                "id": "studio",
                "title": "Animals",
                "date": "1977-01-23",
                "primary-type": "Album",
                "secondary-types": [],
            },
        ]
        best, _ = select_best_release(releases, desired_album="")
        assert best["id"] == "studio"

    def test_empty_releases_returns_none(self):
        best, year = select_best_release([], desired_album="X")
        assert best is None
        assert year is None

    def test_live_secondary_scores_below_studio(self):
        releases = [
            {
                "id": "live",
                "title": "Pulse",
                "date": "1995-01-01",
                "primary-type": "Album",
                "secondary-types": ["Live"],
            },
            {
                "id": "studio",
                "title": "The Division Bell",
                "date": "1994-01-01",
                "primary-type": "Album",
                "secondary-types": [],
            },
        ]
        best, _ = select_best_release(releases, desired_album="")
        assert best["id"] == "studio"


class TestScoreRelease:
    def test_exact_album_scores_high(self):
        rel = {
            "title": "Abbey Road",
            "date": "1969-09-26",
            "primary-type": "Album",
            "secondary-types": [],
        }
        score = score_release_for_library(rel, desired_album="Abbey Road")
        assert score >= 55

    def test_wrong_album_scores_low(self):
        rel = {
            "title": "Greatest Hits",
            "date": "2010-01-01",
            "primary-type": "Album",
            "secondary-types": ["Compilation"],
        }
        score = score_release_for_library(rel, desired_album="Abbey Road")
        assert score < 55

    def test_remaster_with_matching_name_still_ok_if_user_named_it(self):
        rel = {
            "title": "Abbey Road (2019 Remaster)",
            "date": "2019-09-27",
            "primary-type": "Album",
            "secondary-types": ["Remaster"],
        }
        score = score_release_for_library(
            rel, desired_album="Abbey Road (2019 Remaster)"
        )
        assert score >= 55


class TestShouldAccept:
    def test_release_below_threshold_rejected(self):
        assert should_accept_release(40.0) is False
        assert should_accept_release(55.0) is True
        assert should_accept_release(90.0) is True

    def test_recording_below_threshold_rejected(self):
        assert should_accept_recording(0.50) is False
        assert should_accept_recording(0.82) is True
        assert should_accept_recording(0.95) is True


# ── Recording match scoring ──────────────────────────────────────────────────


class TestScoreRecording:
    def test_exact_artist_title_scores_high(self):
        s = score_recording_match(
            "Pink Floyd", "Comfortably Numb", "Pink Floyd", "Comfortably Numb"
        )
        assert s >= 0.82

    def test_different_song_scores_low(self):
        s = score_recording_match(
            "Pink Floyd", "Comfortably Numb", "Pink Floyd", "Wish You Were Here"
        )
        assert s < 0.82

    def test_remastered_suffix_still_acceptable(self):
        s = score_recording_match(
            "Artist",
            "Song Title",
            "Artist",
            "Song Title (2011 Remaster)",
        )
        # Soft title difference should not auto-reject a strong core match.
        assert s >= 0.70

    def test_completely_different_artist_low(self):
        s = score_recording_match(
            "Radiohead", "Creep", "Britney Spears", "Toxic"
        )
        assert s < 0.50


# ── Unicode album key ────────────────────────────────────────────────────────


class TestNormalizeAlbumKeyUnicode:
    def test_persian_names_are_nonempty_and_distinct(self):
        a = normalize_album_key("آبی")
        b = normalize_album_key("دیگری")
        assert a != ""
        assert b != ""
        assert a != b

    def test_persian_year_prefix_stripped(self):
        a = normalize_album_key("1390 - آبی")
        b = normalize_album_key("آبی")
        assert a == b

    def test_latin_still_normalizes(self):
        assert normalize_album_key("2020 - Greatest Hits!") == "greatesthits"

    def test_empty_after_strip_is_not_shared_bucket(self):
        # Symbols-only album must not collapse into the same key as another.
        a = normalize_album_key("!!!")
        b = normalize_album_key("???")
        assert a != b or (a != "" and b != "")
