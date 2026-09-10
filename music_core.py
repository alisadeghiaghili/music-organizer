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
from datetime import datetime, timezone
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
from matching import (
    DEFAULT_ALBUM_MIN_SCORE,
    DEFAULT_RECORDING_MIN_SCORE,
    normalize_album_key as _normalize_album_key_unicode,
    pick_best_recording,
    select_best_release,
)

_cfg = get_config()

MB_BASE   = _cfg["mb_base_url"]
CAA_BASE  = _cfg["caa_base_url"]
LASTFM_KEY = _cfg.get("lastfm_api_key", "")
HEADERS   = {"User-Agent": _cfg["user_agent"]}
_last_mb  = 0.0
_mb_lock  = threading.Lock()

# ── API Response Cache ───────────────────────────────────────────────────────────────
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


# ── MusicBrainz helpers ─────────────────────────────────────────────────────

def mb_get(endpoint, params, retries=1):
    """Fetch from MusicBrainz with rate limiting, caching, and retry."""
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
                    time.sleep(2)
                    continue
                return None
    return None


def _best_release(releases, desired_album=""):
    """Select the best release using album-centric library policy.

    Delegates to matching.select_best_release (prefer oldest studio album;
    prefer the user's album title).

    Args:
        releases: MusicBrainz release list.
        desired_album: Local album tag used as the primary target.

    Returns:
        Tuple ``(release_or_None, year_or_None)``.
    """
    best, year = select_best_release(releases, desired_album=desired_album or "")
    return best, year


def _lucene_escape(value: str) -> str:
    """Escape Lucene special characters in a MusicBrainz query term."""
    specials = r'+-&|!(){}[]^"~*?:\/'
    out = []
    for ch in str(value or ""):
        if ch in specials:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def _mb_query_parts(artist, title, album=""):
    parts = []
    if title:
        parts.append(f'recording:"{_lucene_escape(title)}"')
    if artist:
        parts.append(f'artist:"{_lucene_escape(artist)}"')
    if album:
        parts.append(f'release:"{_lucene_escape(album)}"')
    return " AND ".join(parts)


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
    """Search MusicBrainz for metadata with album-centric scoring.

    Strategy:
      1. Query recordings (with album constraint when known).
      2. Score all candidates and keep the best above threshold.
      3. Score that recording's releases against the user's album tag;
         prefer oldest studio album matching the desired album.
      4. Never invent a track number from media[0].

    Args:
        artist: Local artist tag.
        title: Local title tag.
        album: Local album tag used both as query hint and release target.

    Returns:
        Metadata dict, or None when no candidate clears the acceptance bar.
    """
    if not (artist or title):
        return None

    recordings = []

    def _search(query):
        data = mb_get("recording", {
            "query": query,
            "limit": 10,
            "inc": "genres+tags+releases",
        })
        if data and data.get("recordings"):
            return data["recordings"]
        return []

    primary = _mb_query_parts(artist, title, album)
    if primary:
        recordings = _search(primary)
    if not recordings and album:
        # Album-constrained search can miss on remaster/deluxe tags.
        fallback = _mb_query_parts(artist, title, "")
        if fallback:
            recordings = _search(fallback)
    if not recordings and not album:
        recordings = _search(_mb_query_parts(artist, title, ""))

    if not recordings:
        return None

    rec, rec_score = pick_best_recording(
        recordings,
        query_artist=artist or "",
        query_title=title or "",
        query_album=album or "",
        min_score=DEFAULT_RECORDING_MIN_SCORE,
    )
    if rec is None:
        return None

    recording_id = rec.get("id", "")
    credits = rec.get("artist-credit") or []
    mb_artist = ""
    if credits:
        mb_artist = str((credits[0].get("artist") or {}).get("name") or "")

    result = {
        "title":        rec.get("title", ""),
        "artist":       mb_artist or artist,
        "album":        "", "year": "", "track": "", "disc": "",
        "disc_total":   "", "total_tracks": "",
        "genres":       [], "label": "", "composer": "", "release_id": "",
        "_recording_score": rec_score,
        "_release_score": 0.0,
    }

    releases = rec.get("releases") or []
    if releases:
        rel, year = select_best_release(releases, desired_album=album or "")
        if rel is not None:
            release_score = 0.0
            from matching import score_release_for_library, should_accept_release
            release_score = score_release_for_library(
                rel, desired_album=album or "", prefer_oldest=True
            )
            result["_release_score"] = release_score
            # Album/year/track only when the release clears the bar, or when
            # the user had no album tag (best-effort identification).
            accept = should_accept_release(release_score, DEFAULT_ALBUM_MIN_SCORE)
            if accept or not album:
                result["release_id"] = rel.get("id", "")
                result["album"] = rel.get("title", album)
                result["year"] = str(year) if year is not None else ""
                media = rel.get("media") or []
                found_track = False
                if media:
                    result["disc_total"] = str(len(media)) if len(media) > 1 else ""
                    for medium in media:
                        for track in medium.get("track") or []:
                            if track.get("recording", {}).get("id") == recording_id:
                                if len(media) > 1:
                                    result["disc"] = str(medium.get("position", ""))
                                result["track"] = str(track.get("number", ""))
                                result["total_tracks"] = str(
                                    medium.get("track-count", "")
                                )
                                found_track = True
                                break
                        if found_track:
                            break
                # Never fabricate track from media[0].

    detail = _mb_release_detail(result["release_id"])
    if detail:
        lbl_info = detail.get("label-info") or []
        if lbl_info:
            result["label"] = (lbl_info[0].get("label") or {}).get("name", "")
        result["genres"] = _mb_genres(rec, detail)
    if not result["genres"]:
        result["genres"] = _mb_genres(rec, None)

    return result


