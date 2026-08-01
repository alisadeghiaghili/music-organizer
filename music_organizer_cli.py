#!/usr/bin/env python3
"""
music_organizer_cli.py
Usage: python music_organizer_cli.py [SOURCE] [OUTPUT] [OPTIONS]
       python music_organizer_cli.py          (interactive)
"""

import os, sys, argparse, threading
from music_core import collect_mp3s, process_file, merge_duplicate_albums, fpcalc_status
from fpcalc_installer import download_fpcalc

# ── Pause/Resume state ────────────────────────────────────────────────────────
_pause_event = threading.Event()
_pause_event.set()  # Start in running state
_stop_flag = threading.Event()

try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import (Progress, SpinnerColumn, BarColumn,
                               TextColumn, TimeElapsedColumn, DownloadColumn)
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel
    from rich import box
    HAS_RICH = True
    console  = Console()
except ImportError:
    HAS_RICH = False
    console  = None


def cprint(msg, style=""):
    if HAS_RICH: console.print(msg, style=style)
    else:        print(msg)


# ── fingerprinting installer ──────────────────────────────────────────────────

def _install_fingerprint_tool():
    if HAS_RICH:
        console.print(Panel(
            "[yellow]\u26a0 Audio fingerprinting is unavailable.[/yellow]\n"
            "[dim]Enabling it improves metadata accuracy for untagged files (~2 MB download).[/dim]",
            border_style="yellow", title="Fingerprinting unavailable"))
        if not Confirm.ask("Enable audio fingerprinting automatically?", default=True):
            return False
    else:
        print("\n\u26a0 Audio fingerprinting is unavailable.")
        ans = input("Enable it automatically? (~2 MB download) [Y/n]: ").strip().lower()
        if ans == "n":
            return False

    done_event = threading.Event()
    result     = {"path": None, "error": None}

    if HAS_RICH:
        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]Enabling fingerprinting\u2026"),
            BarColumn(bar_width=30),
            TextColumn("[cyan]{task.percentage:>3.0f}%"),
            DownloadColumn(),
            console=console, transient=False,
        ) as prog:
            task = prog.add_task("dl", total=100)

            def on_progress(dl, total):
                if total > 0:
                    prog.update(task, completed=int(dl / total * 100), total=100)

            def on_done(path):
                prog.update(task, completed=100)
                result["path"] = path
                done_event.set()

            def on_error(exc):
                result["error"] = exc
                done_event.set()

            download_fpcalc(on_progress, on_done, on_error)
            done_event.wait()
    else:
        print("Downloading\u2026")

        def on_progress(dl, total):
            if total > 0:
                pct = int(dl / total * 100)
                bar = "\u2588" * (pct // 5) + "\u2591" * (20 - pct // 5)
                print(f"\r [{bar}] {pct}% {dl//1024}KB/{total//1024}KB",
                      end="", flush=True)

        def on_done(path):
            result["path"] = path
            done_event.set()

        def on_error(exc):
            result["error"] = exc
            done_event.set()

        download_fpcalc(on_progress, on_done, on_error)
        done_event.wait()
        print()

    if result["error"]:
        cprint(f"[red]Failed:[/red] {result['error']}" if HAS_RICH
               else f"Failed: {result['error']}")
        return False

    cprint("[green]\u2713 Audio fingerprinting enabled.[/green]" if HAS_RICH
           else "\u2713 Audio fingerprinting enabled.")
    return True


# ── results table ─────────────────────────────────────────────────────────────

def show_table(rows):
    if not HAS_RICH:
        for r in rows:
            print(" | ".join(str(x) for x in r))
        return
    t = Table(box=box.SIMPLE_HEAD, header_style="bold cyan", border_style="dim")
    for col, w in [("#", 4), ("Artist", 20), ("Album", 22), ("Yr", 5), ("Trk", 4),
                   ("Title", 26), ("Genre", 16), ("Result", 14)]:
        t.add_column(col, width=w)
    STATUS = {
        "ok":      ("[green]\u2713 saved[/green]",    "green"),
        "skipped": ("[yellow]\u21b7 skipped[/yellow]", "yellow"),
        "error":   ("[red]\u2717 error[/red]",         "red"),
        "dry-run": ("[cyan]\u2014 preview[/cyan]",     "cyan"),
    }
    for r in rows:
        *fields, src_label, st = r
        rich_st, _ = STATUS.get(st, (st, "white"))
        result_col = f"{rich_st} [dim]({src_label})[/dim]"
        t.add_row(*[str(x) for x in fields], result_col)
    console.print(t)


def show_summary(stats, dst):
    if HAS_RICH:
        console.print(Panel(
            f"[green]\u2713 Organized:[/green] {stats['ok']}\n"
            f"[yellow]\u21b7 Skipped:[/yellow]   {stats['skipped']}\n"
            f"[red]\u2717 Errors:[/red]     {stats['errors']}\n\n"
            f"[dim]Output \u2192 {dst}[/dim]",
            title="[bold]Done[/bold]", border_style="green"))
    else:
        print(f"\nDone \u2014 OK:{stats['ok']} Skipped:{stats['skipped']} Errors:{stats['errors']}")


# ── keyboard listener (cross-platform) ───────────────────────────────────────

def _check_keyboard():
    """Listen for P (pause), R (resume), S (stop) — works on Windows and POSIX."""
    if os.name == "nt":
        # Windows: use msvcrt for non-blocking key detection
        try:
            import msvcrt
        except ImportError:
            return
        while not _stop_flag.is_set():
            if msvcrt.kbhit():
                key = msvcrt.getch().decode("utf-8", errors="ignore").lower()
                _handle_key(key)
            threading.Event().wait(0.1)
    else:
        # POSIX (macOS / Linux): use select on stdin
        import select, tty, termios
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
        except Exception:
            return  # stdin is not a tty (e.g. piped) — skip keyboard listener
        try:
            tty.setraw(fd)
            while not _stop_flag.is_set():
                rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                if rlist:
                    key = sys.stdin.read(1).lower()
                    _handle_key(key)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _handle_key(key):
    if key == "p" and _pause_event.is_set():
        _pause_event.clear()
        cprint("\n[yellow]\u23f8 Paused \u2014 press R to resume, S to stop[/yellow]"
               if HAS_RICH else "\nPaused \u2014 press R to resume, S to stop")
    elif key == "r" and not _pause_event.is_set():
        _pause_event.set()
        cprint("[green]\u25b6 Resumed[/green]" if HAS_RICH else "Resumed")
    elif key == "s":
        _stop_flag.set()
        _pause_event.set()  # Unblock if paused
        cprint("[red]\u23f9 Stopping...[/red]" if HAS_RICH else "Stopping...")


# ── main run ──────────────────────────────────────────────────────────────────

def run(src, dst, opts, verbose=False, do_merge=True):
    global _pause_event, _stop_flag
    _pause_event = threading.Event()
    _pause_event.set()
    _stop_flag = threading.Event()

    if not os.path.isdir(src):
        cprint(f"[red]Error:[/red] not found: {src}")
        sys.exit(1)
    os.makedirs(dst, exist_ok=True)

    if opts.get("acoustid"):
        st, _ = fpcalc_status()
        if st == "missing":
            installed = _install_fingerprint_tool()
            if not installed:
                opts["acoustid"] = False
                cprint("[yellow]Continuing with basic metadata lookup only.[/yellow]"
                       if HAS_RICH else "Continuing with basic metadata lookup only.")

    if HAS_RICH:
        with Progress(SpinnerColumn(),
                      TextColumn("[cyan]Scanning for audio files\u2026"),
                      console=console, transient=True) as scan_prog:
            scan_prog.add_task("scan", total=None)
            mp3s = collect_mp3s(src)
    else:
        print("Scanning\u2026", end=" ", flush=True)
        mp3s = collect_mp3s(src)
        print(f"{len(mp3s)} files found")

    total = len(mp3s)
    if not total:
        cprint("[yellow]No supported audio files found.[/yellow]" if HAS_RICH
               else "No supported audio files found.")
        return

    cprint(f"\n[bold green]Found {total} audio files[/bold green]" if HAS_RICH
           else f"\nFound {total} audio files\n")

    stats = {"ok": 0, "skipped": 0, "errors": 0}
    rows  = []

    _SKIP = (" \u2713 MusicBrainz", " \u2713 AcoustID", " \u27f3", " \u26a0 AcoustID",
             " \u2717 Could not", " ! Tag", " [DRY]", " genres",
             " \U0001f5bc", " \u26a0 Album art")

    def log(msg):
        if not verbose and any(msg.startswith(p) for p in _SKIP):
            return
        if HAS_RICH: console.print(f" [dim]{msg}[/dim]")
        else:        print(f" {msg}")

    def src_label(source):
        return {"MusicBrainz": "online", "AcoustID": "online",
                "tags": "local tags"}.get(source, source)

    # Start keyboard listener for pause/resume
    kb_thread = threading.Thread(target=_check_keyboard, daemon=True)
    kb_thread.start()

    cprint("[dim]Press P to pause, R to resume, S to stop[/dim]" if HAS_RICH
           else "Press P to pause, R to resume, S to stop")

    if HAS_RICH:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=34),
            TextColumn("[cyan]{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as prog:
            task = prog.add_task("[cyan]Organizing\u2026", total=total)
            for i, path in enumerate(mp3s, 1):
                if _stop_flag.is_set():
                    cprint("\n[yellow]Stopped by user.[/yellow]" if HAS_RICH
                           else "\nStopped by user.")
                    break
                _pause_event.wait()  # Block while paused
                prog.update(task, description=f"[cyan]{os.path.basename(path)[:44]}")
                meta, source, status, dest = process_file(
                    path, dst, opts, stats, log_cb=log)
                rows.append((i,
                             (meta.get("artist", "") or "")[:20],
                             (meta.get("album",  "") or "")[:22],
                             meta.get("year",  ""),
                             meta.get("track", "").zfill(2) if meta.get("track") else "",
                             (meta.get("title", "") or "")[:26],
                             ", ".join(meta.get("genres", [])[:2])[:16],
                             src_label(source), status))
                prog.advance(task)
    else:
        for i, path in enumerate(mp3s, 1):
            if _stop_flag.is_set():
                print("\nStopped by user.")
                break
            _pause_event.wait()  # Block while paused
            print(f"[{i}/{total}] {os.path.basename(path)}")
            meta, source, status, dest = process_file(
                path, dst, opts, stats, log_cb=log)
            rows.append((i,
                         (meta.get("artist", "") or "")[:20],
                         (meta.get("album",  "") or "")[:22],
                         meta.get("year",  ""),
                         meta.get("track", "").zfill(2) if meta.get("track") else "",
                         (meta.get("title", "") or "")[:26],
                         ", ".join(meta.get("genres", [])[:2])[:16],
                         src_label(source), status))

    show_table(rows)

    if do_merge and not opts.get("dry_run"):
        cprint("\n[cyan]Merging duplicate album folders\u2026[/cyan]" if HAS_RICH
               else "\nMerging duplicate album folders\u2026")
        merge_duplicate_albums(dst, log_cb=lambda m: cprint(
            f" [dim]{m}[/dim]" if HAS_RICH else f" {m}"))

    show_summary(stats, dst)


# ── interactive mode ──────────────────────────────────────────────────────────

def interactive():
    if HAS_RICH:
        console.print(Panel.fit(
            "[bold cyan]\U0001f3b8 Music Organizer[/bold cyan]\n"
            "[dim]Organize your music library with online metadata[/dim]",
            border_style="cyan"))
        src       = Prompt.ask("[cyan]Source folder[/cyan]").strip()
        dst       = Prompt.ask("[cyan]Output folder[/cyan]", default=src).strip()
        copy      = Confirm.ask("Keep original files? (No = move them)", default=True)
        deep_meta = Confirm.ask("Use deep metadata lookup?",              default=True)
        wtags     = Confirm.ask("Save enriched tags to files?",           default=True)
        fetch_art = Confirm.ask("Download album art?",                    default=True)
        fetch_lyrics = Confirm.ask("Fetch lyrics?",                       default=True)
        over      = Confirm.ask("Overwrite existing files?",              default=False)
        dry       = Confirm.ask("Preview only? (no changes)",             default=False)
        do_merge  = Confirm.ask("Merge duplicate album folders?",         default=True)
        verbose   = Confirm.ask("Show detailed log?",                     default=False)
    else:
        print("=" * 52 + "\n \U0001f3b8 Music Organizer\n" + "=" * 52)
        src       = input("Source folder: ").strip()
        dst       = input(f"Output folder [{src}]: ").strip() or src
        copy      = input("Keep originals? [Y/n]: ").strip().lower() != "n"
        deep_meta = input("Deep metadata lookup? [Y/n]: ").strip().lower() != "n"
        wtags     = input("Save enriched tags? [Y/n]: ").strip().lower() != "n"
        fetch_art = input("Download album art? [Y/n]: ").strip().lower() != "n"
        fetch_lyrics = input("Fetch lyrics? [Y/n]: ").strip().lower() != "n"
        over      = input("Overwrite existing? [y/N]: ").strip().lower() == "y"
        dry       = input("Preview only? [y/N]: ").strip().lower() == "y"
        do_merge  = input("Merge duplicate albums? [Y/n]: ").strip().lower() != "n"
        verbose   = input("Detailed log? [y/N]: ").strip().lower() == "y"

    opts = {
        "copy": copy, "acoustid": deep_meta, "write_tags": wtags,
        "overwrite": over, "dry_run": dry,
        "fetch_art": fetch_art, "fetch_lyrics": fetch_lyrics,
        "overwrite_art": False,
    }
    run(src, dst, opts, verbose=verbose, do_merge=do_merge)


# ── CLI argument parser ───────────────────────────────────────────────────────

__version__ = "2.1.0"

def main():
    p = argparse.ArgumentParser(
        prog="music_organizer",
        description="\U0001f3b8 Music Organizer \u2014 organize your music library",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python music_organizer_cli.py
  python music_organizer_cli.py "D:/Music" "D:/Organized"
  python music_organizer_cli.py "D:/Music" "D:/Organized" --move --verbose
  python music_organizer_cli.py "D:/Music" "D:/Organized" --preview
  python music_organizer_cli.py "D:/Music" "D:/Organized" --no-art
""")
    p.add_argument("--version",     action="version", version=f"%(prog)s {__version__}")
    p.add_argument("source",        nargs="?", metavar="SOURCE")
    p.add_argument("output",        nargs="?", metavar="OUTPUT")
    p.add_argument("--move",        action="store_true", help="Move files instead of copying")
    p.add_argument("--no-deep",     action="store_true", help="Skip deep metadata lookup")
    p.add_argument("--no-tags",     action="store_true", help="Do not write tags back to files")
    p.add_argument("--no-art",      action="store_true", help="Skip album art download")
    p.add_argument("--no-lyrics",   action="store_true", help="Skip lyrics fetching")
    p.add_argument("--replace-art", action="store_true", help="Replace existing album art")
    p.add_argument("--overwrite",   action="store_true", help="Overwrite existing output files")
    p.add_argument("--preview",     action="store_true", help="Show what would happen without changes")
    p.add_argument("--no-merge",    action="store_true", help="Skip merging duplicate album folders")
    p.add_argument("--verbose", "-v", action="store_true", help="Show detailed processing log")
    p.add_argument("--install-deps", action="store_true", help="Install required Python packages")
    args = p.parse_args()

    if args.install_deps:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"])
        print("Done.")
        return

    if not args.source:
        interactive()
        return

    opts = {
        "copy":         not args.move,
        "acoustid":     not args.no_deep,
        "write_tags":   not args.no_tags,
        "overwrite":    args.overwrite,
        "dry_run":      args.preview,
        "fetch_art":    not args.no_art,
        "fetch_lyrics": not args.no_lyrics,
        "overwrite_art": args.replace_art,
    }
    run(args.source, args.output or args.source, opts,
        verbose=args.verbose, do_merge=not args.no_merge)


if __name__ == "__main__":
    main()
