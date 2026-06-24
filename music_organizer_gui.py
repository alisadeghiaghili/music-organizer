#!/usr/bin/env python3
"""music_organizer_gui.py — GUI frontend"""

import os, sys, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from music_core import collect_mp3s, read_tags, process_file, merge_duplicate_albums, fpcalc_status
from fpcalc_installer import download_fpcalc


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("\U0001f3b8 Music Organizer")
        self.geometry("1000x760")
        self.configure(bg="#1a1a1a")
        self.resizable(True, True)
        self._stop_flag   = threading.Event()
        self._pause_event = threading.Event()  # set=running, clear=paused
        self._pause_event.set()
        self._mp3s      = []
        self._fp_banner = None
        self._build_ui()
        self.after(300, self._check_fpcalc)

    # ── fpcalc banner ─────────────────────────────────────────────────────────

    def _check_fpcalc(self):
        status, path = fpcalc_status()
        if status == "missing":
            self._show_fp_banner()
        else:
            self._fp_lbl.config(text="\u25cf Audio fingerprinting ready", fg="#6daa45")

    def _show_fp_banner(self):
        if self._fp_banner:
            return
        banner = tk.Frame(self, bg="#2a1f00", pady=8)
        banner.pack(fill="x", padx=20, pady=(0, 4))
        self._fp_banner = banner

        tk.Label(banner,
                 text="\u26a0 Audio fingerprinting unavailable \u2014 metadata lookup may be less accurate.",
                 bg="#2a1f00", fg="#f0c060", font=("Segoe UI", 9, "bold")
                 ).pack(side="left", padx=(10, 6))

        self._fp_prog_frame = tk.Frame(banner, bg="#2a1f00")
        self._fp_prog_frame.pack(side="left", padx=6)
        self._fp_prog_lbl = tk.Label(self._fp_prog_frame, text="",
                                     bg="#2a1f00", fg="#aaa", font=("Segoe UI", 9))
        self._fp_prog_lbl.pack(side="top")
        self._fp_prog = ttk.Progressbar(self._fp_prog_frame, length=180, mode="determinate")

        def start_download():
            self._fp_dl_btn.config(state="disabled", text="Downloading\u2026")
            self._fp_prog.pack(side="top", pady=2)
            self._fp_prog_lbl.pack(side="top")
            download_fpcalc(
                progress_cb=self._on_fp_progress,
                done_cb=self._on_fp_done,
                error_cb=self._on_fp_error,
            )

        self._fp_dl_btn = tk.Button(
            banner, text="\u2b07 Enable fingerprinting",
            bg="#e8af34", fg="#111", font=("Segoe UI", 9, "bold"),
            relief="flat", padx=10, pady=3, cursor="hand2",
            command=start_download)
        self._fp_dl_btn.pack(side="left", padx=6)

        def dismiss():
            banner.destroy()
            self._fp_banner = None
        tk.Button(banner, text="\u2715", bg="#2a1f00", fg="#f0c060",
                  font=("Segoe UI", 10), relief="flat", cursor="hand2",
                  command=dismiss).pack(side="right", padx=10)

    def _on_fp_progress(self, downloaded, total):
        def _update():
            if total > 0:
                pct = int(downloaded / total * 100)
                self._fp_prog.config(maximum=100, value=pct)
                self._fp_prog_lbl.config(
                    text=f"{downloaded//1024:,} / {total//1024:,} KB")
            else:
                self._fp_prog.config(mode="indeterminate")
                self._fp_prog.start(10)
        self.after(0, _update)

    def _on_fp_done(self, path):
        def _update():
            if self._fp_banner:
                self._fp_banner.destroy()
                self._fp_banner = None
            self._fp_lbl.config(text="\u25cf Audio fingerprinting ready", fg="#6daa45")
            self._acoustid.set(True)
            messagebox.showinfo("Ready",
                                "Audio fingerprinting has been enabled.\n"
                                "Metadata accuracy is now improved.")
        self.after(0, _update)

    def _on_fp_error(self, exc):
        def _update():
            self._fp_dl_btn.config(state="normal", text="\u2b07 Enable fingerprinting")
            self._fp_prog.stop()
            messagebox.showerror("Download failed",
                                 f"Could not enable fingerprinting:\n{exc}")
        self.after(0, _update)

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        BG, FG, ACC, CARD = "#1a1a1a", "#e0e0e0", "#4f98a3", "#242424"
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",      background=BG)
        s.configure("TLabel",      background=BG,  foreground=FG,   font=("Segoe UI", 10))
        s.configure("Head.TLabel", background=BG,  foreground=ACC,  font=("Segoe UI", 13, "bold"))
        s.configure("TButton",     background=ACC, foreground="#fff",
                    font=("Segoe UI", 10, "bold"), relief="flat", padding=6)
        s.map("TButton",
              background=[("active", "#227f8b"), ("disabled", "#555")],
              foreground=[("disabled", "#aaa")])
        s.configure("Stop.TButton",  background="#a13544", foreground="#fff",
                    font=("Segoe UI", 10, "bold"), relief="flat", padding=6)
        s.map("Stop.TButton",  background=[("active", "#7d2b35")])
        s.configure("Pause.TButton", background="#5a4a1a", foreground="#f0c060",
                    font=("Segoe UI", 10, "bold"), relief="flat", padding=6)
        s.map("Pause.TButton", background=[("active", "#3d3210")])
        s.configure("TProgressbar", troughcolor=CARD, background=ACC, thickness=6)
        s.configure("Treeview",     background=CARD, foreground=FG,
                    fieldbackground=CARD, rowheight=24, font=("Segoe UI", 9))
        s.configure("Treeview.Heading", background="#2d2d2d", foreground=ACC,
                    font=("Segoe UI", 9, "bold"))
        s.map("Treeview", background=[("selected", "#2e4e52")])

        # header
        hdr = ttk.Frame(self)
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        ttk.Label(hdr, text="\U0001f3b8 Music Organizer", style="Head.TLabel").pack(side="left")
        self._fp_lbl = tk.Label(hdr, text="\u25cf Checking\u2026",
                                bg=BG, fg="#e8af34", font=("Segoe UI", 9))
        self._fp_lbl.pack(side="right")

        # folder rows
        row1 = ttk.Frame(self)
        row1.pack(fill="x", padx=20, pady=4)
        self._src_var = tk.StringVar()
        self._dst_var = tk.StringVar()
        for i, (lbl, var, cb) in enumerate([
            ("Source folder:", self._src_var, self._pick_src),
            ("Output folder:", self._dst_var, self._pick_dst),
        ]):
            ttk.Label(row1, text=lbl, width=14).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(row1, textvariable=var, width=58,
                      font=("Segoe UI", 10)).grid(row=i, column=1, padx=6)
            ttk.Button(row1, text="Browse", command=cb).grid(row=i, column=2)

        # checkboxes
        self._copy_mode    = tk.BooleanVar(value=True)
        self._acoustid     = tk.BooleanVar(value=True)
        self._wtags        = tk.BooleanVar(value=True)
        self._fetch_art    = tk.BooleanVar(value=True)
        self._overwrite_art = tk.BooleanVar(value=False)
        self._overwrite    = tk.BooleanVar(value=False)
        self._dry_run      = tk.BooleanVar(value=False)
        self._do_merge     = tk.BooleanVar(value=True)

        opt = ttk.Frame(self)
        opt.pack(fill="x", padx=20, pady=6)
        for var, txt in [
            (self._copy_mode,    "Keep originals"),
            (self._acoustid,     "Deep metadata lookup"),
            (self._wtags,        "Save enriched tags"),
            (self._fetch_art,    "Download album art"),
            (self._overwrite_art, "Replace existing art"),
            (self._overwrite,    "Overwrite duplicates"),
            (self._dry_run,      "Preview only"),
            (self._do_merge,     "Merge duplicate albums"),
        ]:
            tk.Checkbutton(opt, variable=var, text=txt,
                           bg=BG, fg=FG, selectcolor="#333",
                           activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 10)).pack(side="left", padx=7)

        # action buttons
        btn = ttk.Frame(self)
        btn.pack(fill="x", padx=20, pady=4)
        self._scan_btn  = ttk.Button(btn, text="1. Scan",      command=self._scan)
        self._scan_btn.pack(side="left", padx=(0, 8))
        self._run_btn   = ttk.Button(btn, text="2. Organize!", command=self._run, state="disabled")
        self._run_btn.pack(side="left", padx=(0, 8))
        self._pause_btn = ttk.Button(btn, text="\u23f8 Pause",  command=self._toggle_pause,
                                     style="Pause.TButton", state="disabled")
        self._pause_btn.pack(side="left", padx=(0, 4))
        self._stop_btn  = ttk.Button(btn, text="\u23f9 Stop",   command=self._stop,
                                     style="Stop.TButton",  state="disabled")
        self._stop_btn.pack(side="left")
        self._status = ttk.Label(btn, text="", foreground=ACC)
        self._status.pack(side="right")

        # dual progress bars
        pf = ttk.Frame(self)
        pf.pack(fill="x", padx=20, pady=(4, 0))
        tk.Label(pf, text="Scan",     bg=BG, fg="#777", font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
        self._scan_prog = ttk.Progressbar(pf, mode="determinate")
        self._scan_prog.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        tk.Label(pf, text="Organize", bg=BG, fg="#777", font=("Segoe UI", 8)).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self._prog = ttk.Progressbar(pf, mode="determinate")
        self._prog.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(3, 0))
        pf.columnconfigure(1, weight=1)

        # results table
        tf = ttk.Frame(self)
        tf.pack(fill="both", expand=True, padx=20, pady=6)
        cols   = ("file", "artist", "album", "year", "trk", "title", "genre", "status")
        widths = {"file": 170, "artist": 115, "album": 145, "year": 46,
                  "trk": 38, "title": 145, "genre": 110, "status": 72}
        self._tree = ttk.Treeview(tf, columns=cols, show="headings", height=11)
        for c in cols:
            self._tree.heading(c, text=c.capitalize())
            self._tree.column(c, width=widths[c], anchor="w")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for tag, fg in [("ok", "#6daa45"), ("dry-run", "#4f98a3"),
                        ("partial", "#e8af34"), ("skipped", "#797876"), ("error", "#a13544")]:
            self._tree.tag_configure(tag, foreground=fg)

        # log
        self._log = scrolledtext.ScrolledText(self, height=5,
                                              bg="#111", fg="#888",
                                              font=("Consolas", 9), relief="flat")
        self._log.pack(fill="x", padx=20, pady=(0, 10))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _pick_src(self):
        d = filedialog.askdirectory()
        if d: self._src_var.set(d)

    def _pick_dst(self):
        d = filedialog.askdirectory()
        if d: self._dst_var.set(d)

    def _logmsg(self, m):
        skip = (" \u2713 MusicBrainz", " \u2713 AcoustID", " \u27f3", " \u26a0 AcoustID",
                " \u2717 Could not", " ! Tag", " [DRY]", " genres",
                " \U0001f5bc", " \u26a0 Album art")
        if any(m.startswith(p) for p in skip):
            return
        self.after(0, lambda: (self._log.insert("end", m + "\n"), self._log.see("end")))

    def _setstatus(self, m):
        self.after(0, lambda: self._status.config(text=m))

    def _setprog(self, v, mx):
        self.after(0, lambda: self._prog.config(maximum=max(mx, 1), value=v))

    # ── scan ──────────────────────────────────────────────────────────────────

    def _scan(self):
        src = self._src_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showerror("Error", "Select a valid source folder.")
            return
        self._tree.delete(*self._tree.get_children())
        self._mp3s = []
        self._scan_btn.config(state="disabled")
        self._setstatus("Scanning\u2026")
        self._scan_prog.config(value=0, mode="indeterminate")
        self._scan_prog.start(12)
        threading.Thread(target=self._scan_worker, args=(src,), daemon=True).start()

    def _scan_worker(self, src):
        mp3s  = collect_mp3s(src)
        total = len(mp3s)

        def populate():
            self._scan_prog.stop()
            self._scan_prog.config(mode="determinate", maximum=max(total, 1), value=0)
            self._mp3s = mp3s
            for i, p in enumerate(mp3s):
                t = read_tags(p)
                genre_str = ", ".join(t.get("genres", [])[:2])
                has_meta  = any(t.get(k) for k in ("artist", "album", "title"))
                self._tree.insert("", "end", iid=p, values=(
                    os.path.basename(p),
                    t.get("artist", ""), t.get("album", ""),
                    t.get("year", ""), t.get("track", ""), t.get("title", ""),
                    genre_str, "ready"
                ), tags=("partial" if has_meta else "error",))
                self._scan_prog.config(value=i + 1)
                if (i + 1) % 20 == 0:
                    self.update_idletasks()
            self._scan_btn.config(state="normal")
            self._run_btn.config(state="normal" if mp3s else "disabled")
            self._setstatus(f"{total} files found")
            self._logmsg(f"Scanned '{src}' \u2014 {total} MP3 file(s) found")

        self.after(0, populate)

    # ── organize ──────────────────────────────────────────────────────────────

    def _run(self):
        dst = self._dst_var.get().strip() or self._src_var.get().strip()
        src = self._src_var.get().strip()
        if not dst:
            messagebox.showerror("Error", "Select an output folder.")
            return
        if not self._mp3s:
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
        self._scan_btn.config(state="disabled")
        self._run_btn.config(state="disabled")
        self._pause_btn.config(state="normal", text="\u23f8 Pause")
        self._stop_btn.config(state="normal")
        opts = {
            "copy":         self._copy_mode.get(),
            "acoustid":     self._acoustid.get(),
            "write_tags":   self._wtags.get(),
            "overwrite":    self._overwrite.get(),
            "dry_run":      self._dry_run.get(),
            "fetch_art":    self._fetch_art.get(),
            "overwrite_art": self._overwrite_art.get(),
        }
        threading.Thread(target=self._worker,
                         args=(dst, opts, self._do_merge.get()), daemon=True).start()

    def _toggle_pause(self):
        if self._pause_event.is_set():
            self._pause_event.clear()
            self._pause_btn.config(text="\u25b6 Resume")
            self._setstatus("Paused")
            self._logmsg("\u23f8 Paused")
        else:
            self._pause_event.set()
            self._pause_btn.config(text="\u23f8 Pause")
            self._logmsg("\u25b6 Resumed")

    def _stop(self):
        self._pause_event.set()   # unblock worker thread if paused
        self._stop_flag.set()
        self._logmsg("Stopping\u2026")

    def _worker(self, dst, opts, do_merge):
        total = len(self._mp3s)
        done  = 0
        stats = {"ok": 0, "skipped": 0, "errors": 0}

        for path in self._mp3s:
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
            self.after(0, lambda p=path, m=meta, sl=src_label, st=status, tg=tag, gs=genre_str:
                       self._tree.item(p, values=(
                           os.path.basename(p),
                           m.get("artist", ""), m.get("album", ""),
                           m.get("year", ""),
                           m.get("track", "").zfill(2) if m.get("track") else "",
                           m.get("title", ""), gs,
                           f"\u2713 {sl}" if st == "ok" else
                           f"\u2014 {sl}" if st == "dry-run" else
                           "\u21b7 skipped" if st == "skipped" else "\u2717 error"
                       ), tags=(tg,)))

        if do_merge and not opts.get("dry_run") and not self._stop_flag.is_set():
            self._setstatus("Merging duplicate albums\u2026")
            merge_duplicate_albums(dst, log_cb=self._logmsg)

        summary = f"Done \u2014 \u2713 {stats['ok']} \u21b7 {stats['skipped']} \u2717 {stats['errors']}"
        self.after(0, lambda: (
            self._scan_btn.config(state="normal"),
            self._run_btn.config(state="normal"),
            self._pause_btn.config(state="disabled", text="\u23f8 Pause"),
            self._stop_btn.config(state="disabled"),
            self._setstatus(summary),
            messagebox.showinfo("Done",
                                f"Finished!\n\n"
                                f"\u2713 Organized: {stats['ok']}\n"
                                f"\u21b7 Skipped:   {stats['skipped']}\n"
                                f"\u2717 Errors:    {stats['errors']}")))


if __name__ == "__main__":
    App().mainloop()
