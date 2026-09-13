#!/usr/bin/env python3
"""music_organizer_gui.py — GUI frontend"""

import os, sys, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from music_core import collect_audio_files, read_tags, process_file, merge_duplicate_albums, fpcalc_status
from fpcalc_installer import download_fpcalc
from config import get_config

# Columns of the results table, in display order. Kept in one place so the
# header build, the scan/organize row builders, and the header sort all agree.
RESULT_COLUMNS = (
    ("file",    "File",               150, "w"),
    ("artist",  "Artist",             140, "w"),
    ("album",   "Album",              170, "w"),
    ("year",    "Year",                50, "w"),
    ("trk",     "Trk",                 40, "w"),
    ("title",   "Title",              190, "w"),
    ("genre",   "Genre",              130, "w"),
    ("lyrics",  "Lyrics",              58, "center"),
    ("art",     "Art",                 50, "center"),
    ("status",  "Status",              92, "w"),
)
# Columns whose numeric prefix should sort numerically rather than lexicographically.
_NUMERIC_COLS = {"year", "trk"}
# Base heading labels, for clearing/restoring the sort arrow markers.
_RESULT_LABELS = {c[0]: c[1] for c in RESULT_COLUMNS}

# Idle, stage-side one-liners shown in the empty table. They rotate while there
# are no rows, giving the otherwise quiet panel a little character.
_GIG_LINES = (
    "House lights up — the setlist is empty.",
    "Sound check passed. Point us at a folder to load the show.",
    "Stage's ready. Scan a folder to line up the first track.",
    "All quiet in the pit. Add some tracks and cue the lights.",
    "Doors open, crowd's waiting — pick a folder and hit Scan.",
    "Amps warm, mic set, no songs yet. Let's build the setlist.",
    "Backstage and ready — a folder away from first song.",
)
_GIG_INTERVAL_MS = 4200


def next_sort_state(clicked_col, active_col, active_state):
    """Three-state header sort cycle.

    Re-clicking the active column cycles asc -> desc -> default (None);
    clicking a different column always starts it ascending.
    """
    if clicked_col == active_col:
        if active_state == "asc":
            return "desc"
        if active_state == "desc":
            return None  # back to default order
        return "asc"  # was at default; start the cycle
    return "asc"


def sort_key(cid, raw):
    """Sort key for a column cell.

    Numeric-aware: for track/year cells it orders by the leading integer (so
    "9" sorts before "10"), falling back to a stable text key. Empty/blank
    values sort last. Everything else sorts by lower-cased text.
    """
    text = str(raw if raw is not None else "").strip()
    if cid in _NUMERIC_COLS:
        for tok in text.split("/"):
            if tok.isdigit():
                return (0, int(tok), text)
        return (2, 0, text) if not text else (1, 0, text)
    return (2, 0, text) if not text else (0, 0, text.casefold())


# ── design system ──────────────────────────────────────────────────────────
# A single calm dark surface with one confident accent (blue) and a small set
# of vivid status colours. The same status colours are reused across the log,
# the table, and the header so the whole window reads as one system.
D_BG       = "#14161c"   # window background
D_SURFACE  = "#1d2029"   # cards, table rows
D_SURF2    = "#262a35"   # raised: headings, inputs, secondary buttons
D_FG       = "#e8ebf2"   # primary text
D_MUTED    = "#8b93a5"   # secondary text / field labels
D_ACCENT   = "#5b8cff"   # primary action
D_ACCENT_H = "#7aa2ff"   # primary hover
D_OK       = "#35d39b"   # success
D_WARN     = "#f4b64a"   # warning
D_ERR      = "#f4736b"   # error
D_INFO     = "#56c5ea"   # info
D_FONT     = "Segoe UI"
D_MONO     = "Consolas"

# Colour tag for a log line, decided by its leading marker. Kept as a pure,
# ordered list so it can be unit-tested without a display. First match wins;
# the most specific markers come first. Lines with no known marker use "text".
_LOG_RULES = (
    ("\U0001f5bc cover.jpg",   "ok"),     # embedded cover art → dest
    ("✓",                 "ok"),     # identified / art fetched / genres / merged
    ("\U0001f4dd Lyrics found", "ok"),
    ("✅",                "ok"),
    ("▶",                 "ok"),     # resumed
    ("\U0001f5bc Fetching",   "info"),   # fetching album art…
    ("⟳",                 "info"),   # fingerprinting audio…
    ("🔀",                "info"),   # merging duplicate albums
    ("Scanned",           "info"),
    ("[DRY]",             "acc"),    # dry-run destination
    ("→",                 "acc"),    # a file was (would be) written
    ("\U0001f3bc",         "info"),
    ("⚠",                 "warn"),   # anything flagged
    ("⏸",                 "warn"),   # paused
    ("Stopping",          "warn"),
    ("✗",                 "err"),    # could not identify / error
    ("! could not",       "err"),
    ("! skipped (exists)","muted"),
    ("~ Keeping",         "muted"),  # kept an existing tag value
    ("— No lyrics",       "muted"),
    ("↷ Skipped",         "muted"),
    ("← absorbing",       "muted"),
    ("!",                 "warn"),   # tag/journal write failures, conflicts
)


def _log_tag(m):
    """Colour tag for a log line (pure; tested without a display)."""
    s = m.strip()
    for prefix, tag in _LOG_RULES:
        if s.startswith(prefix):
            return tag
    return "text"