# ── Last.fm genre fallback ──────────────────────────────────────────────────

def lastfm_genres(artist, title, api_key=None, retries=1):
    """Fetch genres from Last.fm with caching and retry."""
    key = api_key or LASTFM_KEY
    if not key:
        return []

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


# ── Lyrics (LRCLIB) ────────────────────────────────────────────────────────────

def fetch_lyrics(artist, title, album="", duration=0, retries=1):
    """Fetch lyrics from LRCLIB (free, no API key) with caching and retry.
    Returns (plain_lyrics, synced_lyrics) or (None, None).
    synced_lyrics is in standard LRC format [MM:SS.xx] text.
    """
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


def _parse_lrc_to_sylt(lrc_text):
    """Convert LRC-format lyrics to SYLT (text, milliseconds) tuples.

    Accepts common LRC timestamp shapes:
      ``[MM:SS]``, ``[M:SS]``, ``[MM:SS.x]``, ``[MM:SS.xx]``, ``[MM:SS.xxx]``
    Metadata tags such as ``[ar:...]`` are skipped.

    Args:
        lrc_text: Raw LRC string, or empty/None.

    Returns:
        List of ``(lyric_text, timestamp_ms)`` sorted by timestamp.

    Examples:
        >>> _parse_lrc_to_sylt("[00:12.50] hello")
        [('hello', 12500)]
        >>> _parse_lrc_to_sylt("[00:12] hello")
        [('hello', 12000)]
    """
    if not lrc_text:
        return []
    result = []
    # minutes (1-2 digits), seconds (1-2), optional .fraction (1-3)
    lrc_re = re.compile(r'^\[(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?\](.*)$')
    for line in lrc_text.splitlines():
        m = lrc_re.match(line.strip())
        if not m:
            continue
        minutes, seconds, frac, text = m.groups()
        frac = frac or "0"
        # 1 digit → tenths, 2 → centiseconds, 3 → milliseconds
        if len(frac) == 1:
            frac_ms = int(frac) * 100
        elif len(frac) == 2:
            frac_ms = int(frac) * 10
        else:
            frac_ms = int(frac)
        ms = int(minutes) * 60_000 + int(seconds) * 1_000 + frac_ms
        result.append((text.strip(), ms))
    result.sort(key=lambda item: item[1])
    return result


def _get_audio_duration(path):
    """Return audio duration in seconds (float), or 0 on failure."""
    try:
        audio = MutagenFile(path)
        if audio is not None and audio.info is not None:
            return audio.info.length
    except Exception:
        pass
    return 0


# ── Cover Art Archive ────────────────────────────────────────────────────────────

def fetch_cover_art(release_id, size="large", retries=1):
    """Fetch album art from Cover Art Archive with caching and retry."""
    if not release_id:
        return None

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


# ── fpcalc / AcoustID ────────────────────────────────────────────────────────────

def find_fpcalc():
    fname = "fpcalc.exe" if os.name == "nt" else "fpcalc"

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / fname
        if p.exists():
            return str(p)

    if getattr(sys, "frozen", False):
        p = Path(sys.executable).parent / fname
    else:
        p = Path(__file__).parent / fname
    if p.exists():
        return str(p)

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
        rel, yr = _best_release(rec["releases"], desired_album="")
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


# ── Tags ─────────────────────────────────────────────────────────────────────────────

