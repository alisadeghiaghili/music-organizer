#!/usr/bin/env python3
"""config.py — centralized configuration for Music Organizer

Loads from ~/.music-organizer/config.json with defaults.
Environment variables override file config (prefix: MUSIC_ORG_).
"""

import json
import os
from pathlib import Path

# ── Default configuration ─────────────────────────────────────────────────────

DEFAULTS = {
    # API keys
    # AcoustID key is public/shared — distributed with Chromaprint tools
    "acoustid_api_key": "8XaBELgH",
    "lastfm_api_key": "",
    "discogs_token": "",

    # Network
    "user_agent": "MusicOrganizer/2.0 (github.com/alisadeghiaghili/music-organizer)",
    "mb_rate_limit_seconds": 1.1,
    "request_timeout": 10,

    # Processing
    "max_genre_count": 4,
    "filename_max_length": 60,
    "output_template": "{artist}/{year} - {album}/{track} - {title}.mp3",
    "cover_filename": "cover.jpg",

    # Audio format support
    "supported_extensions": [
        ".mp3", ".flac", ".ogg", ".oga", ".m4a", ".mp4",
        ".wav", ".aiff", ".aif", ".wma", ".opus", ".ape",
    ],

    # Paths
    "config_dir": str(Path.home() / ".music-organizer"),
    "fpcalc_filename": "fpcalc.exe" if os.name == "nt" else "fpcalc",

    # Chromaprint
    "fpcalc_version": "1.6.0",
    "fpcalc_urls": {
        "windows-amd64": "https://github.com/acoustid/chromaprint/releases/download/v1.6.0/chromaprint-fpcalc-1.6.0-windows-x86_64.zip",
        "windows-arm64": "https://github.com/acoustid/chromaprint/releases/download/v1.6.0/chromaprint-fpcalc-1.6.0-windows-arm64.zip",
        "macos-x86_64": "https://github.com/acoustid/chromaprint/releases/download/v1.6.0/chromaprint-fpcalc-1.6.0-macos-x86_64.tar.gz",
        "macos-arm64": "https://github.com/acoustid/chromaprint/releases/download/v1.6.0/chromaprint-fpcalc-1.6.0-macos-arm64.tar.gz",
        "linux-x86_64": "https://github.com/acoustid/chromaprint/releases/download/v1.6.0/chromaprint-fpcalc-1.6.0-linux-x86_64.tar.gz",
        "linux-arm64": "https://github.com/acoustid/chromaprint/releases/download/v1.6.0/chromaprint-fpcalc-1.6.0-linux-aarch64.tar.gz",
        "linux-armhf": "https://github.com/acoustid/chromaprint/releases/download/v1.6.0/chromaprint-fpcalc-1.6.0-linux-armv7hf.tar.gz",
    },

    # Merge settings
    "merge_similar_albums": True,

    # MusicBrainz API endpoints
    "mb_base_url": "https://musicbrainz.org/ws/2",
    "caa_base_url": "https://coverartarchive.org",
    "acoustid_api_url": "https://api.acoustid.org/v2/lookup",
    "lastfm_api_url": "https://ws.audioscrobbler.com/2.0/",
}


class Config:
    """Singleton configuration manager."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self):
        if self._loaded:
            return
        self._data = dict(DEFAULTS)
        self._load_file()
        self._load_env()
        self._loaded = True

    def _config_path(self) -> Path:
        return Path(self._data["config_dir"]) / "config.json"

    def _load_file(self):
        path = self._config_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                # Only update keys that exist in defaults
                for k, v in user_cfg.items():
                    if k in DEFAULTS:
                        self._data[k] = v
            except (json.JSONDecodeError, OSError):
                pass

    def _load_env(self):
        prefix = "MUSIC_ORG_"
        for key in DEFAULTS:
            env_key = prefix + key.upper()
            val = os.environ.get(env_key)
            if val is not None:
                # Auto-coerce types based on default
                default = DEFAULTS[key]
                if isinstance(default, bool):
                    self._data[key] = val.lower() in ("1", "true", "yes")
                elif isinstance(default, int):
                    try:
                        self._data[key] = int(val)
                    except ValueError:
                        pass
                elif isinstance(default, float):
                    try:
                        self._data[key] = float(val)
                    except ValueError:
                        pass
                elif isinstance(default, list):
                    self._data[key] = [s.strip() for s in val.split(",")]
                else:
                    self._data[key] = val

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value

    def save(self):
        """Save current config to disk."""
        path = self._config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Save only non-default values
        overrides = {k: v for k, v in self._data.items() if v != DEFAULTS.get(k)}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(overrides, f, indent=2, ensure_ascii=False)

    @property
    def supported_extensions(self) -> set:
        return set(self._data["supported_extensions"])

    @property
    def is_mp3(self):
        return lambda ext: ext.lower() == ".mp3"

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data


def get_config() -> Config:
    """Get the global configuration singleton."""
    return Config()
