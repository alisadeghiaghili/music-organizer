#!/usr/bin/env python3
"""music_organizer_web.py — Music Organizer GUI (pywebview / WebView2).

The primary GUI: the same `music_core` engine as the CLI, but the UI is a
webview page (HTML/CSS/JS) instead of Tk widgets. It supports light / dark /
system theming and a bundled app icon. Run it with:

    python -m music_organizer_web

It is shipped in the per-platform release builds as MusicOrganizer-GUI
(the Tkinter frontend in `music_organizer_gui.py` remains available as a
lightweight, dependency-free fallback).
"""

import base64
import io
import json
import os
import sys
import threading
from pathlib import Path

import webview

from music_core import (
    collect_audio_files,
    read_tags,
    process_file,
    merge_duplicate_albums,
    merge_duplicate_artists,
    fpcalc_status,
)
from fpcalc_installer import download_fpcalc
from music_organizer import __version__
from config import get_config


def _resource_dir() -> Path:
    """Directory holding bundled assets (icon) — works in PyInstaller --onefile
    (extracts to sys._MEIPASS) and in a plain source checkout."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _window_icon_path():
    """Path to the app icon for the OS titlebar (prefers the multi-size .ico)."""
    base = _resource_dir()
    for name in ("app.ico", "icon.png"):
        p = base / name
        if p.exists():
            return str(p)
    return None


def _icon_data_uri(size: int = 44):
    """Header icon as an inline data URI (so it renders regardless of cwd),
    or None if the asset is absent (header icon is then hidden)."""
    try:
        from PIL import Image
    except ImportError:
        return None
    p = _resource_dir() / "icon.png"
    if not p.exists():
        return None
    try:
        im = Image.open(p).convert("RGBA").resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


def _system_prefers_dark() -> bool:
    """Windows AppsUseLightTheme flag (1 = light). Falls back to light."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return int(val) == 0
    except Exception:
        return False


def _resolve_theme(choice: str) -> str:
    """Return the concrete theme ('light'/'dark') for a user choice."""
    if choice == "light":
        return "light"
    if choice == "dark":
        return "dark"
    return "dark" if _system_prefers_dark() else "light"


# ── tiny log-line tagger (mirrors the GUI's marker rules, loosely) ──────────
def _log_tag(msg):
    s = msg.strip()
    if "✗" in s or "error" in s.lower():
        return "err"
    if s.startswith(("!", "⚠")):
        return "warn"
    if any(p in s for p in ("✓", "✅", "→", "▶")):
        return "ok"
    if any(p in s for p in ("⟳", "🖼", "🎼", "Scanned")):
        return "info"
    if s.startswith(("~", "—", "↷", "←")):
        return "muted"
    return "text"