def _get_tag_value(tags, key):
    """Extract a string value from a tag, handling various formats."""
    v = tags.get(key)
    if v is None:
        return ""
    if hasattr(v, "text"):
        texts = v.text
        if texts:
            return str(texts[0]).strip()
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
    tcon = tags.get("TCON")
    if tcon is not None:
        if hasattr(tcon, "genres") and tcon.genres:
            genres = [x.strip().title() for x in tcon.genres if x.strip()]
        elif hasattr(tcon, "text"):
            genres = [x.strip().title() for x in tcon.text if x.strip()]
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
    apic = tags.get("APIC")
    if apic:
        return True
    covr = tags.get("covr") or tags.get("COVR")
    if covr:
        return True
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

    # Synced lyrics: convert LRC string → list of (text, ms) tuples for SYLT
    sylt_data = _parse_lrc_to_sylt(meta.get("_lyrics_synced"))
    if sylt_data:
        tags.delall("SYLT")
        tags.add(SYLT(
            encoding=3, lang="eng", desc="",
            format=2,   # 2 = milliseconds
            type=1,     # 1 = lyrics
            text=sylt_data,
        ))

    # Plain / unsynced lyrics
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

    managed = {"title", "artist", "album", "date", "tracknumber",
               "discnumber", "genre", "label", "composer", "lyrics",
               "METADATA_BLOCK_PICTURE"}
    for key in list(tags.keys()):
        if key.lower() in managed or key == "METADATA_BLOCK_PICTURE":
            del tags[key]

    if meta.get("title"):    tags["title"]  = [meta["title"]]
    if meta.get("artist"):   tags["artist"] = [meta["artist"]]
    if meta.get("album"):    tags["album"]  = [meta["album"]]
    if meta.get("year"):     tags["date"]   = [meta["year"]]

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

    if meta.get("label"):    tags["label"]    = [meta["label"]]
    if meta.get("composer"): tags["composer"] = [meta["composer"]]

    # FLAC stores plain lyrics; synced LRC stored as-is in "lyrics" tag
    if meta.get("_lyrics_synced"):
        tags["lyrics"] = [meta["_lyrics_synced"]]
    elif meta.get("_lyrics_plain"):
        tags["lyrics"] = [meta["_lyrics_plain"]]

    if cover_bytes and not meta.get("has_art"):
        pic = Picture()
        pic.type = 3
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

    managed = {"title", "artist", "album", "date", "tracknumber",
               "discnumber", "genre", "label", "composer", "lyrics",
               "METADATA_BLOCK_PICTURE"}
    for key in list(tags.keys()):
        if key.lower() in managed or key == "METADATA_BLOCK_PICTURE":
            del tags[key]

    if meta.get("title"):    tags["title"]  = [meta["title"]]
    if meta.get("artist"):   tags["artist"] = [meta["artist"]]
    if meta.get("album"):    tags["album"]  = [meta["album"]]
    if meta.get("year"):     tags["date"]   = [meta["year"]]

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

    if meta.get("label"):    tags["label"]    = [meta["label"]]
    if meta.get("composer"): tags["composer"] = [meta["composer"]]

    # OGG stores plain lyrics; synced LRC stored as-is in "lyrics" tag
    if meta.get("_lyrics_synced"):
        tags["lyrics"] = [meta["_lyrics_synced"]]
    elif meta.get("_lyrics_plain"):
        tags["lyrics"] = [meta["_lyrics_plain"]]

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

    if meta.get("title"):    tags["\xa9nam"] = [meta["title"]]
    if meta.get("artist"):   tags["\xa9ART"] = [meta["artist"]]
    if meta.get("album"):    tags["\xa9alb"] = [meta["album"]]
    if meta.get("year"):     tags["\xa9day"] = [meta["year"]]

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

    if meta.get("label"):    tags["\xa9pub"] = [meta["label"]]
    if meta.get("composer"): tags["\xa9wrt"] = [meta["composer"]]

    # MP4 stores plain lyrics; synced LRC stored as-is
    if meta.get("_lyrics_synced"):
        tags["\xa9lyr"] = [meta["_lyrics_synced"]]
    elif meta.get("_lyrics_plain"):
        tags["\xa9lyr"] = [meta["_lyrics_plain"]]

    if cover_bytes and not meta.get("has_art"):
        tags["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]

    audio.save(path)


# ── Filesystem ──────────────────────────────────────────────────────────────────────────

SAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

def safe(name, maxlen=None):
    if maxlen is None:
        maxlen = _cfg["filename_max_length"]
    return (SAFE_RE.sub("_", str(name)).strip(". ") or "Unknown")[:maxlen]

def normalize_album_key(folder_name):
    """Unicode-safe album folder key (see matching.normalize_album_key)."""
    return _normalize_album_key_unicode(folder_name)

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


# ── Journal ───────────────────────────────────────────────────────────────────────────

JOURNAL_FILENAME = "organize-journal.jsonl"


def journal_append(output_root, action, src=None, dst=None, extra=None):
    """Append one filesystem-mutation record to the output journal.

    Args:
        output_root: Directory that owns ``organize-journal.jsonl``.
        action: One of ``copy``, ``move``, ``tag``, ``merge``, ``skip``.
        src: Source path (optional).
        dst: Destination path (optional).
        extra: Optional dict of additional JSON-serializable fields.

    Returns:
        Path to the journal file.

    Examples:
        >>> journal_append("/tmp/out", "copy", src="a.mp3", dst="/tmp/out/a.mp3")
        PosixPath('/tmp/out/organize-journal.jsonl')
    """
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    journal_path = root / JOURNAL_FILENAME
    entry = {
        "ts": datetime.now(tz=timezone.utc)
        .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "action": action,
    }
    if src is not None:
        entry["src"] = str(src)
    if dst is not None:
        entry["dst"] = str(dst)
    if extra:
        entry.update(extra)
    with open(journal_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return journal_path


def _merge_tree(src_dir, dst_dir, log):
    """Move every file/dir under src_dir into dst_dir without deleting data.

    Existing destination files are skipped (source file is left in place).
    """
    moved = 0
    for item in sorted(src_dir.iterdir()):
        target = dst_dir / item.name
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            moved += _merge_tree(item, target, log)
            try:
                item.rmdir()
            except OSError:
                pass
            continue
        if target.exists():
            log(f"      ! skipped (exists): {item.name}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item), str(target))
        moved += 1
    return moved


# ── Duplicate album merge ────────────────────────────────────────────────────────────

def merge_duplicate_albums(output_root, log_cb=None, journal=True):
    """Merge album folders that normalize to the same key.

    Moves the entire folder contents (audio, covers, cue/log/nfo sidecars)
    into the winner directory, then removes the emptied loser directory.

    Args:
        output_root: Library root containing ``Artist/Album`` folders.
        log_cb: Optional callable(str) for progress messages.
        journal: When True, record each merge in ``organize-journal.jsonl``.

    Returns:
        Number of loser folders merged (removed).
    """
    def log(m):
        if log_cb: log_cb(m)
    output_root  = Path(output_root)
    if not output_root.exists():
        return 0
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
                try:
                    _merge_tree(loser, winner, log)
                    # Remove any leftover skipped files? Leave them — do not rmtree data.
                    leftover = [p.name for p in loser.rglob("*") if p.is_file()]
                    if leftover:
                        log(f"      ! kept in place (name conflicts): {len(leftover)} file(s)")
                        continue
                    shutil.rmtree(str(loser))
                    merged_count += 1
                    if journal:
                        journal_append(
                            output_root, "merge",
                            src=str(loser), dst=str(winner),
                            extra={"artist": artist_dir.name, "key": key},
                        )
                except Exception as e:
                    log(f"      ! could not merge {loser.name}: {e}")
    log(f"  \u2705 Merged {merged_count} duplicate album folder(s)"
        if merged_count else "  \u2705 No duplicate album folders found")
    return merged_count


# ── Process one file ────────────────────────────────────────────────────────────────

def _is_confident_match(mb_result, original_meta):
    """Check if MusicBrainz result is confident enough to overwrite existing tags."""
    if not mb_result.get("release_id"):
        return False
    orig_title = original_meta.get("title", "").lower().strip()
    mb_title = mb_result.get("title", "").lower().strip()
    if orig_title and mb_title and orig_title != mb_title:
        orig_album = original_meta.get("album", "").lower().strip()
        mb_album = mb_result.get("album", "").lower().strip()
        return bool(orig_album and mb_album and orig_album == mb_album)
    return True


def process_file(path, dst, opts, stats, log_cb=None):
    """Enrich metadata and place one audio file under ``dst``.

    Safety contract (Phase A):
      * ``dry_run`` performs network lookups only — zero filesystem writes.
      * Source file tags are never rewritten. Enriched tags are written to
        the destination copy after copy/move.
      * When ``opts['journal']`` is true (default), copy/move/tag/merge are
        recorded in ``dst/organize-journal.jsonl``.

    Args:
        path: Absolute path of the source audio file.
        dst: Output library root.
        opts: Processing options (copy, dry_run, write_tags, fetch_*, journal, ...).
        stats: Mutable dict with ``ok``/``skipped``/``errors`` counters.
        log_cb: Optional callable(str) logger.

    Returns:
        Tuple ``(meta, source, status, dest_path)``.
    """
    def log(msg):
        if log_cb: log_cb(msg)

    def jour(action, src=None, dest=None, extra=None):
        if opts.get("journal", True) and not opts.get("dry_run", False):
            try:
                journal_append(dst, action, src=src, dst=dest, extra=extra)
            except Exception as e:
                log(f"  ! journal write failed: {e}")

    ext = Path(path).suffix.lower()
    meta   = read_tags(path)
    meta["_extension"] = ext
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
            log(f"  ✓ Identified: {meta.get('artist')} — {meta.get('title')}{gstr}")

    # 2. AcoustID fingerprint fallback
    if source == "tags" and opts.get("acoustid", True):
        if find_fpcalc():
            log("  ⟳ Fingerprinting audio…")
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
                log(f"  ✓ Identified: {meta.get('artist')} — {meta.get('title')}")
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
            log("  ⚠ Fingerprinting unavailable — using basic lookup")

    # 3. Last.fm genre fallback
    if not meta.get("genres") and meta.get("artist") and meta.get("title"):
        lfm = lastfm_genres(meta["artist"], meta["title"])
        if lfm:
            meta["genres"] = lfm
            log(f"  ✓ Genres found: {', '.join(lfm)}")

    if source == "tags":
        log("  ✗ Could not identify — using existing tags")

    if not meta.get("title"):  meta["title"]  = Path(path).stem
    if not meta.get("artist"): meta["artist"] = "Unknown Artist"
    if not meta.get("album"):  meta["album"]  = "Unknown Album"

    # 4. Lyrics
    if opts.get("fetch_lyrics", True) and meta.get("artist") and meta.get("title"):
        duration = _get_audio_duration(path)
        plain, synced = fetch_lyrics(
            meta["artist"], meta["title"],
            meta.get("album", ""), duration)
        if plain or synced:
            meta["_lyrics_plain"]  = plain
            meta["_lyrics_synced"] = synced
            log("  📝 Lyrics found")
        else:
            log("  — No lyrics available")

    # 5. Album art (network only; disk write after dry_run gate)
    cover_bytes = None
    if opts.get("fetch_art", True) and meta.get("release_id"):
        log("  🖼 Fetching album art…")
        cover_bytes = fetch_cover_art(meta["release_id"])
        if cover_bytes:
            log(f"  ✓ Album art fetched ({len(cover_bytes)//1024} KB)")
        else:
            log("  ⚠ Album art not found in Cover Art Archive")

    dest = destination(dst, meta)

    # 6. DRY RUN — stop before any filesystem mutation
    if opts.get("dry_run", False):
        stats["ok"] += 1
        log(f"  [DRY] → {dest}")
        return meta, source, "dry-run", str(dest)

    # 7. Copy / move first (source stays immutable in copy mode)
    dest.parent.mkdir(parents=True, exist_ok=True)
    status = "ok"
    if dest.exists() and not opts.get("overwrite", False):
        status = "skipped"; stats["skipped"] += 1
        log(f"  ↷ Skipped (exists): {dest.name}")
        jour("skip", src=path, dest=dest)
        return meta, source, status, str(dest)

    try:
        (shutil.copy2 if opts.get("copy", True) else shutil.move)(path, dest)
        stats["ok"] += 1
        log(f"  → {dest}")
        jour("copy" if opts.get("copy", True) else "move", src=path, dest=dest)
    except Exception as e:
        status = "error"; stats["errors"] += 1
        log(f"  ✗ Error: {e}")
        return meta, source, status, str(dest)

    # 8. Write enriched tags onto the DESTINATION only
    has_new_data = (
        source != "tags"
        or meta.get("_lyrics_plain")
        or meta.get("_lyrics_synced")
        or cover_bytes
    )
    if opts.get("write_tags", True) and has_new_data:
        try:
            write_tags(dest, meta, cover_bytes=cover_bytes)
            jour("tag", src=path, dest=dest)
        except Exception as e:
            log(f"  ! Tag write failed: {e}")
            stats["errors"] += 1

    # 9. Folder cover next to destination
    if cover_bytes:
        saved = save_folder_cover(dest.parent, cover_bytes,
                                  overwrite=opts.get("overwrite_art", False))
        if saved:
            log(f"  🖼 cover.jpg → {dest.parent.name}/")

    return meta, source, status, str(dest)
