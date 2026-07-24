#!/usr/bin/env python3
"""music_core.py — shared logic for Music Organizer (GUI + CLI)

Features:
  • MusicBrainz metadata (title, artist, album, year, track, disc,
    total_tracks, disc_total, label, composer, genres)
  • AcoustID audio fingerprinting fallback
  • Cover Art Archive album art (fetch + embed + save cover.jpg)
  • Last.fm genre fallback (optional — needs API key)
  • fpcalc resolved from _MEIPASS (PyInstaller), disk, or PATH
  • Multi-format support: MP3, FLAC, OGG, M4A, WAV, AIFF, Opus, APE, WMA
"""

import os, re, sys, time, shutil, json, subprocess, urllib.request, urllib.parse, threading, base64, hashlib
from datetime import datetime
from pathlib import Path
from mutagen import File as MutagenFile
from mutagen.id3 import (
    ID3, ID3NoHeaderError,
    TIT2, TPE1, TPE2, TALB, TDRC, TRCK, TCON, TCOM, TPUB, TPOS, APIC,
    USLT, SYLT,
)
from mutagen.flac import FLAC, FLACNoHeaderError, Picture
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4, MP4Tags, MP4Cover
from mutagen.wave import WAVE
from mutagen.aiff import AIFF
from mutagen.mp3 import MP3
from config import get_config

_cfg = get_config()

MB_BASE   = _cfg["mb_base_url"]
CAA_BASE  = _cfg["caa_base_url"]
LASTFM_KEY = _cfg.get("lastfm_api_key", "")
HEADERS   = {"User-Agent": _cfg["user_agent"]}
_last_mb  = 0.0
_mb_lock  = threading.Lock()

# ── API Response Cache ─────────────────────────────────────────────────────────
_CACHE_DIR = Path.home() / ".music-organizer" / "cache"
_CACHE_TTL = 86400  # 24 hours
_CACHE_MAX_FILES = 1000  # Maximum cache files before cleanup

def _cache_cleanup():
    """Remove oldest cache files if over limit."""
    try:
        if not _CACHE_DIR.exists():
            return
        files = list(_CACHE_DIR.glob("*.json"))
        if len(files) <= _CACHE_MAX_FILES:
            return
        # Sort by modification time, remove oldest
        files.sort(key=lambda f: f.stat().st_mtime)
        for f in files[:len(files) - _CACHE_MAX_FILES]:
            f.unlink(missing_ok=True)
    except Exception:
        pass

def _cache_get(key):
    """Get cached API response if valid."""
    try:
        cache_file = _CACHE_DIR / f"{key}.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if time.time() - data.get("ts", 0) < _CACHE_TTL:
                return data.get("response")
    except Exception:
        pass
    return None

