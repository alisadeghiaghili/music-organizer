#!/usr/bin/env python3
"""Regression tests for fpcalc_installer download URLs.

The in-app "Enable fingerprinting" button silently broke when the download
host moved from acoustid.org/files (now 404) to the GitHub release. These
tests pin the URL shape so a regression to a dead host fails offline — no
network needed, only the structure is asserted.
"""

import platform
from unittest.mock import patch

import fpcalc_installer


class TestFpcalcUrls:
    def test_no_url_points_at_dead_acoustid_files_host(self):
        """The old acoustid.org/files path returns 404 and broke the download."""
        for url in fpcalc_installer.FPCALC_URLS.values():
            assert "acoustid.org/files" not in url, (
                f"download URL points at dead host: {url}"
            )

    def test_urls_point_at_github_release_assets(self):
        for url in fpcalc_installer.FPCALC_URLS.values():
            assert url.startswith(
                "https://github.com/acoustid/chromaprint/releases/download/"
            ), f"unexpected host for fpcalc asset: {url}"

    def test_get_download_url_returns_a_known_entry(self):
        url = fpcalc_installer.get_download_url()
        # Whether it matches (system, machine) exactly or the per-system
        # fallback, it must be one of the curated URLs (never a dead host).
        assert url is None or url in fpcalc_installer.FPCALC_URLS.values()

    def test_windows_url_is_the_windows_asset(self):
        assert fpcalc_installer.FPCALC_URLS[("Windows", "AMD64")].endswith(
            "-windows-x86_64.zip"
        )

    def test_version_constant_is_used_in_urls(self):
        for url in fpcalc_installer.FPCALC_URLS.values():
            assert fpcalc_installer.FPCALC_VERSION in url
