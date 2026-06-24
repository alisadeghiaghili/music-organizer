#!/usr/bin/env python3
"""music_core.py — shared logic for Music Organizer (GUI + CLI)

Features:
  • MusicBrainz metadata (title, artist, album, year, track, disc,
    total_tracks, disc_total, label, composer, genres)
  • AcoustID audio fingerprinting fallback
  • Cover Art Archive album art (fetch + embed + save cover.jpg)
  • Last.fm genre fallback (optional — needs API key)
  • fpcalc resolved from _MEIPASS (PyInstaller), disk, or PATH
"""

import os, re, sys, time, shutil, json, subprocess, urllib.request, urllib.parse, threading
from pathlib import Path
from mutagen.id3 import (
    ID3, ID3NoHeaderError,
    TIT2, TPE1, TPE2, TALB, TDRC, TRCK, TCON, TCOM, TPUB, TPOS, APIC,
)

MB_BASE   = "https://musicbrainz.org/ws/2"
CAA_BASE  = "https://coverartarchive.org"
LASTFM_KEY = ""          # optional – set your Last.fm API key here
HEADERS   = {"User-Agent": "MusicOrganizer/1.0 (github.com/alisadeghiaghili/music-organizer)"}
_last_mb  = 0.0
_mb_lock  = threading.Lock()


# ── MusicBrainz helpers ───────────────────────────────────────────────────────

def mb_get(endpoint, params):
    global _last_mb
    with _mb_lock:
        gap = 1.1 - (time.time() - _last_mb)
        if gap > 0:
            time.sleep(gap)
        url = f"{MB_BASE}/{endpoint}?" + urllib.parse.urlencode({**params, "fmt": "json"})
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                _last_mb = time.time()
                return json.loads(r.read().decode())
        except Exception:
            _last_mb = time.time()
            return None


def _best_release(releases):
    best, best_year = None, 9999
    for rel in releases:
        date = rel.get("date", "")
        year = int(date[:4]) if date and date[:4].isdigit() else 9999
        if year < best_year:
            best_year = year
            best = rel
    return best, best_year


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
    parts = []
    if title:  parts.append(f'recording:"{title}"')
    if artist: parts.append(f'artistname:"{artist}"')
    if album:  parts.append(f'release:"{album}"')
    if not parts:
        return None
    data = mb_get("recording",
                  {"query": " AND ".join(parts), "limit": 5,
                   "inc": "genres+tags+releases"})
    if not data or not data.get("recordings"):
        return None

    rec = data["recordings"][0]
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
                result["disc_total"]    = str(len(media)) if len(media) > 1 else ""
                m0 = media[0]
                result["disc"]         = str(m0.get("position", "")) if len(media) > 1 else ""
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

def lastfm_genres(artist, title, api_key=None):
    key = api_key or LASTFM_KEY
    if not key:
        return []
    params = urllib.parse.urlencode({
        "method": "track.getInfo", "api_key": key,
        "artist": artist, "track": title, "format": "json",
    })
    try:
        req = urllib.request.Request(
            f"https://ws.audioscrobbler.com/2.0/?{params}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        tags = data.get("track", {}).get("toptags", {}).get("tag", [])
        return [t["name"].title() for t in tags[:4] if t.get("name")]
    except Exception:
        return []


# ── Cover Art Archive ─────────────────────────────────────────────────────────

def fetch_cover_art(release_id, size="large"):
    if not release_id:
        return None
    for url in [
        f"{CAA_BASE}/release/{release_id}/front-{size}",
        f"{CAA_BASE}/release/{release_id}/front",
    ]:
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read()
        except Exception:
            continue
    return None


def save_folder_cover(album_dir: Path, img_bytes: bytes):
    cover_path = album_dir / "cover.jpg"
    if not cover_path.exists():
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


def acoustid_lookup(filepath, api_key="8XaBELgH"):
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
    url = (
        f"https://api.acoustid.org/v2/lookup?client={api_key}"
        f"&duration={int(fp.get('duration', 0))}"
        f"&fingerprint={fp.get('fingerprint', '')}"
        "&meta=recordings+releases+tracks+releasegroups+compress"
    )
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception:
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
    return {
        "title": title, "artist": artist, "album": album,
        "year": year, "track": track, "disc": "",
        "genres": [], "label": "", "composer": "",
        "total_tracks": "", "disc_total": "", "release_id": release_id,
    }


# ── Tags ──────────────────────────────────────────────────────────────────────

def read_tags(path):
    empty = {
        "title": "", "artist": "", "album": "", "year": "", "track": "",
        "disc": "", "genres": [], "label": "", "composer": "",
        "total_tracks": "", "disc_total": "", "release_id": "", "has_art": False,
    }
    try:
        tags = ID3(path)
    except Exception:
        return empty

    def g(k):
        v = tags.get(k)
        return str(v.text[0]).strip() if v and v.text else ""

    tcon = tags.get("TCON")
    genres = []
    if tcon:
        if hasattr(tcon, "genres") and tcon.genres:
            genres = [x.strip().title() for x in tcon.genres if x.strip()]
        elif tcon.text:
            genres = [x.strip().title() for x in tcon.text if x.strip()]

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
        "genres":       genres,
        "label":        g("TPUB"),
        "composer":     g("TCOM"),
        "release_id":   "",
        "has_art":      bool(tags.getall("APIC")),
    }