def _cache_set(key, response):
    """Cache an API response."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = _CACHE_DIR / f"{key}.json"
        cache_file.write_text(
            json.dumps({"ts": time.time(), "response": response}),
            encoding="utf-8"
        )
    except Exception:
        pass

def _make_cache_key(endpoint, params):
    """Create a deterministic cache key from endpoint and params."""
    param_str = urllib.parse.urlencode(sorted(params.items()))
    return f"{endpoint}_{hashlib.md5(param_str.encode()).hexdigest()[:12]}"

# Clean up old cache on startup
_cache_cleanup()


# ── MusicBrainz helpers ───────────────────────────────────────────────────────

def mb_get(endpoint, params, retries=1):
    """Fetch from MusicBrainz with rate limiting, caching, and retry."""
    # Check cache first
    cache_key = _make_cache_key(endpoint, params)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    global _last_mb
    for attempt in range(retries + 1):
        with _mb_lock:
            gap = 1.1 - (time.time() - _last_mb)
            if gap > 0:
                time.sleep(gap)
            url = f"{MB_BASE}/{endpoint}?" + urllib.parse.urlencode({**params, "fmt": "json"})
            req = urllib.request.Request(url, headers=HEADERS)
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    _last_mb = time.time()
                    data = json.loads(r.read().decode())
                    _cache_set(cache_key, data)
                    return data
            except Exception:
                _last_mb = time.time()
                if attempt < retries:
                    time.sleep(2)  # Wait before retry
                    continue
                return None
    return None


def _best_release(releases):
    """Select the best release — prefer studio albums, then by recency."""
    best, best_score = None, -1
    for rel in releases:
        date = rel.get("date", "")
        year = int(date[:4]) if date and date[:4].isdigit() else 9999
        rtype = rel.get("primary-type", "").lower()
        secondary = [t.lower() for t in rel.get("secondary-types", [])]

        # Score: prefer studio albums over compilations/greatest hits
        type_score = 3 if rtype == "album" and not secondary else 1
        if any(s in secondary for s in ("compilation", "greatest hits", "best of")):
            type_score = 0
        # Prefer earlier releases (original over reissue)
        current_year = datetime.now().year
        year_score = max(0, 30 - (current_year - year)) if year < 9999 else 0
        score = type_score * 1000 + year_score

        if score > best_score:
            best_score = score
            best = rel
    if best is None:
        return None, 9999
    year_str = best.get("date", "")
    year = int(year_str[:4]) if year_str and year_str[:4].isdigit() else 9999
    return best, year


def _mb_genres(rec, rel):
    genres = []
    for src in (rec, rel or {}):
        for g in src.get("genres", []) + src.get("tags", []):
            name = g.get("name", "").strip().title()
            if name and name not in genres:
                genres.append(name)
    return genres[:4]


def _mb_release_detail(release_id):
    if not release_id:
        return None
    return mb_get(f"release/{release_id}",
                  {"inc": "labels+genres+tags+artist-credits+media"})


def search_mb(artist, title, album=""):
    """Search MusicBrainz for metadata. Uses fuzzy matching for better results."""
    parts = []
    if title:  parts.append(f'recording:{title}')
    if artist: parts.append(f'artistname:{artist}')
    if album:  parts.append(f'release:{album}')
    if not parts:
        return None
    data = mb_get("recording",
                  {"query": " AND ".join(parts), "limit": 5,
                   "inc": "genres+tags+releases"})
    if not data or not data.get("recordings"):
        return None

    rec = data["recordings"][0]
    recording_id = rec.get("id", "")
    result = {
        "title":        rec.get("title", ""),
        "artist":       (rec["artist-credit"][0]["artist"]["name"]
                         if rec.get("artist-credit") else artist),
        "album":        "", "year": "", "track": "", "disc": "",
        "disc_total":   "", "total_tracks": "",
        "genres":       [], "label": "", "composer": "", "release_id": "",
    }
    releases = rec.get("releases", [])
    if releases:
        rel, year = _best_release(releases)
        if rel is not None:
            result["release_id"]   = rel.get("id", "")
            result["album"]        = rel.get("title", album)
            result["year"]         = str(year) if year != 9999 else ""
            media = rel.get("media", [])
            if media:
                result["disc_total"] = str(len(media)) if len(media) > 1 else ""
                # Search ALL media to find which disc contains this recording
                found_track = False
                for medium in media:
                    for track in medium.get("track", []):
                        if track.get("recording", {}).get("id") == recording_id:
                            if len(media) > 1:
                                result["disc"] = str(medium.get("position", ""))
                            result["track"] = str(track.get("number", ""))
                            result["total_tracks"] = str(medium.get("track-count", ""))
                            found_track = True
                            break
                    if found_track:
                        break
                # Fallback: use first media if recording not found in any
                if not found_track and media:
                    m0 = media[0]
                    result["total_tracks"] = str(m0.get("track-count", ""))
                    tracks = m0.get("track", [])
                    if tracks:
                        result["track"] = str(tracks[0].get("number", ""))

    detail = _mb_release_detail(result["release_id"])
    if detail:
        lbl_info = detail.get("label-info", [])
        if lbl_info:
            result["label"] = (lbl_info[0].get("label") or {}).get("name", "")
        result["genres"] = _mb_genres(rec, detail)
    if not result["genres"]:
        result["genres"] = _mb_genres(rec, None)

    return result


# ── Last.fm genre fallback ────────────────────────────────────────────────────

def lastfm_genres(artist, title, api_key=None, retries=1):
    """Fetch genres from Last.fm with caching and retry."""
    key = api_key or LASTFM_KEY
    if not key:
        return []

    # Check cache
    cache_key = _make_cache_key("lastfm", {"artist": artist, "title": title})
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    params = urllib.parse.urlencode({
        "method": "track.getInfo", "api_key": key,
        "artist": artist, "track": title, "format": "json",
    })

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"https://ws.audioscrobbler.com/2.0/?{params}", headers=HEADERS)
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode())
            tags = data.get("track", {}).get("toptags", {}).get("tag", [])
            result = [t["name"].title() for t in tags[:4] if t.get("name")]
            _cache_set(cache_key, result)
            return result
        except Exception:
            if attempt < retries:
                time.sleep(2)
                continue
            return []


# ── Lyrics (LRCLIB) ──────────────────────────────────────────────────────────

def fetch_lyrics(artist, title, album="", duration=0, retries=1):
    """Fetch lyrics from LRCLIB (free, no API key) with caching and retry.
    Returns (plain_lyrics, synced_lyrics) or (None, None).
    synced_lyrics is in standard LRC format [MM:SS.xx] text.
    """
    # Check cache
    cache_key = _make_cache_key("lrclib", {"artist": artist, "title": title, "album": album})
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    params = urllib.parse.urlencode({
        "track_name": title,
        "artist_name": artist,
        "album_name": album,
        "duration": int(duration),
    })
    url = f"https://lrclib.net/api/get?{params}"

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            plain = data.get("plainLyrics")
            synced = data.get("syncedLyrics")
            result = (plain, synced)
            _cache_set(cache_key, result)
            return result
        except Exception:
            if attempt < retries:
                time.sleep(2)
                continue
            return None, None


# ── Cover Art Archive ─────────────────────────────────────────────────────────

def fetch_cover_art(release_id, size="large", retries=1):
    """Fetch album art from Cover Art Archive with caching and retry."""
    if not release_id:
        return None

    # Check cache
    cache_key = _make_cache_key("caa", {"release_id": release_id, "size": size})
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    for attempt in range(retries + 1):
        for url in [
            f"{CAA_BASE}/release/{release_id}/front-{size}",
            f"{CAA_BASE}/release/{release_id}/front",
        ]:
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = r.read()
                    _cache_set(cache_key, data)
                    return data
            except Exception:
                continue
        if attempt < retries:
            time.sleep(2)
    return None


def save_folder_cover(album_dir: Path, img_bytes: bytes, overwrite=False):
    """Save cover.jpg to album folder. Overwrites if overwrite=True."""
    cover_path = album_dir / "cover.jpg"
    if not cover_path.exists() or overwrite:
        try:
            cover_path.write_bytes(img_bytes)
        except Exception:
            pass
    return str(cover_path) if cover_path.exists() else None


# ── fpcalc / AcoustID ─────────────────────────────────────────────────────────

def find_fpcalc():
    fname = "fpcalc.exe" if os.name == "nt" else "fpcalc"

    # 1. Embedded inside PyInstaller onefile exe
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / fname
        if p.exists():
            return str(p)

    # 2. Next to the script / exe on disk
    if getattr(sys, "frozen", False):
        p = Path(sys.executable).parent / fname
    else:
        p = Path(__file__).parent / fname
    if p.exists():
        return str(p)

    # 3. System PATH
    return shutil.which("fpcalc")


def fpcalc_status():
    p = find_fpcalc()
    return ("ok", p) if p else ("missing", None)


def acoustid_lookup(filepath, api_key=None, retries=1):
    """Lookup audio fingerprint via AcoustID with caching and retry."""
    if api_key is None:
        api_key = _cfg["acoustid_api_key"]
    fpcalc = find_fpcalc()
    if not fpcalc:
        return None
    try:
        r = subprocess.run(
            [fpcalc, "-json", filepath],
            capture_output=True, text=True, timeout=30
        )
        fp = json.loads(r.stdout)
    except Exception:
        return None

    # Check cache using deterministic hash
    fp_str = fp.get("fingerprint", "")
    cache_key = f"acoustid_{hashlib.md5(fp_str.encode()).hexdigest()[:12]}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = (
        f"https://api.acoustid.org/v2/lookup?client={api_key}"
        f"&duration={int(fp.get('duration', 0))}"
        f"&fingerprint={fp.get('fingerprint', '')}"
        "&meta=recordings+releases+tracks+releasegroups+compress"
    )

    data = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
                break
        except Exception:
            if attempt < retries:
                time.sleep(2)
                continue
            return None

    if data is None:
        return None
    results = data.get("results", [])
    if not results or not results[0].get("recordings"):
        return None
    rec    = results[0]["recordings"][0]
    artist = rec.get("artists", [{}])[0].get("name", "") if rec.get("artists") else ""
    title  = rec.get("title", "")
    album, year, track, release_id = "", "", "", ""
    if rec.get("releases"):
        rel, yr = _best_release(rec["releases"])
        if rel is not None:
            release_id = rel.get("id", "")
            album = rel.get("title", "")
            year  = str(yr) if yr != 9999 else ""
            mediums = rel.get("mediums", [])
            if mediums and mediums[0].get("tracks"):
                track = str(mediums[0]["tracks"][0].get("position", ""))
    result = {
        "title": title, "artist": artist, "album": album,
        "year": year, "track": track, "disc": "",
        "genres": [], "label": "", "composer": "",
        "total_tracks": "", "disc_total": "", "release_id": release_id,
    }
    _cache_set(cache_key, result)
    return result


# ── Tags ──────────────────────────────────────────────────────────────────────

def _get_tag_value(tags, key):
    """Extract a string value from a tag, handling various formats."""
    v = tags.get(key)
    if v is None:
        return ""
    # ID3 frames have .text attribute
    if hasattr(v, "text"):
        texts = v.text
        if texts:
            return str(texts[0]).strip()
    # Vorbis/MP4 use list values
    if isinstance(v, list) and v:
        return str(v[0]).strip()
    return str(v).strip()


def _get_tag_values(tags, key):
    """Extract list values from a tag."""
    v = tags.get(key)
    if v is None:
        return []
    if hasattr(v, "text"):
        return [str(t).strip() for t in v.text if str(t).strip()]
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v).strip()]


def _get_genres(tags):
    """Extract genres from tags, handling various formats."""
    genres = []
    # Try ID3 TCON first
    tcon = tags.get("TCON")
    if tcon is not None:
        if hasattr(tcon, "genres") and tcon.genres:
            genres = [x.strip().title() for x in tcon.genres if x.strip()]
        elif hasattr(tcon, "text"):
            genres = [x.strip().title() for x in tcon.text if x.strip()]
    # Try Vorbis/MP4 genre tags
    if not genres:
        for key in ("genre", "GENRE"):
            v = tags.get(key)
            if v:
                if isinstance(v, list):
                    genres = [x.strip().title() for x in v if x.strip()]
                elif hasattr(v, "text"):
                    genres = [x.strip().title() for x in v.text if x.strip()]
                if genres:
                    break
    return genres


def _has_artwork(tags):
    """Check if tags contain embedded artwork."""
    # ID3 APIC
    apic = tags.get("APIC")
    if apic:
        return True
    # MP4 covr
    covr = tags.get("covr") or tags.get("COVR")
    if covr:
        return True
    # FLAC picture
    if hasattr(tags, "pictures") and tags.pictures:
        return True
    return False


def read_tags(path):
    """Read metadata tags from an audio file (any supported format)."""
    empty = {
        "title": "", "artist": "", "album": "", "year": "", "track": "",
        "disc": "", "genres": [], "label": "", "composer": "",
        "total_tracks": "", "disc_total": "", "release_id": "", "has_art": False,
    }

    ext = Path(path).suffix.lower()

    # Try format-specific readers first for better accuracy
    if ext == ".mp3":
        return _read_id3_tags(path, empty)
    elif ext in (".flac",):
        return _read_flac_tags(path, empty)
    elif ext in (".ogg", ".oga"):
        return _read_vorbis_tags(path, empty)
    elif ext in (".m4a", ".mp4"):
        return _read_mp4_tags(path, empty)
    elif ext in (".wav",):
        return _read_wave_tags(path, empty)
    elif ext in (".aiff", ".aif"):
        return _read_aiff_tags(path, empty)

    # Fallback to generic mutagen.File()
    try:
        audio = MutagenFile(path)
        if audio is None:
            return empty
        return _read_generic_tags(audio, empty)
    except Exception:
        return empty


def _read_id3_tags(path, empty):
    """Read ID3 tags from MP3 files."""
    try:
        tags = ID3(path)
    except Exception:
        return empty

    def g(k):
        v = tags.get(k)
        if v is None:
            return ""
        if hasattr(v, "text") and v.text:
            return str(v.text[0]).strip()
        return ""

    trck = g("TRCK")
    tpos = g("TPOS")

    return {
        "title":        g("TIT2"),
        "artist":       g("TPE1") or g("TPE2"),
        "album":        g("TALB"),
        "year":         g("TDRC")[:4] if g("TDRC") else "",
        "track":        trck.split("/")[0] if trck else "",
        "total_tracks": trck.split("/")[1] if "/" in trck else "",
        "disc":         tpos.split("/")[0] if tpos else "",
        "disc_total":   tpos.split("/")[1] if "/" in tpos else "",
        "genres":       _get_genres(tags),
        "label":        g("TPUB"),
        "composer":     g("TCOM"),
        "release_id":   "",
        "has_art":      _has_artwork(tags),
    }


def _read_flac_tags(path, empty):
    """Read Vorbis comments from FLAC files."""
    try:
        audio = FLAC(path)
    except Exception:
        return empty

    tags = audio.tags or {}
    track = _get_tag_value(tags, "tracknumber")
    disc = _get_tag_value(tags, "discnumber")
    date = _get_tag_value(tags, "date")

    return {
        "title":        _get_tag_value(tags, "title"),
        "artist":       _get_tag_value(tags, "artist"),
        "album":        _get_tag_value(tags, "album"),
        "year":         date[:4] if date else "",
        "track":        track.split("/")[0] if track else "",
        "total_tracks": track.split("/")[1] if "/" in track else "",
        "disc":         disc.split("/")[0] if disc else "",
        "disc_total":   disc.split("/")[1] if "/" in disc else "",
        "genres":       _get_tag_values(tags, "genre"),
        "label":        _get_tag_value(tags, "label"),
        "composer":     _get_tag_value(tags, "composer"),
        "release_id":   "",
        "has_art":      _has_artwork(audio),
    }


def _read_vorbis_tags(path, empty):
    """Read Vorbis comments from OGG files."""
    try:
        audio = OggVorbis(path)
    except Exception:
        return empty

    tags = audio.tags or {}
    track = _get_tag_value(tags, "tracknumber")
    disc = _get_tag_value(tags, "discnumber")
    date = _get_tag_value(tags, "date")

    return {
        "title":        _get_tag_value(tags, "title"),
        "artist":       _get_tag_value(tags, "artist"),
        "album":        _get_tag_value(tags, "album"),
        "year":         date[:4] if date else "",
        "track":        track.split("/")[0] if track else "",
        "total_tracks": track.split("/")[1] if "/" in track else "",
        "disc":         disc.split("/")[0] if disc else "",
        "disc_total":   disc.split("/")[1] if "/" in disc else "",
        "genres":       _get_tag_values(tags, "genre"),
        "label":        _get_tag_value(tags, "label"),
        "composer":     _get_tag_value(tags, "composer"),
        "release_id":   "",
        "has_art":      _has_artwork(audio),
    }


def _read_mp4_tags(path, empty):
    """Read MP4/M4A tags."""
    try:
        audio = MP4(path)
    except Exception:
        return empty

    tags = audio.tags or {}
    track = str(tags.get("\xa9trk", [""])[0]) if "\xa9trk" in tags else ""
    disc = str(tags.get("\xa9disk", [""])[0]) if "\xa9disk" in tags else ""
    date = str(tags.get("\xa9day", [""])[0]) if "\xa9day" in tags else ""

    return {
        "title":        str(tags.get("\xa9nam", [""])[0]),
        "artist":       str(tags.get("\xa9ART", [""])[0]),
        "album":        str(tags.get("\xa9alb", [""])[0]),
        "year":         date[:4] if date else "",
        "track":        track.split("/")[0] if track else "",
        "total_tracks": track.split("/")[1] if "/" in track else "",
        "disc":         disc.split("/")[0] if disc else "",
        "disc_total":   disc.split("/")[1] if "/" in disc else "",
        "genres":       [str(x) for x in tags.get("\xa9gen", [])],
        "label":        str(tags.get("\xa9pub", [""])[0]),
        "composer":     str(tags.get("\xa9wrt", [""])[0]),
        "release_id":   "",
        "has_art":      _has_artwork(tags),
    }


def _read_wave_tags(path, empty):
    """Read tags from WAV files (ID3 in INFO chunk)."""
    try:
        audio = WAVE(path)
    except Exception:
        return empty

    tags = audio.tags
    if tags is None:
        return empty

    # WAV can have ID3 tags
    if hasattr(tags, "get"):
        return _read_id3_tags_from_dict(tags, empty)

    return empty


def _read_aiff_tags(path, empty):
    """Read tags from AIFF files."""
    try:
        audio = AIFF(path)
    except Exception:
        return empty

    tags = audio.tags
    if tags is None:
        return empty

    if hasattr(tags, "get"):
        return _read_id3_tags_from_dict(tags, empty)

    return empty


def _read_id3_tags_from_dict(tags, empty):
    """Read ID3-like tags from a dict-like tag object."""
    def g(k):
        v = tags.get(k)
        if v is None:
            return ""
        if hasattr(v, "text") and v.text:
            return str(v.text[0]).strip()
        if isinstance(v, list) and v:
            return str(v[0]).strip()
        return str(v).strip() if v else ""

    trck = g("TRCK")
    tpos = g("TPOS")

    return {
        "title":        g("TIT2"),
        "artist":       g("TPE1") or g("TPE2"),
        "album":        g("TALB"),
        "year":         g("TDRC")[:4] if g("TDRC") else "",
        "track":        trck.split("/")[0] if trck else "",
        "total_tracks": trck.split("/")[1] if "/" in trck else "",
        "disc":         tpos.split("/")[0] if tpos else "",
        "disc_total":   tpos.split("/")[1] if "/" in tpos else "",
        "genres":       _get_genres(tags),
        "label":        g("TPUB"),
        "composer":     g("TCOM"),
        "release_id":   "",
        "has_art":      _has_artwork(tags),
    }


def _read_generic_tags(audio, empty):
    """Read tags using generic mutagen.File() interface."""
    tags = audio.tags
    if tags is None:
        return empty

    # Try to get common keys
    title = _get_tag_value(tags, "title") or _get_tag_value(tags, "TIT2")
    artist = _get_tag_value(tags, "artist") or _get_tag_value(tags, "TPE1")
    album = _get_tag_value(tags, "album") or _get_tag_value(tags, "TALB")
    date = _get_tag_value(tags, "date") or _get_tag_value(tags, "TDRC")
    track = _get_tag_value(tags, "tracknumber") or _get_tag_value(tags, "TRCK")
    disc = _get_tag_value(tags, "discnumber") or _get_tag_value(tags, "TPOS")
    genres = _get_tag_values(tags, "genre") or _get_genres(tags)
    label = _get_tag_value(tags, "label") or _get_tag_value(tags, "TPUB")
    composer = _get_tag_value(tags, "composer") or _get_tag_value(tags, "TCOM")

    return {
        "title":        title,
        "artist":       artist,
        "album":        album,
        "year":         date[:4] if date else "",
        "track":        track.split("/")[0] if track else "",
        "total_tracks": track.split("/")[1] if "/" in track else "",
        "disc":         disc.split("/")[0] if disc else "",
        "disc_total":   disc.split("/")[1] if "/" in disc else "",
        "genres":       genres,
        "label":        label,
        "composer":     composer,
        "release_id":   "",
        "has_art":      _has_artwork(tags),
    }


def write_tags(path, meta, cover_bytes=None):
    """Write metadata tags to an audio file (any supported format)."""
    ext = Path(path).suffix.lower()

    if ext == ".mp3":
        _write_id3_tags(path, meta, cover_bytes)
    elif ext in (".flac",):
        _write_flac_tags(path, meta, cover_bytes)
    elif ext in (".ogg", ".oga"):
        _write_vorbis_tags(path, meta, cover_bytes)
    elif ext in (".m4a", ".mp4"):
        _write_mp4_tags(path, meta, cover_bytes)
    elif ext in (".wav",):
        _write_id3_tags(path, meta, cover_bytes)
    elif ext in (".aiff", ".aif"):
        _write_id3_tags(path, meta, cover_bytes)
    else:
        _write_id3_tags(path, meta, cover_bytes)


def _write_id3_tags(path, meta, cover_bytes=None):
    """Write ID3 tags to MP3/WAV/AIFF files."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    except Exception:
        return

    def s(k, cls, v):
        if v:
            tags.delall(k)
            tags.add(cls(encoding=3, text=[str(v)]))

    s("TIT2", TIT2, meta.get("title"))
    s("TPE1", TPE1, meta.get("artist"))
    s("TALB", TALB, meta.get("album"))
    s("TDRC", TDRC, meta.get("year"))
    s("TCOM", TCOM, meta.get("composer"))
    s("TPUB", TPUB, meta.get("label"))

    trck = meta.get("track", "")
    ttrc = meta.get("total_tracks", "")
    if trck:
        tags.delall("TRCK")
        tags.add(TRCK(encoding=3, text=[f"{trck}/{ttrc}" if ttrc else trck]))

    disc = meta.get("disc", "")
    dtot = meta.get("disc_total", "")
    if disc:
        tags.delall("TPOS")
        tags.add(TPOS(encoding=3, text=[f"{disc}/{dtot}" if dtot else disc]))

    genres = meta.get("genres", [])
    if genres:
        tags.delall("TCON")
        tags.add(TCON(encoding=3, text=["; ".join(genres)]))

    if cover_bytes and not meta.get("has_art"):
        tags.delall("APIC")
        tags.add(APIC(
            encoding=3, mime="image/jpeg",
            type=3, desc="Cover", data=cover_bytes,
        ))

    # Lyrics
    if meta.get("_lyrics_synced"):
        tags.delall("SYLT")
        tags.add(SYLT(encoding=3, lang="eng", desc="",
                      format=2,  # 2 = LRC timestamp format
                      text=meta["_lyrics_synced"]))
    if meta.get("_lyrics_plain"):
        tags.delall("USLT")
        tags.add(USLT(encoding=3, lang="eng", desc="",
                       text=meta["_lyrics_plain"]))

    tags.save(path)


