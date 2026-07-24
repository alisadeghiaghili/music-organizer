#!/usr/bin/env python3
"""Shared test fixtures for Music Organizer."""

import os
import struct
import shutil
import tempfile
import pytest
from pathlib import Path


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test files."""
    d = tempfile.mkdtemp(prefix="music_org_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _create_minimal_mp3(path):
    """Create a minimal valid MP3 file with ID3v2.4 tags."""
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, TCON

    # Create ID3 tag and save to file
    tags = ID3()
    tags.add(TIT2(encoding=3, text=["Test Song"]))
    tags.add(TPE1(encoding=3, text=["Test Artist"]))
    tags.add(TALB(encoding=3, text=["Test Album"]))
    tags.add(TDRC(encoding=3, text=["2024"]))
    tags.add(TRCK(encoding=3, text=["1/10"]))
    tags.add(TCON(encoding=3, text=["Rock"]))
    tags.save(path)

    # Append a minimal MPEG1 Layer3 frame so mutagen can find audio
    # 0xFF 0xFB = sync word + MPEG1 + Layer3 + no CRC
    frame_header = bytes([0xFF, 0xFB, 0x90, 0x00])
    frame_size = 417  # 128kbps 44100Hz stereo
    frame = frame_header + b"\x00" * (frame_size - 4)

    with open(path, "ab") as f:
        f.write(frame * 3)


def _create_minimal_flac(path):
    """Create a minimal valid FLAC file."""
    with open(path, "wb") as f:
        # fLaC magic
        f.write(b"fLaC")

        # STREAMINFO block (type=0, last=0, length=34)
        f.write(bytes([0x00, 0x00, 0x00, 0x22]))

        # STREAMINFO: 34 bytes total
        # min block size (16 bits)
        f.write(struct.pack(">H", 4096))
        # max block size (16 bits)
        f.write(struct.pack(">H", 4096))
        # min frame size (24 bits) - use 0 (unknown)
        f.write(b"\x00\x00\x00")
        # max frame size (24 bits) - use 0 (unknown)
        f.write(b"\x00\x00\x00")

        # sample rate (20 bits) | channels (3 bits) | bits_per_sample-1 (5 bits) | total_samples (36 bits)
        # Pack as 5 bytes + 4 bytes = 9 bytes (total 2+2+3+3+4+4+16 = 34)
        sample_rate = 44100
        channels = 1
        bps = 16
        total_samples = 0

        # First 4 bytes: sample_rate(20) + channels(3) + bps-1(5) + total_samples_high(4)
        first = (sample_rate << 12) | (channels << 9) | ((bps - 1) << 4) | ((total_samples >> 32) & 0x0F)
        f.write(struct.pack(">I", first))

        # Next 4 bytes: total_samples_low(32)
        f.write(struct.pack(">I", total_samples & 0xFFFFFFFF))

        # MD5 signature (16 bytes of zeros)
        f.write(b"\x00" * 16)

        # VorbisComment block (type=4, last=0)
        # FLAC VorbisComment stores raw Vorbis comment data WITHOUT the \x03vorbis header
        vc = _build_vorbis_comment_bytes_flac({
            "TITLE": "Flac Song",
            "ARTIST": "Flac Artist",
            "ALBUM": "Flac Album",
            "DATE": "2023",
            "TRACKNUMBER": "2",
            "GENRE": "Jazz",
        })
        f.write(bytes([0x04]) + struct.pack(">I", len(vc))[1:])
        f.write(vc)


def _create_minimal_ogg(path):
    """Create a minimal valid OGG Vorbis file."""
    import io

    # Vorbis identification header
    vorbis_id = io.BytesIO()
    vorbis_id.write(b"\x01vorbis")
    vorbis_id.write(struct.pack("<IBI", 0, 1, 44100))
    vorbis_id.write(struct.pack("<III", 128000, 0, 0))
    vorbis_id.write(b"\x00\x00")  # blocksize hints
    vorbis_id.write(b"\x01")  # framing bit

    id_data = vorbis_id.getvalue()

    with open(path, "wb") as f:
        # First OGG page (identification)
        f.write(b"OggS")
        f.write(struct.pack("<B", 0))  # version
        f.write(struct.pack("<B", 0x02))  # header type: first
        f.write(struct.pack("<Q", 0))  # granule pos
        f.write(struct.pack("<I", 12345))  # serial
        f.write(struct.pack("<I", 0))  # page seq
        f.write(b"\x00\x00\x00\x00")  # checksum placeholder
        f.write(struct.pack("B", 1))  # seg count
        f.write(struct.pack("B", len(id_data)))  # seg table
        f.write(id_data)

        # Second OGG page (comment)
        vc = _build_vorbis_comment_bytes({
            "TITLE": "Ogg Song",
            "ARTIST": "Ogg Artist",
            "ALBUM": "Ogg Album",
            "DATE": "2022",
            "TRACKNUMBER": "3",
            "GENRE": "Electronic",
        })

        f.write(b"OggS")
        f.write(struct.pack("<B", 0))
        f.write(struct.pack("<B", 0x00))  # no continuation
        f.write(struct.pack("<Q", 0))
        f.write(struct.pack("<I", 12345))
        f.write(struct.pack("<I", 1))
        f.write(b"\x00\x00\x00\x00")
        f.write(struct.pack("B", 1))
        f.write(struct.pack("B", len(vc)))
        f.write(vc)


def _build_vorbis_comment_bytes(tags_dict):
    """Build raw Vorbis comment packet bytes (with \x03vorbis header for OGG)."""
    import io
    buf = io.BytesIO()
    buf.write(b"\x03vorbis")

    vendor = b"test"
    buf.write(struct.pack("<I", len(vendor)))
    buf.write(vendor)
    buf.write(struct.pack("<I", len(tags_dict)))

    for key, value in tags_dict.items():
        tag = f"{key}={value}".encode("utf-8")
        buf.write(struct.pack("<I", len(tag)))
        buf.write(tag)

    buf.write(b"\x01")  # framing bit
    return buf.getvalue()


def _build_vorbis_comment_bytes_flac(tags_dict):
    """Build raw Vorbis comment data for FLAC (NO \x03vorbis header)."""
    import io
    buf = io.BytesIO()

    vendor = b"test"
    buf.write(struct.pack("<I", len(vendor)))
    buf.write(vendor)
    buf.write(struct.pack("<I", len(tags_dict)))

    for key, value in tags_dict.items():
        tag = f"{key}={value}".encode("utf-8")
        buf.write(struct.pack("<I", len(tag)))
        buf.write(tag)

    buf.write(b"\x01")  # framing bit
    return buf.getvalue()


@pytest.fixture
def sample_mp3(tmp_dir):
    """Create a minimal valid MP3 file with ID3 tags."""
    mp3_path = os.path.join(tmp_dir, "01 - Test Song.mp3")
    _create_minimal_mp3(mp3_path)
    return mp3_path


@pytest.fixture
def sample_flac(tmp_dir):
    """Create a minimal valid FLAC file with Vorbis comments."""
    flac_path = os.path.join(tmp_dir, "02 - Flac Song.flac")
    _create_minimal_flac(flac_path)
    return flac_path


@pytest.fixture
def sample_ogg(tmp_dir):
    """Create a minimal valid OGG Vorbis file with tags."""
    ogg_path = os.path.join(tmp_dir, "03 - Ogg Song.ogg")
    _create_minimal_ogg(ogg_path)
    return ogg_path


@pytest.fixture
def output_dir(tmp_dir):
    """Create a temporary output directory."""
    d = os.path.join(tmp_dir, "output")
    os.makedirs(d)
    return d