def write_tags(path, meta, cover_bytes=None):
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

    tags.save(path)


# ── Filesystem ────────────────────────────────────────────────────────────────

SAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

def safe(name, maxlen=60):
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
    fname  = f"{track} - {title}.mp3" if track else f"{title}.mp3"
    return Path(root) / artist / folder / fname

def collect_mp3s(folder):
    result = []
    for dirpath, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".mp3"):
                result.append(os.path.join(dirpath, f))
    return sorted(result)


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
                for src_file in loser.rglob("*.mp3"):
                    dst_file = winner / src_file.relative_to(loser)
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

def process_file(path, dst, opts, stats, log_cb=None):
    def log(msg):
        if log_cb: log_cb(msg)

    meta   = read_tags(path)
    source = "tags"

    # 1. MusicBrainz
    if meta.get("artist") or meta.get("title"):
        mb = search_mb(meta.get("artist", ""), meta.get("title", ""), meta.get("album", ""))
        if mb:
            for k in ("title", "artist", "album", "year", "track", "disc",
                      "total_tracks", "disc_total", "label", "composer", "release_id"):
                if mb.get(k): meta[k] = mb[k]
            if not meta.get("genres") and mb.get("genres"):
                meta["genres"] = mb["genres"]
            source = "MusicBrainz"
            gstr = f" [{', '.join(meta['genres'][:2])}]" if meta.get("genres") else ""
            log(f"  \u2713 MusicBrainz: {meta.get('artist')} \u2014 {meta.get('title')}{gstr}")

    # 2. AcoustID fingerprint fallback
    if source == "tags" and opts.get("acoustid", True):
        if find_fpcalc():
            log("  \u27f3 AcoustID fingerprint\u2026")
            ac = acoustid_lookup(path)
            if ac:
                for k in ("title", "artist", "album", "year", "track", "disc",
                          "total_tracks", "disc_total", "release_id"):
                    if ac.get(k): meta[k] = ac[k]
                source = "AcoustID"
                log(f"  \u2713 AcoustID: {meta.get('artist')} \u2014 {meta.get('title')}")
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
            log("  \u26a0 AcoustID skipped \u2014 fpcalc not found")

    # 3. Last.fm genre fallback
    if not meta.get("genres") and meta.get("artist") and meta.get("title"):
        lfm = lastfm_genres(meta["artist"], meta["title"])
        if lfm:
            meta["genres"] = lfm
            log(f"  \u2713 Last.fm genres: {', '.join(lfm)}")

    if source == "tags":
        log("  \u2717 Could not identify \u2014 using existing tags")

    if not meta.get("title"):  meta["title"]  = Path(path).stem
    if not meta.get("artist"): meta["artist"] = "Unknown Artist"
    if not meta.get("album"):  meta["album"]  = "Unknown Album"

    # 4. Album art
    cover_bytes = None
    if opts.get("fetch_art", True) and meta.get("release_id"):
        if not meta.get("has_art") or opts.get("overwrite_art", False):
            log("  \U0001f5bc Fetching album art\u2026")
            cover_bytes = fetch_cover_art(meta["release_id"])
            if cover_bytes:
                log(f"  \u2713 Album art fetched ({len(cover_bytes)//1024} KB)")
            else:
                log("  \u26a0 Album art not found in Cover Art Archive")

    # 5. Write tags
    if opts.get("write_tags", True) and source != "tags":
        try:
            write_tags(path, meta, cover_bytes=cover_bytes)
        except Exception as e:
            log(f"  ! Tag write failed: {e}")

    # 6. Copy / move
    dest = destination(dst, meta)

    if opts.get("dry_run", False):
        stats["ok"] += 1
        log(f"  [DRY] \u2192 {dest}")
        return meta, source, "dry-run", str(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)

    if cover_bytes:
        saved = save_folder_cover(dest.parent, cover_bytes)
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