def _write_flac_tags(path, meta, cover_bytes=None):
    """Write Vorbis comments to FLAC files."""
    try:
        audio = FLAC(path)
    except Exception:
        return

    tags = audio.tags
    if tags is None:
        audio.add_tags()
        tags = audio.tags

    # Only update managed keys (don't clear everything)
    managed = {"title", "artist", "album", "date", "tracknumber",
               "discnumber", "genre", "label", "composer", "lyrics",
               "METADATA_BLOCK_PICTURE"}
    for key in list(tags.keys()):
        if key.lower() in managed or key == "METADATA_BLOCK_PICTURE":
            del tags[key]

    if meta.get("title"):
        tags["title"] = [meta["title"]]
    if meta.get("artist"):
        tags["artist"] = [meta["artist"]]
    if meta.get("album"):
        tags["album"] = [meta["album"]]
    if meta.get("year"):
        tags["date"] = [meta["year"]]

    trck = meta.get("track", "")
    ttrc = meta.get("total_tracks", "")
    if trck:
        tags["tracknumber"] = [f"{trck}/{ttrc}" if ttrc else trck]

    disc = meta.get("disc", "")
    dtot = meta.get("disc_total", "")
    if disc:
        tags["discnumber"] = [f"{disc}/{dtot}" if dtot else disc]

    genres = meta.get("genres", [])
    if genres:
        tags["genre"] = genres

    if meta.get("label"):
        tags["label"] = [meta["label"]]
    if meta.get("composer"):
        tags["composer"] = [meta["composer"]]

    # Lyrics
    if meta.get("_lyrics_plain"):
        tags["lyrics"] = [meta["_lyrics_plain"]]

    # Cover art via METADATA_BLOCK_PICTURE
    if cover_bytes and not meta.get("has_art"):
        pic = Picture()
        pic.type = 3  # Cover (front)
        pic.mime = "image/jpeg"
        pic.desc = "Cover"
        pic.data = cover_bytes
        audio.clear_pictures()
        audio.add_picture(pic)

    audio.save(path)