# ── backend API exposed to the webview page ──────────────────────────────────
class Api:
    def __init__(self):
        self._lock = threading.Lock()
        self._rows = []            # ordered list of row dicts
        self._row_index = {}       # path -> index into _rows
        self._log = []             # list of {id, t, tag}
        self._log_id = 0
        self._phase = "idle"       # idle|scanning|organizing|merging|done
        self._progress = 0.0
        self._status = ""
        self._stats = {"ok": 0, "skipped": 0, "errors": 0}
        self._audio_files = []
        self._pause = threading.Event()
        self._pause.set()
        self._stop = threading.Event()
        st, _ = fpcalc_status()
        self._fp = st              # ok | missing | downloading | failed
        cfg = get_config()
        self._theme = cfg.get("theme", "system")  # light | dark | system
        self._cfg = cfg

    # -- state helpers (call from worker threads; guarded by lock) --
    def _logmsg(self, m):
        m = str(m)
        with self._lock:
            self._log_id += 1
            self._log.append({"id": self._log_id, "t": m, "tag": _log_tag(m)})

    def _set(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, "_" + k, v)

    def _upsert_row(self, path, row):
        with self._lock:
            i = self._row_index.get(path)
            if i is None:
                i = len(self._rows)
                self._row_index[path] = i
                self._rows.append(row)
            else:
                self._rows[i] = row

    # -- initial snapshot (called on page ready) --
    def init(self):
        return self._state()

    def _state(self):
        with self._lock:
            return {
                "phase": self._phase,
                "progress": round(self._progress, 1),
                "status": self._status,
                "stats": dict(self._stats),
                "rows": [dict(r) for r in self._rows],
                "log": list(self._log[-800:]),
                "fpcalc": self._fp,
                "running": self._phase in ("scanning", "organizing", "merging"),
                "can_organize": bool(self._audio_files),
                "version": __version__,
                "theme": self._theme,                     # user choice
                "effective_theme": _resolve_theme(self._theme),  # light|dark
            }

    # -- called from JS on a timer --
    def get_state(self):
        return self._state()

    # -- theme --
    def icon(self):
        """Inline header icon (data URI), or None to hide the <img>."""
        return _icon_data_uri()

    def set_theme(self, choice):
        choice = (choice or "system").strip().lower()
        if choice not in ("light", "dark", "system"):
            choice = "system"
        with self._lock:
            self._theme = choice
        try:
            self._cfg.set("theme", choice)
            self._cfg.save()
        except Exception:
            pass
        return self._state()

    # -- folder picker --
    def pick_folder(self):
        for w in webview.windows:
            try:
                return w.create_file_dialog(webview.FOLDER_DIALOG)
            except Exception:
                return None
        return None

    # -- fpcalc --
    def install_fpcalc(self):
        if self._fp not in ("missing", "failed"):
            return

        def _run():
            self._fp = "downloading"
            self._logmsg("🎼 Installing audio fingerprinting…")

            def _done():
                st, _ = fpcalc_status()
                self._fp = st if st == "ok" else "ok"
                self._logmsg("✓ Audio fingerprinting ready")

            def _err(e):
                self._fp = "failed"
                self._logmsg(f"✗ Fingerprinting install failed: {e}")

            try:
                download_fpcalc(done_cb=_done, error_cb=_err)
            except Exception as e:
                _err(e)

        threading.Thread(target=_run, daemon=True).start()

    # -- scan --
    def scan(self, src):
        src = (src or "").strip()
        if not src or not os.path.isdir(src):
            self._logmsg("✗ Please choose a valid source folder")
            return

        def _run():
            self._set(phase="scanning", progress=0.0, status="Scanning…")
            self._logmsg(f"Scanning '{src}'…")
            files = collect_audio_files(src)
            self._audio_files = files
            total = max(len(files), 1)
            for i, p in enumerate(files):
                t = read_tags(p)
                row = {
                    "path": p,
                    "file": os.path.basename(p),
                    "artist": t.get("artist", ""),
                    "album": t.get("album", ""),
                    "year": t.get("year", ""),
                    "trk": t.get("track", ""),
                    "title": t.get("title", ""),
                    "genre": ", ".join(t.get("genres", [])[:2]),
                    "lyrics": "·", "art": "·",
                    "status": "ready",
                }
                self._upsert_row(p, row)
                self._set(progress=(i + 1) / total * 100)
            self._set(
                phase="idle",
                status=f"{len(files)} file(s) found",
            )
            self._logmsg(f"Scanned '{src}' — {len(files)} audio file(s) found")

        threading.Thread(target=_run, daemon=True).start()

    # -- organize --
    def organize(self, dst, opts, do_merge):
        dst = (dst or "").strip()
        if not dst:
            self._logmsg("✗ Please choose an output folder")
            return
        if not self._audio_files:
            self._logmsg("✗ Scan a folder first")
            return
        opts = dict(opts or {})
        for k in ("copy", "acoustid", "write_tags", "overwrite",
                  "dry_run", "fetch_art", "fetch_lyrics", "overwrite_art"):
            opts[k] = bool(opts.get(k, False))
        do_merge = bool(do_merge)

        def _run():
            self._stop.clear()
            self._pause.set()
            os.makedirs(dst, exist_ok=True)
            files = self._audio_files
            total = max(len(files), 1)
            done = 0
            stats = {"ok": 0, "skipped": 0, "errors": 0}
            self._set(phase="organizing", progress=0.0, stats=stats)
            self._logmsg(f"Organizing {len(files)} file(s)…")

            for path in files:
                self._pause.wait()
                if self._stop.is_set():
                    break
                try:
                    meta, source, status, dest = process_file(
                        path, dst, opts, stats, log_cb=self._logmsg)
                except Exception as e:
                    stats["errors"] += 1
                    status = "error"
                    meta = read_tags(path)
                    self._logmsg(f"✗ {os.path.basename(path)}: {e}")
                done += 1
                self._set(progress=done / total * 100, stats=stats)

                src_label = {"MusicBrainz": "Online", "AcoustID": "Online",
                             "tags": "Local tags"}.get(source, source or "")
                status_txt = (f"✓ {src_label}" if status == "ok" else
                              f"— {src_label}" if status == "dry-run" else
                              "↷ skipped" if status == "skipped" else "✗ error")
                row = {
                    "path": path,
                    "file": os.path.basename(path),
                    "artist": meta.get("artist", ""),
                    "album": meta.get("album", ""),
                    "year": meta.get("year", ""),
                    "trk": (meta.get("track", "").zfill(2) if meta.get("track") else ""),
                    "title": meta.get("title", ""),
                    "genre": ", ".join(meta.get("genres", [])[:2]),
                    "lyrics": "✓" if (meta.get("_lyrics_plain") or meta.get("_lyrics_synced")) else "·",
                    "art": "✓" if meta.get("_art_found") else "·",
                    "status": status_txt,
                }
                self._upsert_row(path, row)

            if do_merge and not opts.get("dry_run") and not self._stop.is_set():
                self._set(phase="merging", status="Merging duplicate folders…")
                self._logmsg("🔀 Merging duplicate folders…")
                merge_duplicate_artists(dst, log_cb=self._logmsg)
                merge_duplicate_albums(dst, log_cb=self._logmsg)

            self._set(
                phase="done", progress=100.0,
                status=f"Done — ✓ {stats['ok']}  ↷ {stats['skipped']}  ✗ {stats['errors']}",
            )
            self._logmsg(f"Done — ✓ {stats['ok']}  ↷ {stats['skipped']}  ✗ {stats['errors']}")

        threading.Thread(target=_run, daemon=True).start()

    # -- pause / resume / stop --
    def pause(self):
        self._pause.clear()
        self._set(status="Paused")
        self._logmsg("⏸ Paused")

    def resume(self):
        self._pause.set()
        self._logmsg("▶ Resumed")

    def stop(self):
        self._pause.set()
        self._stop.set()
        self._logmsg("Stopping…")


