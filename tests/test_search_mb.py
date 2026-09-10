#!/usr/bin/env python3
"""Integration tests for MusicBrainz search_mb album-centric behavior."""

from __future__ import annotations

from unittest.mock import patch

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