def _write_vorbis_tags(path, meta, cover_bytes=None):
    """Write Vorbis comments to OGG files."""
    try:
        audio = OggVorbis(path)
    except Exception:
        return

    tags = audio.tags
    if tags is None:
        audio.add_tags()
        tags = audio.tags

    # Only update managed keys (don't clear everything)
    managed = {"title", "artist", "album", "date", "tracknumber",
               "discnumber", "genre", "label", "composer", "lyrics",
               "METADATA_BLOCK_PICTURE"}
    for key in list(tags.keys()):
        if key.lower() in managed or key == "METADATA_BLOCK_PICTURE":
            del tags[key]

    if meta.get("title"):
        tags["title"] = [meta["title"]]
    if meta.get("artist"):
        tags["artist"] = [meta["artist"]]
    if meta.get("album"):
        tags["album"] = [meta["album"]]
    if meta.get("year"):
        tags["date"] = [meta["year"]]

    trck = meta.get("track", "")
    ttrc = meta.get("total_tracks", "")
    if trck:
        tags["tracknumber"] = [f"{trck}/{ttrc}" if ttrc else trck]

    disc = meta.get("disc", "")
    dtot = meta.get("disc_total", "")
    if disc:
        tags["discnumber"] = [f"{disc}/{dtot}" if dtot else disc]

    genres = meta.get("genres", [])
    if genres:
        tags["genre"] = genres

    if meta.get("label"):
        tags["label"] = [meta["label"]]
    if meta.get("composer"):
        tags["composer"] = [meta["composer"]]

    # Lyrics
    if meta.get("_lyrics_plain"):
        tags["lyrics"] = [meta["_lyrics_plain"]]

    # Cover art via METADATA_BLOCK_PICTURE (base64 encoded in Vorbis comment)
    if cover_bytes and not meta.get("has_art"):
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.desc = "Cover"
        pic.data = cover_bytes
        b64_data = base64.b64encode(pic.write()).decode("ascii")
        tags["METADATA_BLOCK_PICTURE"] = [b64_data]

    audio.save(path)


