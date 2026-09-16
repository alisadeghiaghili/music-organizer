#!/usr/bin/env python3
"""Safety tests: dry-run purity, source immutability, merge sidecars, journal.

These tests encode the Phase A contract:
  - dry_run must not mutate any file on disk
  - copy mode must not rewrite tags on the source file
  - merge must not delete non-audio sidecar files
  - journal must record each filesystem mutation
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from mutagen.id3 import ID3

from music_core import (
    merge_duplicate_albums,
    merge_duplicate_artists,
    process_file,
    read_tags,
)


MB_OK = {
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


def _read_id3_raw(path: str) -> dict[str, str]:
    """Return a stable snapshot of ID3 text frames for mutation comparison."""
    try:
        tags = ID3(path)
    except Exception:
        return {}
    snap: dict[str, str] = {}
    for key in tags.keys():
        frame = tags[key]
        text = getattr(frame, "text", None)
        if text:
            snap[key] = str(text[0])
    return snap


def _opts(**overrides) -> dict:
    base = {
        "copy": True,
        "acoustid": False,
        "write_tags": True,
        "overwrite": False,
        "dry_run": False,
        "fetch_art": False,
        "fetch_lyrics": False,
        "overwrite_art": False,
        "write_to_source": False,
        "journal": True,
    }
    base.update(overrides)
    return base


@pytest.fixture
def mb_mock():
    with patch("music_core.search_mb", return_value=dict(MB_OK)), \
         patch("music_core.acoustid_lookup", return_value=None), \
         patch("music_core.lastfm_genres", return_value=[]), \
         patch("music_core.fetch_lyrics", return_value=(None, None)), \
         patch("music_core.fetch_cover_art", return_value=None), \
         patch("music_core.find_fpcalc", return_value=None):
        yield


class TestDryRunPurity:
    """dry_run=True must leave the filesystem byte-identical for the source."""

    def test_dry_run_does_not_write_source_tags(self, sample_mp3, output_dir, mb_mock):
        before = _read_id3_raw(sample_mp3)
        mtime_before = os.path.getmtime(sample_mp3)

        stats = {"ok": 0, "skipped": 0, "errors": 0}
        meta, source, status, dest = process_file(
            sample_mp3, output_dir, _opts(dry_run=True), stats
        )

        assert status == "dry-run"
        after = _read_id3_raw(sample_mp3)
        assert after == before, (
            "dry_run must not rewrite source tags. "
            f"before={before!r} after={after!r}"
        )
        assert os.path.getmtime(sample_mp3) == mtime_before

    def test_dry_run_creates_no_output_tree(self, sample_mp3, output_dir, mb_mock):
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        process_file(sample_mp3, output_dir, _opts(dry_run=True), stats)

        created = [p for p in Path(output_dir).rglob("*")]
        assert created == [], f"dry_run created filesystem entries: {created}"

    def test_dry_run_does_not_create_journal_file(self, sample_mp3, output_dir, mb_mock):
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        process_file(sample_mp3, output_dir, _opts(dry_run=True, journal=True), stats)

        journal = Path(output_dir) / "organize-journal.jsonl"
        assert not journal.exists()


class TestSourceImmutability:
    """Copy mode must never rewrite tags on the original file."""

    def test_copy_mode_leaves_source_tags_untouched(self, sample_mp3, output_dir, mb_mock):
        before = _read_id3_raw(sample_mp3)
        mtime_before = os.path.getmtime(sample_mp3)
        # Same album → confident match → a buggy writer would rewrite source.
        mb = dict(MB_OK)
        mb["title"] = "Renamed By MB"
        mb["label"] = "Some Label"

        with patch("music_core.search_mb", return_value=mb):
            stats = {"ok": 0, "skipped": 0, "errors": 0}
            meta, source, status, dest = process_file(
                sample_mp3, output_dir, _opts(), stats
            )

        assert status == "ok"
        after = _read_id3_raw(sample_mp3)
        assert after == before, (
            "copy mode mutated the source file. "
            f"before={before!r} after={after!r}"
        )
        assert os.path.getmtime(sample_mp3) == mtime_before

    def test_copy_mode_writes_tags_on_destination(self, sample_mp3, output_dir, mb_mock):
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        meta, source, status, dest = process_file(
            sample_mp3, output_dir, _opts(), stats
        )
        assert status == "ok"
        assert Path(dest).exists()
        dest_tags = read_tags(dest)
        assert dest_tags["title"] == "Test Song"
        assert dest_tags["album"] == "Test Album"
        assert dest_tags["artist"] == "Test Artist"


class TestMergeSidecars:
    """merge_duplicate_albums must not rmtree sidecar files."""

    def _make_album(
        self, root: Path, artist: str, album: str, *, sidecar: str | None = None
    ) -> Path:
        album_dir = root / artist / album
        album_dir.mkdir(parents=True)
        (album_dir / "01 - Song.mp3").write_bytes(b"\x00" * 8)
        (album_dir / "rip.cue").write_text('FILE "audio.wav" WAVE\n')
        (album_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        if sidecar:
            (album_dir / sidecar).write_text(f"unique:{sidecar}\n")
        return album_dir

    def test_merge_preserves_non_audio_files(self, tmp_dir):
        root = Path(tmp_dir) / "out"
        root.mkdir()
        self._make_album(root, "Artist", "Album", sidecar="loser-only.nfo")
        self._make_album(root, "Artist", "2020 - Album")

        merge_duplicate_albums(str(root))

        winner = root / "Artist" / "2020 - Album"
        assert winner.exists()
        assert (winner / "rip.cue").exists(), "merge deleted .cue sidecar"
        assert (winner / "loser-only.nfo").exists(), (
            "merge deleted unique sidecar from loser folder"
        )
        assert (winner / "cover.jpg").exists()

    def test_merge_leaves_no_empty_loser_dir(self, tmp_dir):
        root = Path(tmp_dir) / "out"
        root.mkdir()
        loser = root / "Artist" / "Album"
        loser.mkdir(parents=True)
        # Only unique names so every file can be absorbed without conflicts.
        (loser / "02 - Bonus.mp3").write_bytes(b"\x01" * 8)
        (loser / "only-in-loser.nfo").write_text("unique\n")
        self._make_album(root, "Artist", "2020 - Album")

        merge_duplicate_albums(str(root))

        assert not loser.exists()
        dirs = {p.name for p in (root / "Artist").iterdir() if p.is_dir()}
        assert dirs == {"2020 - Album"}
        winner = root / "Artist" / "2020 - Album"
        assert (winner / "02 - Bonus.mp3").exists()
        assert (winner / "only-in-loser.nfo").exists()

    def test_merge_keeps_loser_when_name_conflicts_remain(self, tmp_dir):
        """If winner already has the same filenames, do not rmtree the loser."""
        root = Path(tmp_dir) / "out"
        root.mkdir()
        loser = self._make_album(root, "Artist", "Album")
        self._make_album(root, "Artist", "2020 - Album")
        # Extra file only in loser with a name that also exists in winner? No —
        # use identical layout; all moves skip; loser must survive.
        merge_duplicate_albums(str(root))
        assert loser.exists(), "rmtree removed a folder that still held skipped files"


class TestMergeArtist:
    """merge_duplicate_artists folds split artist folders into one."""

    def _artist_album(self, root: Path, artist: str, album: str, song: str) -> Path:
        album_dir = root / artist / album
        album_dir.mkdir(parents=True)
        (album_dir / f"01 - {song}.mp3").write_bytes(b"\x00" * 8)
        (album_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        return album_dir

    def test_bracket_artist_variant_is_merged(self, tmp_dir):
        root = Path(tmp_dir) / "out"
        root.mkdir()
        # Same artist, one folder has a stray bracket variant in its name.
        self._artist_album(root, "Shajarian", "2001 - Divan", "Parvaneh")
        loser = self._artist_album(root, "Shajarian (فرض)", "1999 - Other", "Khesht")

        merged = merge_duplicate_artists(str(root))

        assert merged == 1
        assert not loser.exists()
        winner = root / "Shajarian"
        # Both album folders now live under the canonical artist folder.
        assert (winner / "2001 - Divan" / "01 - Parvaneh.mp3").exists()
        assert (winner / "1999 - Other" / "01 - Khesht.mp3").exists()
        assert len([p for p in root.iterdir() if p.is_dir()]) == 1

    def test_distinct_artists_not_merged(self, tmp_dir):
        root = Path(tmp_dir) / "out"
        root.mkdir()
        self._artist_album(root, "Raha Derakhsh", "Raha", "Song")
        self._artist_album(root, "Raha", "Solo", "Other")

        merge_duplicate_artists(str(root))

        assert (root / "Raha Derakhsh").exists()
        assert (root / "Raha").exists()

    def test_keeps_loser_when_name_conflicts_remain(self, tmp_dir):
        """If winner already has the same filenames, do not rmtree the loser."""
        root = Path(tmp_dir) / "out"
        root.mkdir()
        self._artist_album(root, "Artist", "2000 - A", "01 - X")
        loser = self._artist_album(root, "Artist (feat)", "2000 - A", "01 - X")

        merge_duplicate_artists(str(root))

        # The loser's only file collides, so it is kept in place, not deleted.
        assert loser.exists()


class TestTitlePrefixStrip:
    """A 'NN -' prefix in the title must not double the track number in the path."""

    def _mp3_with_title(self, path: str, title: str, track: str) -> str:
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK
        tags = ID3()
        tags.add(TIT2(encoding=3, text=[title]))
        tags.add(TPE1(encoding=3, text=["Artist"]))
        tags.add(TALB(encoding=3, text=["Album"]))
        tags.add(TRCK(encoding=3, text=[f"{track}/10"]))
        tags.save(path)
        frame = bytes([0xFF, 0xFB, 0x90, 0x00]) + b"\x00" * 413
        with open(path, "ab") as f:
            f.write(frame * 3)
        return path

    def test_destination_title_has_no_double_prefix(self, tmp_dir):
        src = self._mp3_with_title(
            str(Path(tmp_dir) / "03 - Song.mp3"), "03 - Song", "3"
        )
        dst = str(Path(tmp_dir) / "out")
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        with patch("music_core.search_mb", return_value=None), \
             patch("music_core.acoustid_lookup", return_value=None), \
             patch("music_core.lastfm_genres", return_value=[]), \
             patch("music_core.fetch_lyrics", return_value=(None, None)), \
             patch("music_core.find_fpcalc", return_value=None):
            meta, _src_label, status, dest = process_file(
                src, dst, _opts(), stats
            )
        assert status == "ok"
        # Filename is "03 - Song.mp3", never "03 - 03 - Song.mp3".
        assert Path(dest).name == "03 - Song.mp3"
        assert meta["title"] == "Song"


class TestCollisionNeverDropsData:
    """Two DIFFERENT files that normalise to the same destination path must
    both be preserved — the second gets a '(N)' filename, never a silent skip.

    Regression: distinct tracks (e.g. two different songs of the same title, or
    two artists whose names collapse under a loose online match) used to be
    dropped as a false 'duplicate' the moment the first one claimed the
    destination filename.
    """

    def _mk_mp3(self, path, payload=b"\x00", title="Song", track="1"):
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK
        tags = ID3()
        tags.add(TIT2(encoding=3, text=[title]))
        tags.add(TPE1(encoding=3, text=["Artist"]))
        tags.add(TALB(encoding=3, text=["Album"]))
        tags.add(TRCK(encoding=3, text=[f"{track}/10"]))
        tags.save(path)
        frame = bytes([0xFF, 0xFB, 0x90, 0x00]) + payload * 413
        with open(path, "ab") as f:
            f.write(frame * 3)
        return path

    def _process(self, path, dst, opts=None):
        from unittest.mock import patch
        opts = opts or _opts()
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        with patch("music_core.search_mb", return_value=None), \
             patch("music_core.acoustid_lookup", return_value=None), \
             patch("music_core.lastfm_genres", return_value=[]), \
             patch("music_core.fetch_lyrics", return_value=(None, None)), \
             patch("music_core.find_fpcalc", return_value=None):
            meta, _src, status, dest = process_file(path, dst, opts, stats)
        return status, dest, stats

    def test_distinct_files_get_unique_names(self, tmp_dir):
        dst = str(Path(tmp_dir) / "out")
        # Two files with identical tags (→ identical destination) but different
        # audio bytes: the Salar/Homayoun "two different songs, one filename" case.
        a = self._mk_mp3(str(Path(tmp_dir) / "a.mp3"), payload=b"\x00")
        b = self._mk_mp3(str(Path(tmp_dir) / "b.mp3"), payload=b"\x01")

        status_a, dest_a, _ = self._process(a, dst)
        status_b, dest_b, _ = self._process(b, dst)

        assert status_a == "ok"
        assert Path(dest_a).name == "01 - Song.mp3"
        # The second distinct file is NOT dropped — it gets its own name.
        assert status_b == "ok"
        assert Path(dest_b).name == "01 - Song (1).mp3"
        assert Path(dest_a).exists()
        assert Path(dest_b).exists()
        # Both distinct payloads survive on disk.
        assert Path(dest_a).read_bytes() != Path(dest_b).read_bytes()

    def test_true_duplicate_is_still_skipped(self, tmp_dir):
        dst = str(Path(tmp_dir) / "out")
        a = self._mk_mp3(str(Path(tmp_dir) / "a.mp3"), payload=b"\x00")

        status_a, dest_a, _ = self._process(a, dst)
        # Re-running the very same file must be idempotent (a real duplicate).
        status_a2, dest_a2, stats = self._process(a, dst)

        assert status_a == "ok"
        assert status_a2 == "skipped"
        assert dest_a2 == dest_a
        assert stats["skipped"] == 1 and stats["ok"] == 0

    def test_collision_resolves_past_occupied_slot(self, tmp_dir):
        dst = str(Path(tmp_dir) / "out")
        a = self._mk_mp3(str(Path(tmp_dir) / "a.mp3"), payload=b"\x00")
        b = self._mk_mp3(str(Path(tmp_dir) / "b.mp3"), payload=b"\x01")
        c = self._mk_mp3(str(Path(tmp_dir) / "c.mp3"), payload=b"\x02")

        _, dest_a, _ = self._process(a, dst)
        _, dest_b, _ = self._process(b, dst)
        status_c, dest_c, _ = self._process(c, dst)

        assert Path(dest_a).name == "01 - Song.mp3"
        assert Path(dest_b).name == "01 - Song (1).mp3"
        assert status_c == "ok"
        assert Path(dest_c).name == "01 - Song (2).mp3"


class TestDirtyTagFiling:
    """Dirty source tags (bracketed artist, site watermark, stray '~') must not
    split one artist into a separate ``[bracket]`` folder or leave watermarks in
    the destination filenames.

    Regression: two distinct songs of the same artist, e.g.
    ``Salar Aghili - Khor Ava [SevilMusic].mp3`` (artist ``Salar Aghili``) and
    ``Salar Aghili - Royaye Man [SevilMusic].mp3`` (artist ``[Salar Aghili]``,
    title ``[Royaye Man] ~[SevilMusic.Com]~``), were filed under two different
    artist folders because the brackets created ``[Salar Aghili]`` — so one song
    appeared to vanish. Both must now land under a single clean ``Salar Aghili``
    folder.
    """

    def _mk_mp3(self, path, *, artist, title, payload=b"\x00"):
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC
        tags = ID3()
        tags.add(TIT2(encoding=3, text=[title]))
        tags.add(TPE1(encoding=3, text=[artist]))
        tags.add(TDRC(encoding=3, text=["2020"]))
        tags.save(path)
        frame = bytes([0xFF, 0xFB, 0x90, 0x00]) + payload * 413
        with open(path, "ab") as f:
            f.write(frame * 3)
        return path

    def _process(self, path, dst):
        from unittest.mock import patch
        opts = dict(copy=True, acoustid=False, write_tags=True, overwrite=False,
                    dry_run=True, fetch_art=False, fetch_lyrics=False,
                    overwrite_art=False, journal=False)
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        with patch("music_core.search_mb", return_value=None), \
             patch("music_core.acoustid_lookup", return_value=None), \
             patch("music_core.lastfm_genres", return_value=[]), \
             patch("music_core.fetch_lyrics", return_value=(None, None)), \
             patch("music_core.find_fpcalc", return_value=None):
            meta, source, status, dest = process_file(path, dst, opts, stats)
        return meta, dest

    def test_dirty_tags_file_under_one_clean_artist_folder(self, tmp_dir):
        from pathlib import Path as P
        dst = str(P(tmp_dir) / "out")
        a = self._mk_mp3(str(P(tmp_dir) / "a.mp3"),
                         artist="Salar Aghili",
                         title="Khor Ava [SevilMusic.Com]", payload=b"\x00")
        b = self._mk_mp3(str(P(tmp_dir) / "b.mp3"),
                         artist="[Salar Aghili]",
                         title="[Royaye Man] ~[SevilMusic.Com]~", payload=b"\x01")

        meta_a, dest_a = self._process(a, dst)
        meta_b, dest_b = self._process(b, dst)

        # Both must resolve to the same, unbracketed artist folder.
        assert P(dest_a).parent.parent.name == "Salar Aghili"
        assert P(dest_b).parent.parent.name == "Salar Aghili"
        assert P(dest_a).parent.parent == P(dest_b).parent.parent

        # Clean names: no brackets, tildes, or site watermarks anywhere in the path.
        for d in (dest_a, dest_b):
            parts = P(d).parts
            for part in parts:
                assert "[" not in part and "]" not in part, f"bracket left in {part!r}"
                assert "~" not in part, f"tilde left in {part!r}"
                assert "SevilMusic" not in part, f"watermark left in {part!r}"
        assert P(dest_a).name == "Khor Ava.mp3"
        assert P(dest_b).name == "Royaye Man.mp3"

        # The returned meta (used for tag-writing / status) is clean too.
        assert meta_a["artist"] == "Salar Aghili"
        assert meta_b["artist"] == "Salar Aghili"
        assert meta_a["title"] == "Khor Ava"
        assert meta_b["title"] == "Royaye Man"


class TestJournal:
    """Filesystem mutations must be journaled when journal is enabled."""

    def test_journal_created_on_copy(self, sample_mp3, output_dir, mb_mock):
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        process_file(sample_mp3, output_dir, _opts(journal=True), stats)

        journal = Path(output_dir) / "organize-journal.jsonl"
        assert journal.exists(), "journal file was not created"
        lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
        actions = {entry.get("action") for entry in lines}
        assert "copy" in actions or "tag" in actions
        for entry in lines:
            assert "ts" in entry
            assert "src" in entry or "dst" in entry

    def test_journal_disabled_writes_nothing(self, sample_mp3, output_dir, mb_mock):
        stats = {"ok": 0, "skipped": 0, "errors": 0}
        process_file(sample_mp3, output_dir, _opts(journal=False), stats)
        journal = Path(output_dir) / "organize-journal.jsonl"
        assert not journal.exists()