# ── palette ───────────────────────────────────────────────────────────────
# A single cool, neutral gray "slate" palette (a calm middle gray with a faint
# cool cast — no warm/cream tint). The app is single-theme on purpose: every
# widget is built once with these colours and never recoloured at runtime, which
# sidesteps the Tk background-repaint flicker that theme-switching caused.
PALETTE = {
    "bg": "#e8e9ec", "surface": "#fbfbfc", "surface2": "#e0e2e7",
    "fg": "#2b2f36", "muted": "#6b717a", "accent": "#4a6fb0",
    "accent_hover": "#587cc2", "accent_text": "#ffffff",
    "ok": "#2f9e63", "warn": "#c9862a", "err": "#d15a50", "info": "#3d84b0",
    "btn_secondary": "#dcdee3", "btn_secondary_hover": "#cdd0d7",
    "btn_secondary_press": "#bfc3cb", "btn_danger": "#f5dedb",
    "btn_danger_hover": "#eeccc7", "disabled_fill": "#e8e9ec",
    "trough": "#d2d4da", "sel": "#dbe2f0", "zebra": "#f2f3f5",
    "toggle_off": "#c2c5cc", "dot_off": "#888e98",
    "banner_bg": "#eef1f8", "banner_fg": "#3d4a63",
    "banner_sub": "#6a748a", "banner_bar": "#8494b8",
}


# ── custom-drawn widgets ──────────────────────────────────────────────────
# Tk's stock buttons/checkboxes/progressbars look dated no matter the colour.
# These are drawn by hand on a Canvas so the chrome reads as one modern,
# flat, rounded system. They wrap the same BooleanVars the logic already uses,
# so no worker code changes.

def _rr(cv, x1, y1, x2, y2, r, **kw):
    """Draw a rounded-rectangle polygon and return its item id."""
    r = max(1, min(int(r), int((x2 - x1) / 2), int((y2 - y1) / 2)))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class CButton(tk.Frame):
    """A rounded button (canvas-drawn) with hover / press / disabled states.

    Variants: "primary" (accent CTA), "secondary" (quiet), "danger" (stop).
    Colours are theme-aware — pass a concrete palette via the ``theme`` dict.
    """

    def __init__(self, master, text, command, variant="secondary",
                 theme=None, bg=None, width=None, **kw):
        super().__init__(master, highlightthickness=0, **kw)
        t = theme or PALETTE
        bg = bg or t["bg"]
        self.configure(bg=bg)
        self._command, self._t = command, t
        if variant == "primary":
            self._c = (t["accent"], t["accent_hover"], t["accent_hover"], t["accent_text"])
        elif variant == "danger":
            self._c = (t["btn_danger"], t["btn_danger_hover"], t["btn_danger_hover"], t["err"])
        else:
            self._c = (t["btn_secondary"], t["btn_secondary_hover"],
                       t["btn_secondary_press"], t["fg"])
        self._bh = 40
        self._bw = int(width or (len(text) * 8 + 36))
        self._enabled, self._hover, self._press = True, False, False
        cv = tk.Canvas(self, width=self._bw, height=self._bh, bg=bg,
                       highlightthickness=0, bd=0)
        cv.pack()
        self._cv = cv
        self._shape = _rr(cv, 1, 1, self._bw - 1, self._bh - 1, 10,
                          fill=self._c[0], outline="")
        self._txt = cv.create_text(self._bw // 2, self._bh // 2, text=text,
                                   fill=self._c[3], font=(D_FONT, 10, "bold"))
        cv.bind("<Enter>", self._enter)
        cv.bind("<Leave>", self._leave)
        cv.bind("<Button-1>", self._down)
        cv.bind("<ButtonRelease-1>", self._up)
        cv.bind("<Motion>", self._reconcile)

    def _fill(self):
        if not self._enabled:
            return self._t["disabled_fill"]
        if self._press:
            return self._c[2]
        if self._hover:
            return self._c[1]
        return self._c[0]

    def _paint(self):
        self._cv.itemconfig(self._shape, fill=self._fill())
        self._cv.itemconfig(self._txt,
                            fill=self._c[3] if self._enabled else self._t["muted"])

    def _enter(self, _e):
        self._hover = True
        self._cv.config(cursor="hand2" if self._enabled else "arrow")
        self._paint()

    def _leave(self, _e):
        self._hover, self._press = False, False
        self._cv.config(cursor="arrow")
        self._paint()

    def _reconcile(self):
        """Reset hover/press from the real pointer position.

        Tk can drop the <Leave> event when a modal dialog (e.g. the folder
        picker) opens while the pointer is over the button, leaving the highlight
        stuck. Re-deriving the state from where the pointer actually is fixes
        that on the next motion or focus change.
        """
        try:
            px, py = self._cv.winfo_pointerxy()
            wx, wy = self._cv.winfo_rootx(), self._cv.winfo_rooty()
            ww, wh = self._cv.winfo_width(), self._cv.winfo_height()
        except tk.TclError:
            return
        inside = wx <= px < wx + ww and wy <= py < wy + wh
        new = bool(inside and self._enabled)
        self._press = False
        if new == self._hover:
            return  # unchanged → don't repaint
        self._hover = new
        self._cv.config(cursor="hand2" if self._hover else "arrow")
        self._paint()

    def _down(self, _e):
        if self._enabled:
            self._press = True
            self._paint()

    def _up(self, _e):
        if self._enabled and self._press:
            self._press = False
            self._paint()
            if self._command:
                self._command()

    def set_enabled(self, en):
        self._enabled = bool(en)
        self._press = False
        self._paint()

    def set_text(self, t):
        self._cv.itemconfig(self._txt, text=t)