def _write_mp4_tags(path, meta, cover_bytes=None):
    """Write MP4/M4A tags."""
    try:
        audio = MP4(path)
    except Exception:
        return

    if audio.tags is None:
        audio.add_tags()

    tags = audio.tags

    if meta.get("title"):
        tags["\xa9nam"] = [meta["title"]]
    if meta.get("artist"):
        tags["\xa9ART"] = [meta["artist"]]
    if meta.get("album"):
        tags["\xa9alb"] = [meta["album"]]
    if meta.get("year"):
        tags["\xa9day"] = [meta["year"]]

    trck = meta.get("track", "")
    ttrc = meta.get("total_tracks", "")
    if trck:
        tags["\xa9trk"] = [f"{trck}/{ttrc}" if ttrc else trck]

    disc = meta.get("disc", "")
    dtot = meta.get("disc_total", "")
    if disc:
        tags["\xa9disk"] = [f"{disc}/{dtot}" if dtot else disc]

    genres = meta.get("genres", [])
    if genres:
        tags["\xa9gen"] = genres

    if meta.get("label"):
        tags["\xa9pub"] = [meta["label"]]
    if meta.get("composer"):
        tags["\xa9wrt"] = [meta["composer"]]

    # Lyrics
    if meta.get("_lyrics_plain"):
        tags["\xa9lyr"] = [meta["_lyrics_plain"]]

    # Cover art
    if cover_bytes and not meta.get("has_art"):
        tags["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]

    audio.save(path)


# ── Filesystem ────────────────────────────────────────────────────────────────

SAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

def safe(name, maxlen=None):
    if maxlen is None:
        maxlen = _cfg["filename_max_length"]
    return (SAFE_RE.sub("_", str(name)).strip(". ") or "Unknown")[:maxlen]

def normalize_album_key(folder_name):
    name = re.sub(r'^\d{4}\s*-\s*', '', folder_name).strip()
    return re.sub(r'[^a-z0-9]', '', name.lower())

def folder_score(folder_name):
    return 1 if re.match(r'^\d{4}\s*-\s*', folder_name) else 0

def destination(root, meta):
    artist = safe(meta.get("artist") or "Unknown Artist")
    album  = safe(meta.get("album")  or "Unknown Album")
    year   = meta.get("year", "")
    folder = f"{year} - {album}" if year else album
    track  = meta.get("track", "").zfill(2) if meta.get("track") else ""
    title  = safe(meta.get("title")  or "Unknown Title")
    ext    = meta.get("_extension", ".mp3")
    fname  = f"{track} - {title}{ext}" if track else f"{title}{ext}"
    return Path(root) / artist / folder / fname

def collect_audio_files(folder):
    """Collect all supported audio files from a folder (recursively).
    Does not follow symlinks to prevent infinite loops."""
    exts = _cfg.supported_extensions
    result = []
    for dirpath, _, files in os.walk(folder, followlinks=False):
        for f in files:
            if Path(f).suffix.lower() in exts:
                result.append(os.path.join(dirpath, f))
    return sorted(result)


def collect_mp3s(folder):
    """Legacy alias — collects all supported audio files."""
    return collect_audio_files(folder)


# ── Duplicate album merge ─────────────────────────────────────────────────────

def merge_duplicate_albums(output_root, log_cb=None):
    def log(m):
        if log_cb: log_cb(m)
    output_root  = Path(output_root)
    merged_count = 0
    for artist_dir in sorted(output_root.iterdir()):
        if not artist_dir.is_dir(): continue
        groups = {}
        for album_dir in sorted(artist_dir.iterdir()):
            if not album_dir.is_dir(): continue
            groups.setdefault(normalize_album_key(album_dir.name), []).append(album_dir)
        for key, dirs in groups.items():
            if len(dirs) < 2: continue
            def sort_key(d):
                m = re.match(r'^(\d{4})', d.name)
                return (-folder_score(d.name), int(m.group(1)) if m else 9999)
            dirs_sorted = sorted(dirs, key=sort_key)
            winner, losers = dirs_sorted[0], dirs_sorted[1:]
            log(f"  \U0001f500 Merging into: {artist_dir.name}/{winner.name}")
            for loser in losers:
                log(f"      \u2190 absorbing: {loser.name}")
                # Move all supported audio files (not just .mp3)
                for src_file in collect_audio_files(loser):
                    dst_file = winner / Path(src_file).relative_to(loser)
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    if not dst_file.exists():
                        shutil.move(str(src_file), str(dst_file))
                    else:
                        log(f"      ! skipped (exists): {dst_file.name}")
                for src_img in loser.glob("cover.*"):
                    dst_img = winner / src_img.name
                    if not dst_img.exists():
                        shutil.move(str(src_img), str(dst_img))
                try:
                    shutil.rmtree(str(loser))
                    merged_count += 1
                except Exception as e:
                    log(f"      ! could not remove {loser.name}: {e}")
    log(f"  \u2705 Merged {merged_count} duplicate album folder(s)"
        if merged_count else "  \u2705 No duplicate album folders found")
    return merged_count


# ── Process one file ──────────────────────────────────────────────────────────

def _is_confident_match(mb_result, original_meta):
    """Check if MusicBrainz result is confident enough to overwrite existing tags."""
    # Must have at least a release_id to be considered
    if not mb_result.get("release_id"):
        return False
    # If both titles exist and differ, require album match too
    orig_title = original_meta.get("title", "").lower().strip()
    mb_title = mb_result.get("title", "").lower().strip()
    if orig_title and mb_title and orig_title != mb_title:
        orig_album = original_meta.get("album", "").lower().strip()
        mb_album = mb_result.get("album", "").lower().strip()
        return bool(orig_album and mb_album and orig_album == mb_album)
    return True


def process_file(path, dst, opts, stats, log_cb=None):
    def log(msg):
        if log_cb: log_cb(msg)

    ext = Path(path).suffix.lower()
    meta   = read_tags(path)
    meta["_extension"] = ext  # preserve original format
    source = "tags"

    # 1. MusicBrainz
    if meta.get("artist") or meta.get("title"):
        mb = search_mb(meta.get("artist", ""), meta.get("title", ""), meta.get("album", ""))
        if mb:
            confident = _is_confident_match(mb, meta)
            for k in ("title", "artist", "album", "year", "track", "disc",
                      "total_tracks", "disc_total", "label", "composer", "release_id"):
                if mb.get(k):
                    if meta.get(k) and meta[k] != mb[k] and not confident:
                        log(f"  ~ Keeping existing {k}: {meta[k]}")
                    else:
                        meta[k] = mb[k]
            if not meta.get("genres") and mb.get("genres"):
                meta["genres"] = mb["genres"]
            source = "MusicBrainz"
            gstr = f" [{', '.join(meta['genres'][:2])}]" if meta.get("genres") else ""
            log(f"  \u2713 Identified: {meta.get('artist')} \u2014 {meta.get('title')}{gstr}")

    # 2. AcoustID fingerprint fallback
    if source == "tags" and opts.get("acoustid", True):
        if find_fpcalc():
            log("  \u27f3 Fingerprinting audio\u2026")
            ac = acoustid_lookup(path)
            if ac:
                confident = _is_confident_match(ac, meta)
                for k in ("title", "artist", "album", "year", "track", "disc",
                          "total_tracks", "disc_total", "release_id"):
                    if ac.get(k):
                        if meta.get(k) and meta[k] != ac[k] and not confident:
                            log(f"  ~ Keeping existing {k}: {meta[k]}")
                        else:
                            meta[k] = ac[k]
                source = "AcoustID"
                log(f"  \u2713 Identified: {meta.get('artist')} \u2014 {meta.get('title')}")
                if meta.get("release_id") and not meta.get("genres"):
                    detail = _mb_release_detail(meta["release_id"])
                    if detail:
                        genres = _mb_genres({}, detail)
                        if genres:
                            meta["genres"] = genres
                            log(f"  genres: {', '.join(genres)}")
                        lbl_info = detail.get("label-info", [])
                        if lbl_info and not meta.get("label"):
                            meta["label"] = (lbl_info[0].get("label") or {}).get("name", "")
        else:
            log("  \u26a0 Fingerprinting unavailable \u2014 using basic lookup")

    # 3. Last.fm genre fallback
    if not meta.get("genres") and meta.get("artist") and meta.get("title"):
        lfm = lastfm_genres(meta["artist"], meta["title"])
        if lfm:
            meta["genres"] = lfm
            log(f"  \u2713 Genres found: {', '.join(lfm)}")

    if source == "tags":
        log("  \u2717 Could not identify \u2014 using existing tags")

    if not meta.get("title"):  meta["title"]  = Path(path).stem
    if not meta.get("artist"): meta["artist"] = "Unknown Artist"
    if not meta.get("album"):  meta["album"]  = "Unknown Album"

    # 4. Lyrics
    if opts.get("fetch_lyrics", True) and meta.get("artist") and meta.get("title"):
        plain, synced = fetch_lyrics(
            meta["artist"], meta["title"],
            meta.get("album", ""), 0)
        if plain or synced:
            meta["_lyrics_plain"] = plain
            meta["_lyrics_synced"] = synced
            log("  \U0001f4dd Lyrics found")
        else:
            log("  \u2014 No lyrics available")

    # 5. Album art — always fetch if release_id is known
    cover_bytes = None
    if opts.get("fetch_art", True) and meta.get("release_id"):
        log("  \U0001f5bc Fetching album art\u2026")
        cover_bytes = fetch_cover_art(meta["release_id"])
        if cover_bytes:
            log(f"  \u2713 Album art fetched ({len(cover_bytes)//1024} KB)")
        else:
            log("  \u26a0 Album art not found in Cover Art Archive")

    # 6. Write tags — write if metadata was enriched OR if lyrics/art were fetched
    has_new_data = source != "tags" or meta.get("_lyrics_plain") or meta.get("_lyrics_synced") or cover_bytes
    if opts.get("write_tags", True) and has_new_data:
        try:
            write_tags(path, meta, cover_bytes=cover_bytes)
        except Exception as e:
            log(f"  ! Tag write failed: {e}")

    # 7. Copy / move
    dest = destination(dst, meta)

    if opts.get("dry_run", False):
        stats["ok"] += 1
        log(f"  [DRY] \u2192 {dest}")
        return meta, source, "dry-run", str(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)

    if cover_bytes:
        saved = save_folder_cover(dest.parent, cover_bytes,
                                  overwrite=opts.get("overwrite_art", False))
        if saved:
            log(f"  \U0001f5bc cover.jpg \u2192 {dest.parent.name}/")

    status = "ok"
    if dest.exists() and not opts.get("overwrite", False):
        status = "skipped"; stats["skipped"] += 1
        log(f"  \u21b7 Skipped (exists): {dest.name}")
    else:
        try:
            (shutil.copy2 if opts.get("copy", True) else shutil.move)(path, dest)
            stats["ok"] += 1
            log(f"  \u2192 {dest}")
        except Exception as e:
            status = "error"; stats["errors"] += 1
            log(f"  \u2717 Error: {e}")

    return meta, source, status, str(dest)
