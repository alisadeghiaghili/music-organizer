#!/usr/bin/env python3
"""Tests for the single GUI palette (no display required)."""

import music_organizer_gui as g

# Keys the app actually reads from the palette (a missing key would break a
# widget at build time, so the palette must define each of them).
REQUIRED_KEYS = (
    "bg", "surface", "surface2", "fg", "muted",
    "accent", "accent_hover", "accent_text",
    "ok", "warn", "err", "info",
    "btn_secondary", "btn_secondary_hover", "btn_secondary_press",
    "btn_danger", "btn_danger_hover", "disabled_fill",
    "trough", "sel", "zebra",
    "toggle_off", "dot_off",
    "banner_bg", "banner_fg", "banner_sub", "banner_bar",
)

_HEX = set("0123456789abcdefABCDEF")


def _is_hex(value):
    return (isinstance(value, str) and value.startswith("#")
            and len(value) == 7 and all(c in _HEX for c in value[1:]))


class TestPalette:
    def test_has_all_required_keys(self):
        missing = [k for k in REQUIRED_KEYS if k not in g.PALETTE]
        assert not missing, f"PALETTE missing keys: {missing}"

    def test_all_values_are_valid_hex_colors(self):
        bad = {k: v for k, v in g.PALETTE.items() if not _is_hex(v)}
        assert not bad, f"invalid hex colors: {bad}"

    def test_single_theme_is_used_for_building(self):
        # The app is single-theme: widgets are built from PALETTE and never
        # recoloured at runtime, so the palette must be a concrete (not a
        # nested) dict of colours.
        assert isinstance(g.PALETTE, dict)
        assert all(isinstance(v, str) for v in g.PALETTE.values())