# ── webview page ──────────────────────────────────────────────────────────────
HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Music Organizer</title>
<style>
  :root{
    --bg:#e8e9ec; --surface:#fbfbfc; --surface2:#e0e2e7;
    --fg:#2b2f36; --muted:#6b717a; --accent:#4a6fb0; --accent-hover:#587cc2;
    --ok:#2f9e63; --warn:#c9862a; --err:#d15a50; --info:#3d84b0;
    --btn2:#dcdee3; --btn2-h:#cdd0d7; --trough:#d2d4da; --zebra:#f2f3f5;
    --log-bg:#1f232b; --log-fg:#c8cdd6;
    --pill-ok:#e5f4ec; --pill-warn:#f6ece0;
  }
  html[data-theme="dark"]{
    --bg:#1b1e24; --surface:#242830; --surface2:#333945;
    --fg:#e6e8ec; --muted:#9aa1ac; --accent:#5c82c8; --accent-hover:#6d92d6;
    --ok:#43b878; --warn:#d99a3d; --err:#e0685e; --info:#5aa0cf;
    --btn2:#333945; --btn2-h:#3d4451; --trough:#2c313b; --zebra:#20242c;
    --log-bg:#12151b; --log-fg:#c8cdd6;
    --pill-ok:#1e3a2c; --pill-warn:#3a2f1e;
  }
  *{box-sizing:border-box}
  html,body{height:100%;margin:0}
  body{
    font-family:"Segoe UI",system-ui,sans-serif; color:var(--fg);
    background:var(--bg); display:flex; flex-direction:column; overflow:hidden;
  }
  .bar{
    display:flex; align-items:center; gap:10px; padding:10px 18px;
    background:var(--surface); border-bottom:1px solid var(--surface2);
  }
  .bar .logo{width:26px; height:26px; border-radius:7px; flex:none}
  .bar .title{font-size:15px; font-weight:700; letter-spacing:.2px}
  .bar .ver{color:var(--muted); font-size:12px}
  .themeseg{display:flex; align-items:center; gap:2px; margin-left:auto;
    background:var(--bg); border:1px solid var(--surface2); border-radius:8px; padding:2px}
  .themeseg button{border:0; background:transparent; color:var(--muted); cursor:pointer;
    font-size:11px; font-weight:600; padding:3px 9px; border-radius:6px;
    display:flex; align-items:center; gap:5px}
  .themeseg button.active{background:var(--surface); color:var(--fg)}
  .themeseg button:hover:not(.active){color:var(--fg)}
  .themeseg svg{width:13px; height:13px}
  .pill{font-size:11px; padding:3px 9px; border-radius:999px;
        background:var(--surface2); color:var(--muted)}
  .pill.ok{background:var(--pill-ok); color:var(--ok)}
  .pill.missing{background:var(--pill-warn); color:var(--warn); cursor:pointer}
  .wrap{flex:1; min-height:0; display:flex; flex-direction:column; gap:10px;
        padding:14px 18px}
  .card{background:var(--surface); border:1px solid var(--surface2);
        border-radius:10px; padding:14px 16px}
  .card h3{margin:0 0 10px; font-size:12px; text-transform:none; color:var(--muted);
        font-weight:700; letter-spacing:.3px}
  .row{display:flex; align-items:center; gap:10px; margin:6px 0}
  .row label{width:78px; color:var(--muted); font-size:12px; flex:none}
  .row input[type=text]{flex:1; border:1px solid var(--surface2); border-radius:7px;
        padding:7px 10px; font-size:13px; background:var(--bg); color:var(--fg)}
  .btn{border:0; border-radius:7px; padding:8px 14px; font-size:13px; font-weight:600;
       cursor:pointer; background:var(--btn2); color:var(--fg); transition:background .12s}
  .btn:hover{background:var(--btn2-h)}
  .btn.primary{background:var(--accent); color:#fff}
  .btn.primary:hover{background:var(--accent-hover)}
  .btn:disabled{opacity:.45; cursor:not-allowed}
  .opts{display:grid; grid-template-columns:1fr 1fr; gap:10px}
  .opt-row{display:flex; align-items:center; justify-content:space-between; padding:5px 0}
  .opt-row span{font-size:13px}
  .switch{position:relative; width:38px; height:22px; flex:none}
  .switch input{opacity:0; width:0; height:0}
  .slider{position:absolute; inset:0; background:var(--surface2); border-radius:999px;
        transition:.15s; cursor:pointer}
  .slider:before{content:""; position:absolute; width:16px; height:16px; left:3px;
        top:3px; background:#fff; border-radius:50%; transition:.15s}
  .switch input:checked + .slider{background:var(--accent)}
  .switch input:checked + .slider:before{transform:translateX(16px)}
  .actions{display:flex; align-items:center; gap:10px}
  .actions .status{margin-left:auto; font-size:12px; color:var(--muted); font-weight:600;
        overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:40%}
  .prog{height:8px; background:var(--trough); border-radius:999px; overflow:hidden}
  .prog > i{display:block; height:100%; width:0; background:var(--accent);
        border-radius:999px; transition:width .2s}
  .tablebox{flex:1; min-height:120px; overflow:auto; border:1px solid var(--surface2);
        border-radius:10px; background:var(--surface)}
  table{border-collapse:collapse; width:100%; font-size:12px}
  thead th{position:sticky; top:0; background:var(--surface2); color:var(--muted);
        text-align:left; padding:8px 10px; font-weight:700; white-space:nowrap; z-index:1}
  tbody td{padding:7px 10px; border-top:1px solid var(--surface2); white-space:nowrap}
  tbody tr:nth-child(even){background:var(--zebra)}
  td.num{width:34px}
  .mark.ok{color:var(--ok); font-weight:700}
  .st-ok{color:var(--ok)} .st-skip{color:var(--muted)} .st-err{color:var(--err)}
  .st-dry{color:var(--accent)}
  .logbox{height:130px; overflow:auto; background:var(--log-bg); color:var(--log-fg);
        border-radius:10px; padding:10px 12px; font-family:Consolas,monospace;
        font-size:12px; line-height:1.5}
  .logbox .ok{color:#6fd39a} .logbox .err{color:#ff8f86} .logbox .warn{color:#f0c169}
  .logbox .info{color:#7fc4ea} .logbox .muted{color:#7a828f}
  .row input[type=text]{color-scheme:light}
  html[data-theme="dark"] .row input[type=text]{color-scheme:dark}
</style>
</head>
<body>
  <div class="bar">
    <img class="logo" id="logo" alt="" onerror="this.style.display='none'">
    <span class="title">Music Organizer</span>
    <span class="ver" id="ver"></span>
    <div class="themeseg" role="group" aria-label="Theme">
      <button data-theme="light" title="Light" onclick="pickTheme('light')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
        Light</button>
      <button data-theme="dark" title="Dark" onclick="pickTheme('dark')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
        Dark</button>
      <button data-theme="system" title="Match system" onclick="pickTheme('system')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>
        System</button>
    </div>
    <span class="pill" id="fp"></span>
  </div>

  <div class="wrap">
    <div class="card">
      <h3>Folders</h3>
      <div class="row">
        <label>Source</label>
        <input type="text" id="src" placeholder="Folder to organize">
        <button class="btn" onclick="pick('src')">Browse</button>
      </div>
      <div class="row">
        <label>Output</label>
        <input type="text" id="dst" placeholder="Where files go (blank = in-place)">
        <button class="btn" onclick="pick('dst')">Browse</button>
      </div>
    </div>

    <div class="opts">
      <div class="card">
        <h3>Processing</h3>
        <label class="opt-row"><span>Keep original files</span>
          <span class="switch"><input type="checkbox" id="t_copy" checked><span class="slider"></span></span></label>
        <label class="opt-row"><span>Deep metadata lookup</span>
          <span class="switch"><input type="checkbox" id="t_acoustid"><span class="slider"></span></span></label>
        <label class="opt-row"><span>Download album art</span>
          <span class="switch"><input type="checkbox" id="t_art" checked><span class="slider"></span></span></label>
        <label class="opt-row"><span>Fetch lyrics</span>
          <span class="switch"><input type="checkbox" id="t_lyrics" checked><span class="slider"></span></span></label>
      </div>
      <div class="card">
        <h3>Output</h3>
        <label class="opt-row"><span>Save enriched tags</span>
          <span class="switch"><input type="checkbox" id="t_tags" checked><span class="slider"></span></span></label>
        <label class="opt-row"><span>Replace existing art</span>
          <span class="switch"><input type="checkbox" id="t_art_repl"><span class="slider"></span></span></label>
        <label class="opt-row"><span>Overwrite duplicates</span>
          <span class="switch"><input type="checkbox" id="t_ovr"><span class="slider"></span></span></label>
        <label class="opt-row"><span>Preview only</span>
          <span class="switch"><input type="checkbox" id="t_dry"><span class="slider"></span></span></label>
        <label class="opt-row"><span>Merge duplicate folders</span>
          <span class="switch"><input type="checkbox" id="t_merge" checked><span class="slider"></span></span></label>
      </div>
    </div>

    <div class="card actions">
      <button class="btn primary" id="btnScan" onclick="doScan()">Scan</button>
      <button class="btn primary" id="btnOrg" onclick="doOrganize()" disabled>Organize!</button>
      <button class="btn" id="btnPause" onclick="doPause()" disabled>Pause</button>
      <button class="btn" id="btnStop" onclick="doStop()" disabled>Stop</button>
      <span class="status" id="status"></span>
    </div>

    <div class="prog"><i id="progress"></i></div>

    <div class="tablebox">
      <table>
        <thead><tr>
          <th>File</th><th>Artist</th><th>Album</th><th>Year</th>
          <th>Trk</th><th>Title</th><th>Genre</th>
          <th style="width:56px">Lyrics</th><th style="width:44px">Art</th><th>Status</th>
        </tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>

    <div class="logbox" id="log"></div>
  </div>

<script>
const $ = id => document.getElementById(id);
const api = (name, ...args) => window.pywebview.api[name](...args);
const tog = id => $(id).checked;
let lastLogId = -1;
let rowMap = new Map();   // path -> tr element
let curTheme = null;

function applyTheme(s){
  document.documentElement.setAttribute("data-theme", s.effective_theme);
  document.querySelectorAll(".themeseg button").forEach(b=>{
    b.classList.toggle("active", b.dataset.theme === s.theme);
  });
  curTheme = s.theme;
}
function pickTheme(t){
  if(t === curTheme) return;
  // optimistic local apply, then persist + reconcile from the returned state
  document.querySelectorAll(".themeseg button").forEach(b=>{
    b.classList.toggle("active", b.dataset.theme === t);
  });
  api("set_theme", t).then(applyTheme).catch(()=>{});
}

function stClass(s){
  if(!s) return "";
  if(s.startsWith("✓")) return "st-ok";
  if(s.startsWith("✗")) return "st-err";
  if(s.startsWith("↷")) return "st-skip";
  if(s.startsWith("—")) return "st-dry";
  return "";
}
function mark(cls){ return `<span class="mark ${cls}">${"·"}</span>`; }

function render(s){
  applyTheme(s);
  $("ver").textContent = "v" + s.version;
  // fpcalc pill
  const fp = $("fp");
  if(s.fpcalc === "ok"){ fp.textContent="fingerprinting ✓"; fp.className="pill ok"; fp.onclick=null; }
  else if(s.fpcalc === "downloading"){ fp.textContent="installing…"; fp.className="pill"; fp.onclick=null; }
  else if(s.fpcalc === "failed"){ fp.textContent="fingerprinting failed"; fp.className="pill missing"; fp.onclick=doInstall; }
  else { fp.textContent="enable fingerprinting"; fp.className="pill missing"; fp.onclick=doInstall; }

  // status + progress
  $("status").textContent = s.status || "";
  $("progress").style.width = (s.progress||0) + "%";
  $("progress").style.background = s.phase === "organizing" || s.phase==="merging"
      ? "var(--ok)" : "var(--accent)";

  // buttons
  $("btnScan").disabled = s.running;
  $("btnOrg").disabled = s.running || !s.can_organize;
  $("btnPause").disabled = !s.running;
  $("btnStop").disabled = !s.running;

  // table — reconcile by path
  const seen = new Set();
  s.rows.forEach(r=>{
    seen.add(r.path);
    let tr = rowMap.get(r.path);
    if(!tr){
      tr = document.createElement("tr");
      tr.innerHTML = "<td></td><td></td><td></td><td></td><td class='num'></td>"
                   + "<td></td><td></td><td></td><td></td><td></td>";
      rowMap.set(r.path, tr);
      $("tbody").appendChild(tr);
    }
    const c = tr.children;
    c[0].textContent = r.file;
    c[1].textContent = r.artist;
    c[2].textContent = r.album;
    c[3].textContent = r.year;
    c[4].textContent = r.trk;
    c[5].textContent = r.title;
    c[6].textContent = r.genre;
    c[7].innerHTML = r.lyrics==="✓" ? '<span class="mark ok">✓</span>' : '<span class="mark">·</span>';
    c[8].innerHTML = r.art==="✓"   ? '<span class="mark ok">✓</span>' : '<span class="mark">·</span>';
    c[9].textContent = r.status;
    c[9].className = stClass(r.status);
  });
  // drop rows no longer present (e.g. after re-scan)
  for(const [p,tr] of [...rowMap]){
    if(!seen.has(p)){ tr.remove(); rowMap.delete(p); }
  }

  // log — append only new lines, autoscroll
  const log = $("log");
  s.log.forEach(l=>{
    if(l.id > lastLogId){
      const d = document.createElement("div");
      d.className = l.tag;
      d.textContent = l.t;
      log.appendChild(d);
    }
  });
  lastLogId = s.log.length ? s.log[s.log.length-1].id : lastLogId;
  log.scrollTop = log.scrollHeight;
}

function poll(){
  api("get_state").then(render).catch(()=>{});
}

function doScan(){ api("scan", $("src").value); }
function doOrganize(){
  const opts = {
    copy: tog("t_copy"), acoustid: tog("t_acoustid"), write_tags: tog("t_tags"),
    overwrite: tog("t_ovr"), dry_run: tog("t_dry"), fetch_art: tog("t_art"),
    fetch_lyrics: tog("t_lyrics"), overwrite_art: tog("t_art_repl"),
  };
  api("organize", $("dst").value, opts, tog("t_merge"));
}
function doPause(){ const b=$("btnPause");
  if(b.textContent==="Pause"){ api("pause"); b.textContent="Resume"; }
  else { api("resume"); b.textContent="Pause"; } }
function doStop(){ api("stop"); }
function doInstall(){ api("install_fpcalc"); }
async function pick(which){ const p = await api("pick_folder"); if(p) $(which).value = p; }

window.addEventListener("pywebviewready", ()=>{
  // header icon (hides itself via onerror if unavailable)
  api("icon").then(u => { if(u) $("logo").src = u; }).catch(()=>{});
  api("init").then(render).catch(()=>{});
  setInterval(poll, 400);
});
</script>
</body>
</html>
"""


def main():
    api = Api()
    # Match the window background to the resolved theme so there's no white/dark
    # flash before the webview page paints.
    bg = "#1b1e24" if _resolve_theme(api._theme) == "dark" else "#e8e9ec"
    webview.create_window(
        "Music Organizer",
        js_api=api,
        html=HTML,
        width=1120,
        height=780,
        min_size=(820, 600),
        background_color=bg,
    )
    # Titlebar icon: start() sets _state['icon'], which the WinForms backend
    # applies to Form.Icon before the window is shown (create_window itself has
    # no icon= kwarg in 6.x). debug=True opens devtools while evaluating.
    webview.start(debug=False, icon=_window_icon_path())


if __name__ == "__main__":
    main()