class Toggle(tk.Canvas):
    """A modern pill-shaped toggle switch bound to a BooleanVar."""

    def __init__(self, master, variable, theme=None, **kw):
        super().__init__(master, width=44, height=24, bg=(theme or PALETTE)["surface"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self._var, self._t = variable, theme or PALETTE
        self._tw, self._th = 44, 24
        self._pill = _rr(self, 1, 3, self._tw - 1, self._th - 3, 9,
                         fill=self._t["toggle_off"], outline="")
        self._dot = self.create_oval(9, 8, 17, 16, fill=self._t["dot_off"], outline="")
        self.bind("<Button-1>", self._click)
        self._render()

    def _click(self, _e):
        self._var.set(not self._var.get())
        self._render()

    def _render(self):
        on = bool(self._var.get())
        self.itemconfig(self._pill, fill=self._t["accent"] if on else self._t["toggle_off"])
        self.coords(self._dot, (self._tw - 17) if on else 9, 8,
                    (self._tw - 9) if on else 17, 16)
        self.itemconfig(self._dot, fill="#ffffff" if on else self._t["dot_off"])

    def refresh(self):
        self._render()


class CProgress(tk.Canvas):
    """A rounded progress bar (canvas-drawn), determinate or indeterminate."""

    def __init__(self, master, color=None, bg=None, height=8, width=220,
                 theme=None, **kw):
        t = theme or PALETTE
        self._bg = bg or t["bg"]
        super().__init__(master, height=height, width=width, bg=self._bg,
                         highlightthickness=0, bd=0)
        self._color, self._h, self._trough = color or t["accent"], height, t["trough"]
        self._val, self._anim = 0.0, 0.0
        self._indet = False
        self.bind("<Configure>", lambda _e: self._draw())
        self._draw()

    def set_value(self, cur, mx):
        self._indet = False
        self._val = 0.0 if mx <= 0 else max(0.0, min(1.0, cur / mx))
        self._draw()

    def start(self):
        self._indet, self._anim = True, 0.0
        self._tick()

    def stop(self):
        self._indet = False

    def _tick(self):
        if not self._indet:
            return
        self._anim = (self._anim + 0.05) % 1.0
        self._draw()
        self.after(45, self._tick)

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 6:
            return
        r = max(2, self._h // 2)
        _rr(self, 0, 0, w, self._h, r, fill=self._trough, outline="")
        if self._indet:
            seg = max(50, int(w * 0.35))
            x0 = int(self._anim * (w + seg)) - seg
            x0c, x1c = max(0, x0), max(0, min(x0 + seg, w))
            if x1c - x0c > 6:
                _rr(self, x0c, 0, x1c, self._h, r, fill=self._color, outline="")
        else:
            fw = int(w * self._val)
            if fw >= self._h:
                _rr(self, 0, 0, fw, self._h, r, fill=self._color, outline="")
            elif fw > 0:
                self.create_oval(0, 0, fw, self._h, fill=self._color, outline="")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("\U0001f3b8 Music Organizer")
        self.geometry("1200x800")
        self.minsize(960, 640)
        self.resizable(True, True)
        self._stop_flag   = threading.Event()
        self._pause_event = threading.Event()  # set=running, clear=paused
        self._pause_event.set()
        self._audio_files = []
        self._fp_banner = None
        self._fp_missing = False
        self._t = PALETTE
        self.configure(bg=self._t["bg"])
        self._build_ui()
        self._sync_empty()          # table is empty at launch → show the idle line
        self.after(300, self._check_fpcalc)

    # ── fpcalc banner ─────────────────────────────────────────────────────────

    def _check_fpcalc(self):
        status, path = fpcalc_status()
        self._fp_missing = (status == "missing")
        if status == "missing":
            self._show_fp_banner()
        else:
            self._fp_lbl.config(text="● Audio fingerprinting ready", fg=self._t["ok"])

    def _show_fp_banner(self):
        if self._fp_banner:
            return
        t = self._t
        bg, fg = t["banner_bg"], t["banner_fg"]
        banner = tk.Frame(self, bg=bg, pady=8)
        banner.pack(fill="x", padx=20, pady=(0, 4))
        self._fp_banner = banner

        tk.Label(banner,
                 text="⚠ Audio fingerprinting unavailable — metadata lookup may be less accurate.",
                 bg=bg, fg=fg, font=(D_FONT, 9, "bold")
                 ).pack(side="left", padx=(10, 6))

        self._fp_prog_frame = tk.Frame(banner, bg=bg)
        self._fp_prog_frame.pack(side="left", padx=6)
        self._fp_prog_lbl = tk.Label(self._fp_prog_frame, text="",
                                     bg=bg, fg=t["banner_sub"], font=(D_FONT, 9))
        self._fp_prog_lbl.pack(side="top")
        self._fp_prog = CProgress(self._fp_prog_frame, color=t["banner_bar"],
                                  bg=bg, height=6, width=180, theme=t)

        def start_download():
            self._fp_dl_btn.set_enabled(False)
            self._fp_dl_btn.set_text("↓ Downloading…")
            self._fp_prog.pack(side="top", pady=2)
            self._fp_prog_lbl.pack(side="top")
            download_fpcalc(
                progress_cb=self._on_fp_progress,
                done_cb=self._on_fp_done,
                error_cb=self._on_fp_error,
            )

        self._fp_dl_btn = CButton(banner, "↓ Enable fingerprinting", start_download,
                                  variant="secondary", theme=t, bg=bg)
        self._fp_dl_btn.pack(side="left", padx=6)

        def dismiss():
            banner.destroy()
            self._fp_banner = None
            self._fp_prog = None
            self._fp_dl_btn = None
        tk.Button(banner, text="✕", bg=bg, fg=fg,
                  font=(D_FONT, 10), relief="flat", bd=0, cursor="hand2",
                  command=dismiss).pack(side="right", padx=10)

    def _on_fp_progress(self, downloaded, total):
        def _update():
            if total > 0:
                self._fp_prog.set_value(downloaded, total)
                self._fp_prog_lbl.config(
                    text=f"{downloaded//1024:,} / {total//1024:,} KB")
            else:
                self._fp_prog.start()
        self.after(0, _update)

    def _on_fp_done(self, path):
        def _update():
            if self._fp_banner:
                self._fp_banner.destroy()
                self._fp_banner = None
            self._fp_lbl.config(text="● Audio fingerprinting ready", fg=self._t["ok"])
            self._acoustid.set(True)
            self._toggles["acoustid"].refresh()
            messagebox.showinfo("Ready",
                                "Audio fingerprinting has been enabled.\n"
                                "Metadata accuracy is now improved.")
        self.after(0, _update)

    def _on_fp_error(self, exc):
        def _update():
            self._fp_dl_btn.set_enabled(True)
            self._fp_dl_btn.set_text("↓ Enable fingerprinting")
            messagebox.showerror("Download failed",
                                 f"Could not enable fingerprinting:\n{exc}")
        self.after(0, _update)

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        t = self._t
        F, MONO = D_FONT, D_MONO

        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=t["bg"], foreground=t["fg"], font=(F, 10))
        s.configure("Treeview", background=t["surface"], foreground=t["fg"],
                    fieldbackground=t["surface"], rowheight=28, font=(F, 9))
        s.configure("Treeview.Heading", background=t["surface2"], foreground=t["muted"],
                    font=(F, 9, "bold"), borderwidth=0)
        s.map("Treeview.Heading", foreground=[("active", t["fg"])])
        s.map("Treeview", background=[("selected", t["sel"])])

        # Slim, arrow-less scrollbars (the default ttk/clam bar has chunky
        # arrow buttons and a thick 3-D look that clashes with the flat design).
        for orient in ("Vertical", "Horizontal"):
            s.layout(f"Slim.{orient}.TScrollbar",
                     [(f"{orient}.Scrollbar.trough", {"sticky": "ns" if orient == "Vertical" else "ew",
                      "children": [(f"{orient}.Scrollbar.thumb",
                                    {"expand": "1", "sticky": "nswe"})]})])
            s.configure(f"Slim.{orient}.TScrollbar", background=t["trough"],
                        borderwidth=0, relief="flat", troughcolor=t["bg"],
                        arrowsize=0)
            s.map(f"Slim.{orient}.TScrollbar",
                  background=[("active", t["surface2"]), ("pressed", t["muted"])])

        # toggles — the same BooleanVars the workers already read.
        self._copy_mode    = tk.BooleanVar(value=True)
        self._acoustid     = tk.BooleanVar(value=True)
        self._wtags        = tk.BooleanVar(value=True)
        self._fetch_art    = tk.BooleanVar(value=True)
        self._fetch_lyrics = tk.BooleanVar(value=True)
        self._overwrite_art = tk.BooleanVar(value=False)
        self._overwrite    = tk.BooleanVar(value=False)
        self._dry_run      = tk.BooleanVar(value=False)
        self._do_merge     = tk.BooleanVar(value=True)

        # ── signature accent bar + header ─────────────────────────────────
        tk.Frame(self, bg=t["accent"], height=3).pack(fill="x")
        self._hdr = tk.Frame(self, bg=t["bg"])
        self._hdr.pack(fill="x", padx=24, pady=(18, 6))
        self._title_lbl = tk.Label(self._hdr, text="🎸 Music Organizer",
                                   bg=t["bg"], fg=t["fg"], font=(F, 17, "bold"))
        self._title_lbl.pack(side="left")
        self._fp_lbl = tk.Label(self._hdr, text="● Checking fingerprinting…",
                                bg=t["bg"], fg=t["warn"], font=(F, 9, "bold"))
        self._fp_lbl.pack(side="right")

        # ── folders card ──────────────────────────────────────────────────
        fcard = tk.Frame(self, bg=t["surface"], padx=18, pady=14,
                         highlightthickness=1, highlightbackground=t["surface2"])
        fcard.pack(fill="x", padx=24, pady=(4, 8))
        self._src_var = tk.StringVar()
        self._dst_var = tk.StringVar()
        for i, (lbl, var, cb) in enumerate([
            ("Source folder", self._src_var, self._pick_src),
            ("Output folder", self._dst_var, self._pick_dst),
        ]):
            l = tk.Label(fcard, text=lbl, bg=t["surface"], fg=t["muted"], font=(F, 9, "bold"))
            l.grid(row=i, column=0, sticky="w", padx=(0, 14), pady=5)
            e = tk.Entry(fcard, textvariable=var, bg=t["surface2"], fg=t["fg"],
                         insertbackground=t["fg"], relief="flat", font=(F, 10),
                         highlightthickness=1, highlightbackground=t["surface2"],
                         highlightcolor=t["accent"], disabledbackground=t["surface2"])
            e.grid(row=i, column=1, sticky="ew", pady=5, ipady=4)
        fcard.columnconfigure(1, weight=1)

        # ── option cards (toggles, not checkboxes) ─────────────────────────
        self._toggles = {}
        opt = tk.Frame(self, bg=t["bg"])
        opt.pack(fill="x", padx=24, pady=(0, 8))

        def _card(col, title, tint, items):
            card = tk.Frame(opt, bg=t["surface"], padx=18, pady=14,
                            highlightthickness=1, highlightbackground=t["surface2"])
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 12, 0))
            tk.Label(card, text=title, bg=t["surface"], fg=tint, font=(F, 11, "bold")
                     ).pack(anchor="w")
            tk.Frame(card, bg=t["surface2"], height=1).pack(fill="x", pady=(6, 10))
            for key, var, txt, tip in items:
                row = tk.Frame(card, bg=t["surface"])
                row.pack(fill="x", pady=3)
                tk.Label(row, text=txt, bg=t["surface"], fg=t["fg"],
                         font=(F, 10), anchor="w").pack(side="left")
                tog = Toggle(row, variable=var, theme=t)
                tog.pack(side="right", padx=(6, 0))
                self._toggles[key] = tog
                self._add_tooltip(row, tip)

        _card(0, "Processing", t["accent"], [
            ("copy",    self._copy_mode,    "Keep original files",
             "Copy files to output and leave sources untouched; off moves them"),
            ("acoustid", self._acoustid,    "Deep metadata lookup",
             "Use AcoustID audio fingerprinting for untagged files"),
            ("art",     self._fetch_art,    "Download album art",
             "Fetch and embed cover art from MusicBrainz"),
            ("lyrics",  self._fetch_lyrics, "Fetch lyrics",
             "Download synced lyrics from LRCLIB (free)"),
        ])
        _card(1, "Output", t["info"], [
            ("tags",   self._wtags,        "Save enriched tags",
             "Write enriched metadata back into each file"),
            ("art_repl", self._overwrite_art, "Replace existing art",
             "Replace already-embedded album art"),
            ("ovr",    self._overwrite,    "Overwrite duplicates",
             "Overwrite files that already exist in output"),
            ("dry",    self._dry_run,      "Preview only",
             "Show what would happen without touching any files"),
            ("merge",  self._do_merge,     "Merge duplicate albums",
             "Consolidate split album folders after organizing"),
        ])
        opt.columnconfigure(0, weight=1, uniform="cards")
        opt.columnconfigure(1, weight=1, uniform="cards")
        opt.rowconfigure(0, weight=1)

        # ── actions + status ───────────────────────────────────────────────
        self._bar = tk.Frame(self, bg=t["bg"])
        self._bar.pack(fill="x", padx=24, pady=(0, 8))
        self._build_buttons()
        self._status = tk.Label(self._bar, text="", bg=t["bg"], fg=t["muted"],
                                font=(F, 10, "bold"))
        self._status.pack(side="right")
        # start with the run controls disabled until a scan has happened
        self._run_btn.set_enabled(False)
        self._pause_btn.set_enabled(False)
        self._stop_btn.set_enabled(False)

        # progress bars (scan = accent, organize = success green)
        pf = tk.Frame(self, bg=t["bg"])
        pf.pack(fill="x", padx=24, pady=(0, 8))
        for r, lbl in enumerate(["Scan", "Organize"]):
            l = tk.Label(pf, text=lbl, bg=t["bg"], fg=t["muted"], font=(F, 8, "bold"))
            l.grid(row=r, column=0, sticky="w", padx=(0, 12))
        self._scan_prog = CProgress(pf, color=t["accent"], theme=t)
        self._scan_prog.grid(row=0, column=1, sticky="ew", pady=2)
        self._prog = CProgress(pf, color=t["ok"], theme=t)
        self._prog.grid(row=1, column=1, sticky="ew", pady=2)
        pf.columnconfigure(1, weight=1)

        # results table
        self._sort_col = None      # column id currently sorted, or None
        self._sort_state = None    # "asc" | "desc" | None (default order)
        self._order = []           # canonical row order (path iids)
        self._row_status = {}      # iid -> status tag (so zebra can be re-applied)
        tf = ttk.Frame(self)
        tf.pack(fill="both", expand=True, padx=24, pady=6)
        cols = tuple(c[0] for c in RESULT_COLUMNS)
        self._tree = ttk.Treeview(tf, columns=cols, show="headings", height=13)
        for cid, label, width, anchor in RESULT_COLUMNS:
            self._tree.heading(cid, text=label, anchor="w",
                               command=lambda c=cid: self._sort_by_column(c))
            self._tree.column(cid, width=width, anchor=anchor)
        # Only a slim vertical scrollbar is shown; the columns (≈1070px) scroll
        # horizontally via native means — mouse wheel while hovering, Shift+wheel,
        # and touchpad two-finger pan — instead of a cluttering bar at the bottom.
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._tree.yview,
                            style="Slim.Vertical.TScrollbar")
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        # Empty-state overlay: shown over the (empty) table with a rotating
        # stage-side one-liner, hidden as soon as there's anything to list.
        self._empty = tk.Frame(tf, bg=t["surface"])
        self._empty.grid(row=0, column=0, sticky="nsew", padx=24, pady=40)
        self._empty_lbl = tk.Label(self._empty, text=_GIG_LINES[0], bg=t["surface"],
                                   fg=t["muted"], font=(F, 10, "italic"),
                                   wraplength=620, justify="center")
        self._empty_lbl.pack()
        self._gig_idx = 0
        self._gig_timer = None
        # Native horizontal scrolling (wheel over the table / Shift+wheel /
        # touchpad). The wheel is captured only while the pointer is over the
        # tree; <MouseWheel> on Windows scrolls the hovered widget, so this
        # stays local to the table.
        self._bind_native_hscroll(self._tree)
        # Status colours are shared with the log so the table and log agree.
        for tag, fg in [("ok", t["ok"]), ("dry-run", t["info"]),
                        ("partial", t["warn"]), ("skipped", t["muted"]), ("error", t["err"])]:
            self._tree.tag_configure(tag, foreground=fg)
        # Zebra striping for readability (background only).
        self._tree.tag_configure("even", background=t["surface"])
        self._tree.tag_configure("odd", background=t["zebra"])

        # log — each line is coloured by its leading marker (see _log_tag)
        # instead of one faint grey, so "found / fetched / error" stand out.
        # A plain tk.Text + ttk.Scrollbar keeps the scrollbar consistent with
        # the results table (the legacy ScrolledText embeds a 3-D tk bar).
        logf = tk.Frame(self, bg=t["surface"],
                        highlightthickness=1, highlightbackground=t["surface2"])
        logf.pack(fill="x", padx=24, pady=(0, 12))
        self._log = tk.Text(logf, height=5, bg=t["surface"], fg=t["fg"],
                            insertbackground=t["fg"], font=(MONO, 9),
                            relief="flat", padx=10, pady=8,
                            highlightthickness=0, wrap="word", bd=0)
        lsb = ttk.Scrollbar(logf, orient="vertical", command=self._log.yview,
                            style="Slim.Vertical.TScrollbar")
        self._log.configure(yscrollcommand=lsb.set)
        self._log.grid(row=0, column=0, sticky="nsew")
        lsb.grid(row=0, column=1, sticky="ns")
        logf.rowconfigure(0, weight=1)
        logf.columnconfigure(0, weight=1)
        for tag, fg in [("ok", t["ok"]), ("info", t["info"]), ("acc", t["accent"]),
                        ("warn", t["warn"]), ("err", t["err"]), ("muted", t["muted"]),
                        ("text", t["fg"])]:
            self._log.tag_config(tag, foreground=fg)

        # keyboard shortcuts
        self.bind("<Control-s>", lambda e: self._scan())
        self.bind("<Control-S>", lambda e: self._scan())
        self.bind("<Escape>", lambda e: self._stop())
        self.bind("<space>", lambda e: self._toggle_pause())
        # When focus returns to this window (e.g. a modal folder picker closed)
        # re-derive every button's hover state, in case a <Leave> was dropped
        # while the dialog had the grab.
        self.bind("<FocusIn>", lambda e: self._reconcile_all())

    def _reconcile_all(self):
        def walk(w):
            for child in w.winfo_children():
                if isinstance(child, CButton):
                    child._reconcile()
                walk(child)
        walk(self)

    def _sync_empty(self):
        """Show the rotating empty-state when the table has no rows, else hide it."""
        try:
            has_rows = bool(self._tree.get_children(""))
        except tk.TclError:
            return
        if has_rows:
            self._hide_idle()
            return
        self._empty.grid()
        if self._gig_timer is None:
            self._rotate_gig()

    def _rotate_gig(self):
        """Cycle the idle one-liner; reschedules itself while the table is empty."""
        try:
            if not self._tree.get_children(""):
                self._gig_idx = (self._gig_idx + 1) % len(_GIG_LINES)
                self._empty_lbl.config(text=_GIG_LINES[self._gig_idx])
            self._gig_timer = self.after(_GIG_INTERVAL_MS, self._rotate_gig)
        except tk.TclError:
            pass

    def _hide_idle(self):
        """Immediately hide the idle overlay (e.g. rows are about to stream in)."""
        if self._gig_timer:
            self.after_cancel(self._gig_timer)
            self._gig_timer = None
        self._empty.grid_remove()

    def _build_buttons(self):
        """Create the action CButtons (built once; the palette never changes)."""
        t = self._t
        self._scan_btn = CButton(self._bar, "1 · Scan", self._scan,
                                 variant="secondary", theme=t)
        self._scan_btn.pack(side="left")
        self._run_btn = CButton(self._bar, "2 · Organize", self._run,
                                variant="primary", theme=t, width=150)
        self._run_btn.pack(side="left", padx=(10, 0))
        self._pause_btn = CButton(self._bar, "⏸  Pause", self._toggle_pause,
                                  variant="secondary", theme=t, width=110)
        self._pause_btn.pack(side="left", padx=(10, 0))
        self._stop_btn = CButton(self._bar, "⏹  Stop", self._stop,
                                 variant="danger", theme=t, width=100)
        self._stop_btn.pack(side="left", padx=(10, 0))

    def _bind_native_hscroll(self, tree):
        """Scroll the tree horizontally without a persistent bottom scrollbar.

        On Windows <MouseWheel> is delivered to the widget under the pointer,
        so binding per-wheel here only scrolls the table while it is hovered
        (a plain scroll would nudge rows; Shift+wheel or a horizontal touchpad
        pan moves columns). Left/right arrows also pan the visible columns.
        """
        def _wheel(event):
            if event.state & 0x0001:          # Shift held → horizontal pan
                tree.xview_scroll(-int(event.delta / 120) * 3, "units")
        tree.bind("<MouseWheel>", _wheel, add="+")
        tree.bind("<Button-4>", lambda e: tree.xview_scroll(-3, "units"), add="+")  # trackup
        tree.bind("<Button-5>", lambda e: tree.xview_scroll(3, "units"), add="+")   # trackdown
        tree.bind("<Prior>", lambda e: tree.xview_scroll(-5, "pages"), add="+")
        tree.bind("<Next>", lambda e: tree.xview_scroll(5, "pages"), add="+")

    # ── tooltip helper ────────────────────────────────────────────────────────

    def _add_tooltip(self, widget, text):
        tip = None

        def show(event):
            nonlocal tip
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            t = self._t
            tk.Label(tip, text=text, bg=t["surface2"], fg=t["fg"],
                     font=(D_FONT, 9), relief="flat", padx=8, pady=4
                     ).pack()

        def hide(event):
            nonlocal tip
            if tip:
                tip.destroy()
                tip = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _pick_src(self):
        d = filedialog.askdirectory()
        if d: self._src_var.set(d)

    def _pick_dst(self):
        d = filedialog.askdirectory()
        if d: self._dst_var.set(d)

    def _logmsg(self, m):
        # Drop a few very noisy per-file lines to keep the log readable.
        skip = (" ✓ MusicBrainz", " ✓ AcoustID", " ⚠ AcoustID", " 🎼")
        if any(m.startswith(p) for p in skip):
            return
        tag = _log_tag(m)
        self.after(0, lambda: (self._log.insert("end", m + "\n", tag),
                               self._log.see("end")))

    def _setstatus(self, m):
        self.after(0, lambda: self._status.config(text=m))

    def _setprog(self, v, mx):
        self.after(0, lambda: self._prog.set_value(v, mx))

    # ── table sorting ─────────────────────────────────────────────────────────

    def _sort_by_column(self, cid):
        """Three-state header sort: click cycles asc -> desc -> default.

        Default (None) restores the original insertion order (path order for a
        fresh scan, or the order left by the previous run) by re-inserting
        rows in their current top-to-bottom order.
        """
        state = next_sort_state(cid, self._sort_col, self._sort_state)
        self._sort_col, self._sort_state = cid, state
        order = self._tree.get_children("")  # current visual top-to-bottom
        idx = tuple(c[0] for c in RESULT_COLUMNS).index(cid)

        if state is None:
            # Restore default: pin the current visual order as the new order.
            self._order = list(order)
        else:
            reverse = (state == "desc")
            keyed = [(path, self._tree.item(path, "values"),
                      self._tree.item(path, "tags")) for path in order]

            def key(item):
                raw = item[1][idx] if len(item[1]) > idx else ""
                return sort_key(cid, raw)

            keyed.sort(key=key, reverse=reverse)
            self._order = [iid for iid, _v, _t in keyed]

        # Reorder rows and clear/set heading arrows.
        for i, iid in enumerate(self._order):
            self._tree.move(iid, "", i)
        for c in _RESULT_LABELS:
            if c == cid and state is not None:
                self._tree.heading(c, text=_RESULT_LABELS[c] + (" ▾" if state == "desc" else " ▴"))
            else:
                self._tree.heading(c, text=_RESULT_LABELS[c])
        self._rezebra()

    def _col_mark(self, has):
        """Glyph for the Lyrics/Art columns."""
        return "✓" if has else "·"

    def _rezebra(self):
        """Apply zebra background (by current position) + per-row status tag."""
        for i, iid in enumerate(self._tree.get_children("")):
            tags = ["odd" if i % 2 else "even"]
            st = self._row_status.get(iid)
            if st:
                tags.append(st)
            self._tree.item(iid, tags=tags)

    # ── scan ──────────────────────────────────────────────────────────────────

    def _scan(self):
        src = self._src_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showerror("Error", "Select a valid source folder.")
            return
        self._tree.delete(*self._tree.get_children())
        self._audio_files = []
        self._order = []
        self._sort_col, self._sort_state = None, None
        for c in _RESULT_LABELS:
            self._tree.heading(c, text=_RESULT_LABELS[c])
        self._hide_idle()          # rows are about to stream in; don't flash the idle line
        self._scan_btn.set_enabled(False)
        self._setstatus("Scanning…")
        self._scan_prog.start()
        threading.Thread(target=self._scan_worker, args=(src,), daemon=True).start()

    def _scan_worker(self, src):
        """Run entirely in background thread — only schedules Tk updates via after()."""
        audio_files = collect_audio_files(src)
        total = len(audio_files)

        # Switch progress bar from indeterminate to determinate
        self.after(0, lambda: (
            self._scan_prog.stop(),
            self._scan_prog.set_value(0, max(total, 1)),
        ))

        self._audio_files = audio_files

        for i, p in enumerate(audio_files):
            # read_tags runs in background thread — no Tk calls here
            t = read_tags(p)
            genre_str = ", ".join(t.get("genres", [])[:2])
            has_meta  = any(t.get(k) for k in ("artist", "album", "title"))
            row_values = (
                os.path.basename(p),
                t.get("artist", ""), t.get("album", ""),
                t.get("year", ""), t.get("track", ""), t.get("title", ""),
                genre_str,
                self._col_mark(False), self._col_mark(False),  # lyrics/art: unknown until Organize
                "ready"
            )
            row_tag = "partial" if has_meta else "error"
            progress = i + 1

            def _insert(path=p, vals=row_values, tag=row_tag, prog=progress):
                self._tree.insert("", "end", iid=path, values=vals, tags=(tag,))
                self._row_status[path] = tag
                self._scan_prog.set_value(prog, max(len(audio_files), 1))
            self.after(0, _insert)

        # Finalise on main thread (runs after all per-row inserts are queued)
        self.after(0, lambda: (
            setattr(self, "_order", list(self._tree.get_children(""))),
            self._rezebra(),
            self._scan_btn.set_enabled(True),
            self._run_btn.set_enabled(bool(audio_files)),
            self._setstatus(f"{total} files found"),
            self._logmsg(f"Scanned '{src}' — {total} audio file(s) found"),
            self._sync_empty(),     # re-show the idle line if the folder was empty
        ))

    # ── organize ──────────────────────────────────────────────────────────────

    def _run(self):
        dst = self._dst_var.get().strip() or self._src_var.get().strip()
        src = self._src_var.get().strip()
        if not dst:
            messagebox.showerror("Error", "Select an output folder.")
            return
        if not self._audio_files:
            messagebox.showwarning("No files", "Please scan a folder first.")
            return
        if not self._copy_mode.get() and os.path.abspath(src) == os.path.abspath(dst):
            if not messagebox.askyesno("Warning",
                                       "Source and output folders are the same.\n"
                                       "Files will be reorganized in-place.\nContinue?"):
                return
        os.makedirs(dst, exist_ok=True)
        self._stop_flag.clear()
        self._pause_event.set()
        self._scan_btn.set_enabled(False)
        self._run_btn.set_enabled(False)
        self._pause_btn.set_enabled(True)
        self._pause_btn.set_text("⏸  Pause")
        self._stop_btn.set_enabled(True)
        self._prog.set_value(0, 1)
        opts = {
            "copy":         self._copy_mode.get(),
            "acoustid":     self._acoustid.get(),
            "write_tags":   self._wtags.get(),
            "overwrite":    self._overwrite.get(),
            "dry_run":      self._dry_run.get(),
            "fetch_art":    self._fetch_art.get(),
            "fetch_lyrics": self._fetch_lyrics.get(),
            "overwrite_art": self._overwrite_art.get(),
        }
        threading.Thread(target=self._worker,
                         args=(dst, opts, self._do_merge.get()), daemon=True).start()

    def _toggle_pause(self):
        if self._pause_event.is_set():
            self._pause_event.clear()
            self._pause_btn.set_text("▶  Resume")
            self._setstatus("Paused")
            self._logmsg("⏸ Paused")
        else:
            self._pause_event.set()
            self._pause_btn.set_text("⏸  Pause")
            self._logmsg("▶ Resumed")

    def _stop(self):
        self._pause_event.set()   # unblock worker thread if paused
        self._stop_flag.set()
        self._logmsg("Stopping…")

    def _worker(self, dst, opts, do_merge):
        total = len(self._audio_files)
        done  = 0
        stats = {"ok": 0, "skipped": 0, "errors": 0}

        for path in self._audio_files:
            self._pause_event.wait()   # blocks here while paused
            if self._stop_flag.is_set():
                break
            fname = os.path.basename(path)
            self._setstatus(f"{done + 1}/{total} {fname[:40]}")
            meta, source, status, dest = process_file(
                path, dst, opts, stats, log_cb=self._logmsg)
            done += 1
            self._setprog(done, total)
            tag = status if status in ("ok", "error", "skipped", "dry-run") else "partial"
            genre_str  = ", ".join(meta.get("genres", [])[:2])
            src_label  = {"MusicBrainz": "Online", "AcoustID": "Online",
                          "tags": "Local tags"}.get(source, source)
            lyrics     = bool(meta.get("_lyrics_plain") or meta.get("_lyrics_synced"))
            art        = bool(meta.get("_art_found"))
            def _update(p=path, m=meta, sl=src_label, st=status, tg=tag, gs=genre_str,
                        ly=lyrics, ar=art):
                self._tree.item(p, values=(
                    os.path.basename(p),
                    m.get("artist", ""), m.get("album", ""),
                    m.get("year", ""),
                    m.get("track", "").zfill(2) if m.get("track") else "",
                    m.get("title", ""), gs,
                    self._col_mark(ly), self._col_mark(ar),
                    f"✓ {sl}" if st == "ok" else
                    f"— {sl}" if st == "dry-run" else
                    "↷ skipped" if st == "skipped" else "✗ error"
                ), tags=(tg,))
                self._row_status[p] = tg
                self._rezebra()
            self.after(0, _update)

        if do_merge and not opts.get("dry_run") and not self._stop_flag.is_set():
            self._setstatus("Merging duplicate albums…")
            merge_duplicate_albums(dst, log_cb=self._logmsg)

        summary = f"Done — ✓ {stats['ok']}  ↷ {stats['skipped']}  ✗ {stats['errors']}"
        self.after(0, lambda: (
            self._scan_btn.set_enabled(True),
            self._run_btn.set_enabled(True),
            self._pause_btn.set_enabled(False),
            self._stop_btn.set_enabled(False),
            self._setstatus(summary),
            messagebox.showinfo("Done",
                                f"Finished!\n\n"
                                f"✓ Organized: {stats['ok']}\n"
                                f"↷ Skipped:   {stats['skipped']}\n"
                                f"✗ Errors:    {stats['errors']}")))


def main():
    """Application entry point (backing the ``music-organizer-gui`` script)."""
    if sys.platform == "win32":
        # Declare DPI awareness before Tk builds any widget, so on a display
        # that's scaled (125%/150%) the window renders at native resolution
        # instead of being bitmap-scaled small and blurry by Windows.
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    App().mainloop()


if __name__ == "__main__":
    main()
