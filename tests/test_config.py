#!/usr/bin/env python3
"""Tests for config.py."""

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

# Add parent dir to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Config, get_config, DEFAULTS
from music_organizer.__about__ import __version__


class TestUserAgent:
    """The User-Agent must be a single source of truth: it embeds the release
    version from ``music_organizer.__about__.__version__`` so the API clients
    never drift from the release (the old code hardcoded 2.3/2.0/2.2)."""

    def test_user_agent_uses_release_version(self):
        assert __version__ in DEFAULTS["user_agent"]

    def test_user_agent_matches_about_version_exactly(self):
        ua = DEFAULTS["user_agent"]
        assert ua.startswith(f"MusicOrganizer/{__version__}")
        assert "github.com/alisadeghiaghili/music-organizer" in ua

    def test_no_stale_hardcoded_version(self):
        # Regression guard: none of the old drifted versions may appear.
        ua = DEFAULTS["user_agent"]
        for stale in ("2.0", "2.2", "2.3"):
            assert f"/{stale}" not in ua, f"user_agent still hardcodes {stale}"

    def test_fpcalc_installer_user_agent_uses_release_version(self):
        # The fpcalc downloader has its own UA header — it must track __version__
        # too (it previously hardcoded MusicOrganizer/2.0).
        import inspect
        import fpcalc_installer
        src = inspect.getsource(fpcalc_installer.download_fpcalc)
        assert "__version__" in src
        assert "MusicOrganizer/2.0" not in src


class TestDefaults:
    def test_defaults_contain_required_keys(self):
        required = [
            "acoustid_api_key", "lastfm_api_key", "user_agent",
            "mb_rate_limit_seconds", "supported_extensions",
            "output_template", "mb_base_url", "caa_base_url",
        ]
        for key in required:
            assert key in DEFAULTS, f"Missing default: {key}"

    def test_supported_extensions_include_common_formats(self):
        exts = DEFAULTS["supported_extensions"]
        for ext in [".mp3", ".flac", ".ogg", ".m4a", ".wav"]:
            assert ext in exts, f"Missing extension: {ext}"


class TestConfigSingleton:
    def test_singleton_pattern(self):
        c1 = Config()
        c2 = Config()
        assert c1 is c2

    def test_get_returns_default(self):
        c = Config()
        assert c.get("acoustid_api_key") == "8XaBELgH"

    def test_get_with_default(self):
        c = Config()
        assert c.get("nonexistent_key", "fallback") == "fallback"

    def test_set_and_get(self):
        c = Config()
        c.set("custom_key", "custom_value")
        assert c.get("custom_key") == "custom_value"

    def test_contains(self):
        c = Config()
        assert "acoustid_api_key" in c
        assert "nonexistent_key" not in c

    def test_getitem(self):
        c = Config()
        assert c["user_agent"] == DEFAULTS["user_agent"]


class TestConfigFile:
    def test_load_from_file(self, tmp_dir):
        config_dir = os.path.join(tmp_dir, ".music-organizer")
        os.makedirs(config_dir)
        config_file = os.path.join(config_dir, "config.json")
        with open(config_file, "w") as f:
            json.dump({"acoustid_api_key": "custom_key_123"}, f)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MUSIC_ORG_ACOUSTID_API_KEY", None)
            c = Config()
            c._data = dict(DEFAULTS)
            c._config_path = lambda: Path(config_file)
            c._load_file()
            assert c.get("acoustid_api_key") == "custom_key_123"

    def test_env_override(self):
        with patch.dict(os.environ, {"MUSIC_ORG_ACOUSTID_API_KEY": "env_key"}):
            c = Config()
            c._data = dict(DEFAULTS)
            c._load_env()
            assert c.get("acoustid_api_key") == "env_key"

    def test_env_bool_coercion(self):
        with patch.dict(os.environ, {"MUSIC_ORG_MERGE_SIMILAR_ALBUMS": "false"}):
            c = Config()
            c._data = dict(DEFAULTS)
            c._load_env()
            assert c.get("merge_similar_albums") is False

    def test_env_int_coercion(self):
        with patch.dict(os.environ, {"MUSIC_ORG_FILENAME_MAX_LENGTH": "80"}):
            c = Config()
            c._data = dict(DEFAULTS)
            c._load_env()
            assert c.get("filename_max_length") == 80


class TestConfigSave:
    def test_save_creates_file(self, tmp_dir):
        config_dir = os.path.join(tmp_dir, ".music-organizer")
        os.makedirs(config_dir)
        config_file = os.path.join(config_dir, "config.json")

        c = Config()
        c._data = dict(DEFAULTS)
        c._data["acoustid_api_key"] = "saved_key"
        c._config_path = lambda: Path(config_file)
        c.save()

        with open(config_file) as f:
            saved = json.load(f)
        assert saved["acoustid_api_key"] == "saved_key"
