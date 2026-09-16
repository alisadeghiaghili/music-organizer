#!/usr/bin/env python3
"""Integration tests for MusicBrainz search_mb album-centric behavior."""

from __future__ import annotations

from unittest.mock import patch

import music_core
from music_core import search_mb


def _rec(id_, title, artist, releases):
    return {
        "id": id_,
        "title": title,
        "artist-credit": [{"artist": {"name": artist}}],
        "releases": releases,
    }


class TestSearchMb:
    def test_prefers_oldest_studio_release(self):
        rec = _rec(
            "r1",
            "The Wall",
            "Pink Floyd",
            [
                {
                    "id": "remaster",
                    "title": "The Wall",
                    "date": "2011-09-26",
                    "primary-type": "Album",
                    "secondary-types": [],
                    "media": [{"track": [], "track-count": 26}],
                },
                {
                    "id": "original",
                    "title": "The Wall",
                    "date": "1979-11-30",
                    "primary-type": "Album",
                    "secondary-types": [],
                    "media": [
                        {
                            "position": 1,
                            "track-count": 13,
                            "track": [
                                {
                                    "number": "3",
                                    "recording": {"id": "r1"},
                                }
                            ],
                        }
                    ],
                },
            ],
        )

        def fake_mb_get(endpoint, params, retries=1):
            if endpoint == "recording":
                return {"recordings": [rec]}
            return None

        with patch("music_core.mb_get", side_effect=fake_mb_get):
            result = search_mb("Pink Floyd", "The Wall", "The Wall")

        assert result is not None
        assert result["release_id"] == "original"
        assert result["year"] == "1979"
        assert result["track"] == "3"

    def test_does_not_fabricate_track_from_first_media_entry(self):
        rec = _rec(
            "r1",
            "Song",
            "Artist",
            [
                {
                    "id": "rel1",
                    "title": "Album",
                    "date": "1990-01-01",
                    "primary-type": "Album",
                    "secondary-types": [],
                    "media": [
                        {
                            "position": 1,
                            "track-count": 10,
                            "track": [
                                {"number": "1", "recording": {"id": "OTHER"}}
                            ],
                        }
                    ],
                }
            ],
        )

        def fake_mb_get(endpoint, params, retries=1):
            if endpoint == "recording":
                return {"recordings": [rec]}
            return None

        with patch("music_core.mb_get", side_effect=fake_mb_get):
            result = search_mb("Artist", "Song", "Album")

        assert result is not None
        # recording id does not match the only track → track must stay empty
        assert result["track"] == ""

    def test_album_query_failure_falls_back_without_album(self):
        calls = []

        def fake_mb_get(endpoint, params, retries=1):
            calls.append(params.get("query", ""))
            query = params.get("query", "")
            if "release:" in query:
                return {"recordings": []}
            rec = _rec(
                "r1",
                "Song",
                "Artist",
                [
                    {
                        "id": "rel1",
                        "title": "Album",
                        "date": "1990-01-01",
                        "primary-type": "Album",
                        "secondary-types": [],
                        "media": [],
                    }
                ],
            )
            return {"recordings": [rec]}

        with patch("music_core.mb_get", side_effect=fake_mb_get):
            result = search_mb("Artist", "Song", "Totally Wrong Album Name")

        assert result is not None
        assert len(calls) >= 2
        assert any("release:" in q for q in calls)
        assert any("release:" not in q for q in calls)

    def test_low_score_recording_rejected(self):
        rec = _rec(
            "r1",
            "Completely Different Song",
            "Other Artist",
            [],
        )

        def fake_mb_get(endpoint, params, retries=1):
            return {"recordings": [rec]}

        with patch("music_core.mb_get", side_effect=fake_mb_get):
            result = search_mb("Pink Floyd", "Comfortably Numb", "The Wall")

        assert result is None

    def test_scores_second_candidate_higher(self):
        bad = _rec("r1", "Wish You Were Here", "Pink Floyd", [])
        good = _rec("r2", "Comfortably Numb", "Pink Floyd", [])

        def fake_mb_get(endpoint, params, retries=1):
            # Intentionally return the worse match first.
            return {"recordings": [bad, good]}

        with patch("music_core.mb_get", side_effect=fake_mb_get):
            result = search_mb("Pink Floyd", "Comfortably Numb", "")

        assert result is not None
        assert result["title"] == "Comfortably Numb"


def _rel(id_, title, date, media=None, ptype="Album", sec=None):
    return {
        "id": id_,
        "title": title,
        "date": date,
        "primary-type": ptype,
        "secondary-types": sec or [],
        "media": media if media is not None else [],
    }


class TestConfigWiring:
    """The config keys that used to be declared-but-never-read must now actually
    change behaviour. Each test pushes a key past its default and checks the
    outcome flips — the flip only happens if the value is read from ``_cfg``.
    """

    def test_recording_min_score_is_read(self):
        rec = _rec("r1", "The Wall", "Pink Floyd",
                   [_rel("rel1", "The Wall", "1979-11-30")])

        def fake_mb_get(endpoint, params, retries=1):
            if endpoint == "recording":
                return {"recordings": [rec]}
            return None

        # Impossibly high bar → even a strong match is rejected. This only
        # happens if search_mb reads recording_min_score from config.
        with patch.object(music_core._cfg, "get",
                          side_effect=lambda k, d=None: 0.9999 if k == "recording_min_score" else d), \
             patch("music_core.mb_get", side_effect=fake_mb_get):
            assert search_mb("Pink Floyd", "The Wall", "The Wall") is None

    def test_prefer_oldest_release_toggles_selection(self):
        def make_rec():
            return _rec(
                "r1", "The Wall", "Pink Floyd",
                [_rel("new", "The Wall", "2011-09-26"),
                 _rel("old", "The Wall", "1990-01-01")],
            )

        def fake_mb_get(endpoint, params, retries=1):
            if endpoint == "recording":
                return {"recordings": [make_rec()]}
            return None

        def run(prefer_oldest):
            with patch.object(music_core._cfg, "get",
                              side_effect=lambda k, d=None:
                              prefer_oldest if k == "prefer_oldest_release" else d), \
                 patch("music_core.mb_get", side_effect=fake_mb_get):
                return search_mb("Pink Floyd", "The Wall", "")

        assert run(True)["release_id"] == "old"
        assert run(False)["release_id"] == "new"

    def test_album_min_score_is_read(self):
        # A release whose score sits below the default 55.0 bar: with the
        # default the album/year stay withheld (album tag is set); lowering the
        # bar must populate them.
        rec = _rec("r1", "Some Tune", "Band",
                   [_rel("rel1", "Totally Different Title", "1995-05-05")])

        def fake_mb_get(endpoint, params, retries=1):
            if endpoint == "recording":
                return {"recordings": [rec]}
            return None

        def run(album_bar):
            with patch.object(music_core._cfg, "get",
                              side_effect=lambda k, d=None:
                              album_bar if k == "album_min_score" else d), \
                 patch("music_core.mb_get", side_effect=fake_mb_get):
                return search_mb("Band", "Some Tune", "Some Tune Album")

        below_default = run(0.0)  # accept everything
        assert below_default is not None
        assert below_default["year"] == "1995"
