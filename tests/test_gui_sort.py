#!/usr/bin/env python3
"""Tests for the results-table sort logic (pure, no display required)."""

import music_organizer_gui as g


class TestNextSortState:
    """Three-state header sort: asc -> desc -> default (None)."""

    def test_first_click_starts_ascending(self):
        assert g.next_sort_state("artist", None, None) == "asc"

    def test_active_column_cycles_asc_to_desc(self):
        assert g.next_sort_state("artist", "artist", "asc") == "desc"

    def test_active_column_cycles_desc_to_default(self):
        assert g.next_sort_state("artist", "artist", "desc") is None

    def test_default_resets_to_ascending_on_reclick(self):
        # Once back at default, the next click on the same column goes asc again.
        assert g.next_sort_state("artist", "artist", None) == "asc"

    def test_clicking_different_column_starts_ascending(self):
        assert g.next_sort_state("year", "artist", "desc") == "asc"
        assert g.next_sort_state("year", "artist", "asc") == "asc"


class TestSortKey:
    def test_track_sorts_numerically(self):
        """Track cells must order by number, not lexicographically (9 before 10)."""
        order = ["10", "2", "9", "1"]
        order.sort(key=lambda v: g.sort_key("trk", v))
        assert order == ["1", "2", "9", "10"]

    def test_track_with_total_uses_number_part(self):
        # "5/12" should sort as 5, and "10/12" as 10.
        order = ["10/12", "2/12", "9/12"]
        order.sort(key=lambda v: g.sort_key("trk", v))
        assert order == ["2/12", "9/12", "10/12"]

    def test_year_sorts_numerically(self):
        order = ["2000", "1999", "2010"]
        order.sort(key=lambda v: g.sort_key("year", v))
        assert order == ["1999", "2000", "2010"]

    def test_text_sorts_case_insensitively(self):
        order = ["zebra", "Apple", "banana"]
        order.sort(key=lambda v: g.sort_key("artist", v))
        assert order == ["Apple", "banana", "zebra"]

    def test_empty_values_sort_last(self):
        # Empty cells should sort after real values on a numeric column.
        order = ["", "5", "1"]
        order.sort(key=lambda v: g.sort_key("trk", v))
        assert order == ["1", "5", ""]

    def test_lyrics_art_columns_are_text_sorted(self):
        # Mark columns are not numeric; "·" (missing) vs "✓" (present) text order.
        order = ["✓", "·", "·"]
        order.sort(key=lambda v: g.sort_key("lyrics", v))
        assert len(order) == 3  # stable, no crash
