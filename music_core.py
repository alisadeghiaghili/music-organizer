#!/usr/bin/env python3
"""music_core.py — shared logic for Music Organizer (GUI + CLI)"""

import os, re, sys, time, shutil, json, subprocess, urllib.request, urllib.parse
from pathlib import Path
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, TPE2, ID3NoHeaderError

MB_BASE  = "https://musicbrainz.org/ws/2"
HEADERS  = {"User-Agent": "MusicOrganizer/1.0 (github.com/alisadeghiaghili/music-organizer)"}
_last_mb = 0.0


def mb_get(endpoint, params):
    global _last_mb
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


def search_mb(artist, title, album=""):
    parts = []
    if title:  parts.append(f'recording:"{title}"')
    if artist: parts.append(f'artistname:"{artist}"')
    if album:  parts.append(f'release:"{album}"')
    if not parts:
        return None
    data = mb_get("recording", {"query": " AND ".join(parts), "limit": 5})
    if not data or not data.get("recordings"):
        return None
    rec = data["recordings"][0]
    result = {
        "title":  rec.get("title", ""),
        "artist": (rec["artist-credit"][0]["artist"]["name"]
                   if rec.get("artist-credit") else artist),
        "album": "", "year": "", "track": "", "disc": "",
    }
    releases = rec.get("releases", [])
    if releases:
        rel, year = _best_release(releases)
        result["album"] = rel.get("title", album)
        result["year"]  = str(year) if year != 9999 else ""
        media = rel.get("media", [])
        if media:
            t = media[0].get("track", [{}])[0] if media[0].get("track") else {}
            result["track"] = str(t.get("number", ""))
            result["disc"]  = str(media[0].get("position", "")) if len(media) > 1 else ""
    return result


def find_fpcalc():
    fname = "fpcalc.exe" if os.name == "nt" else "fpcalc"

    # 1. Embedded inside PyInstaller onefile exe (_MEIPASS = temp extraction dir)
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
        "&meta=recordings+releases+tracks+releasegroups"
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
    album, year, track = "", "", ""
    if rec.get("releases"):
        rel, yr = _best_release(rec["releases"])
        album = rel.get("title", "")
        year  = str(yr) if yr != 9999 else ""
        mediums = rel.get("mediums", [])
        if mediums and mediums[0].get("tracks"):
            track = str(mediums[0]["tracks"][0].get("position", ""))
    return {"title": title, "artist": artist, "album": album,
            "year": year, "track": track, "disc": ""}


def read_tags(path):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return {}
    def g(k):
        v = tags.get(k)
        return str(v.text[0]).strip() if v and v.text else ""
    return {
        "title":  g("TIT2"),
        "artist": g("TPE1") or g("TPE2"),
        "album":  g("TALB"),
        "year":   g("TDRC")[:4] if g("TDRC") else "",
        "track":  g("TRCK").split("/")[0] if g("TRCK") else "",
        "disc":   "",
    }


def write_tags(path, meta):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    def s(k, cls, v):
        if v:
            tags.delall(k)
            tags.add(cls(encoding=3, text=[v]))
    s("TIT2", TIT2, meta.get("title"))
    s("TPE1", TPE1, meta.get("artist"))
    s("TALB", TALB, meta.get("album"))
    s("TDRC", TDRC, meta.get("year"))
    s("TRCK", TRCK, meta.get("track"))
    tags.save(path)


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
            key = normalize_album_key(album_dir.name)
            groups.setdefault(key, []).append(album_dir)
        for key, dirs in groups.items():
            if len(dirs) < 2: continue
            def sort_key(d):
                m = re.match(r'^(\d{4})', d.name)
                return (-folder_score(d.name), int(m.group(1)) if m else 9999)
            dirs_sorted = sorted(dirs, key=sort_key)
            winner, losers = dirs_sorted[0], dirs_sorted[1:]
            log(f"  🔀 Merging into: {artist_dir.name}/{winner.name}")
            for loser in losers:
                log(f"      ← absorbing: {loser.name}")
                for src_file in loser.rglob("*.mp3"):
                    dst_file = winner / src_file.relative_to(loser)
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    if not dst_file.exists():
                        shutil.move(str(src_file), str(dst_file))
                    else:
                        log(f"      ! skipped (exists): {dst_file.name}")
                try:
                    shutil.rmtree(str(loser))
                    merged_count += 1
                except Exception as e:
                    log(f"      ! could not remove {loser.name}: {e}")
    log(f"  ✅ Merged {merged_count} duplicate album folder(s)" if merged_count
        else "  ✅ No duplicate album folders found")
    return merged_count


def process_file(path, dst, opts, stats, log_cb=None):
    def log(msg):
        if log_cb: log_cb(msg)
    meta   = read_tags(path)
    source = "tags"
    if meta.get("artist") or meta.get("title"):
        mb = search_mb(meta.get("artist", ""), meta.get("title", ""), meta.get("album", ""))
        if mb:
            for k in ("title", "artist", "album", "year", "track", "disc"):
                if mb.get(k): meta[k] = mb[k]
            source = "MusicBrainz"
            log(f"  ✓ MusicBrainz: {meta.get('artist')} — {meta.get('title')}")
    if source == "tags" and opts.get("acoustid", True):
        if find_fpcalc():
            log("  ⟳ Fingerprinting…")
            ac = acoustid_lookup(path)
            if ac:
                for k in ("title", "artist", "album", "year", "track", "disc"):
                    if ac.get(k): meta[k] = ac[k]
                source = "AcoustID"
                log(f"  ✓ Fingerprint: {meta.get('artist')} — {meta.get('title')}")
        else:
            log("  ⚠ Fingerprinting skipped — fpcalc not found")
    if source == "tags":
        log("  ✗ Could not identify — using existing tags")
    if not meta.get("title"):  meta["title"]  = Path(path).stem
    if not meta.get("artist"): meta["artist"] = "Unknown Artist"
    if not meta.get("album"):  meta["album"]  = "Unknown Album"
    if opts.get("write_tags", True) and source != "tags":
        try: write_tags(path, meta)
        except Exception as e: log(f"  ! Tag write failed: {e}")
    dest = destination(dst, meta)
    if opts.get("dry_run", False):
        stats["ok"] += 1
        log(f"  [DRY] → {dest}")
        return meta, source, "dry-run", str(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    status = "ok"
    if dest.exists() and not opts.get("overwrite", False):
        status = "skipped"; stats["skipped"] += 1
        log(f"  ↷ Skipped (exists): {dest.name}")
    else:
        try:
            (shutil.copy2 if opts.get("copy", True) else shutil.move)(path, dest)
            stats["ok"] += 1
            log(f"  → {dest}")
        except Exception as e:
            status = "error"; stats["errors"] += 1
            log(f"  ✗ Error: {e}")
    return meta, source, status, str(dest)
