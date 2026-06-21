#!/usr/bin/env python3
"""
music_organizer_cli.py — CLI frontend with fpcalc auto-installer
Usage: python music_organizer_cli.py [SOURCE] [OUTPUT] [OPTIONS]
       python music_organizer_cli.py              (interactive)
"""

import os, sys, argparse, threading
from music_core import collect_mp3s, process_file, merge_duplicate_albums, fpcalc_status
from fpcalc_installer import download_fpcalc

try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import (Progress, SpinnerColumn, BarColumn,
                                TextColumn, TimeElapsedColumn, DownloadColumn)
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None


def cprint(msg, style=""):
    if HAS_RICH: console.print(msg, style=style)
    else: print(msg)


def install_fpcalc_cli():
    if HAS_RICH:
        console.print(Panel(
            "[yellow]⚠  fpcalc not found — AcoustID fingerprinting disabled.[/yellow]\n"
            "[dim]fpcalc is a small ~2MB binary needed for audio fingerprinting.[/dim]",
            border_style="yellow", title="AcoustID unavailable"))
        if not Confirm.ask("Download and install fpcalc automatically?", default=True):
            return False
    else:
        print("\n⚠  fpcalc not found.")
        ans = input("Download and install fpcalc automatically? [Y/n]: ").strip().lower()
        if ans == "n":
            return False

    done_event = threading.Event()
    result     = {"path": None, "error": None}

    if HAS_RICH:
        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]Downloading fpcalc…"),
            BarColumn(bar_width=30),
            TextColumn("[cyan]{task.percentage:>3.0f}%"),
            DownloadColumn(),
            console=console,
            transient=False,
        ) as prog:
            task = prog.add_task("download", total=100)

            def on_progress(dl, total):
                if total > 0:
                    prog.update(task, completed=int(dl/total*100), total=100)

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
        print("Downloading fpcalc…")

        def on_progress(dl, total):
            if total > 0:
                pct = int(dl/total*100)
                bar = "█" * (pct//5) + "░" * (20 - pct//5)
                print(f"\r  [{bar}] {pct}%  {dl//1024}KB/{total//1024}KB", end="", flush=True)

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
        cprint(f"[red]Download failed:[/red] {result['error']}" if HAS_RICH
               else f"Download failed: {result['error']}")
        return False

    cprint(f"[green]✓ fpcalc installed:[/green] {result['path']}" if HAS_RICH
           else f"✓ fpcalc installed: {result['path']}")
    return True


def show_table(rows):
    if not HAS_RICH:
        for r in rows: print(" | ".join(str(x) for x in r))
        return
    t = Table(box=box.SIMPLE_HEAD, header_style="bold cyan", border_style="dim")
    for col,w in [("#",4),("Artist",20),("Album",22),("Yr",5),("Trk",4),
                  ("Title",26),("Source",12),("Status",8)]:
        t.add_column(col, width=w)
    ST = {"ok":"green","skipped":"yellow","error":"red","dry-run":"cyan"}
    for r in rows:
        st = r[-1]; col = ST.get(st,"white")
        t.add_row(*[str(x) for x in r[:-1]], f"[{col}]{st}[/{col}]")
    console.print(t)


def show_summary(stats, dst):
    if HAS_RICH:
        console.print(Panel(
            f"[green]✓ Organized:[/green]  {stats['ok']}\n"
            f"[yellow]↷ Skipped:[/yellow]   {stats['skipped']}\n"
            f"[red]✗ Errors:[/red]    {stats['errors']}\n\n"
            f"[dim]Output → {dst}[/dim]",
            title="[bold]Done[/bold]", border_style="green"))
    else:
        print(f"\nDone — OK:{stats['ok']}  Skipped:{stats['skipped']}  Errors:{stats['errors']}")


def run(src, dst, opts, verbose=False, do_merge=True):
    if not os.path.isdir(src):
        cprint(f"[red]Error:[/red] not found: {src}"); sys.exit(1)
    os.makedirs(dst, exist_ok=True)

    if opts.get("acoustid"):
        st, _ = fpcalc_status()
        if st == "missing":
            installed = install_fpcalc_cli()
            if not installed:
                opts["acoustid"] = False
                cprint("[yellow]Continuing without AcoustID.[/yellow]" if HAS_RICH
                       else "Continuing without AcoustID.")

    mp3s  = collect_mp3s(src); total = len(mp3s)
    if not total: cprint("[yellow]No MP3 files found.[/yellow]"); return

    cprint(f"\n[bold green]Found {total} MP3 files[/bold green]" if HAS_RICH
           else f"\nFound {total} MP3 files\n")

    stats = {"ok":0,"skipped":0,"errors":0}
    rows  = []

    def log(msg):
        if verbose: cprint(f"  [dim]{msg}[/dim]" if HAS_RICH else f"  {msg}")

    if HAS_RICH:
        with Progress(SpinnerColumn(),
                      TextColumn("[progress.description]{task.description}"),
                      BarColumn(bar_width=32),
                      TextColumn("[cyan]{task.completed}/{task.total}"),
                      TimeElapsedColumn(), console=console) as prog:
            task = prog.add_task("[cyan]Organizing…", total=total)
            for i,path in enumerate(mp3s,1):
                prog.update(task, description=f"[cyan]{os.path.basename(path)[:42]}")
                meta,source,status,dest = process_file(path,dst,opts,stats,log_cb=log)
                rows.append((i,
                    (meta.get("artist","") or "")[:20],
                    (meta.get("album","")  or "")[:22],
                    meta.get("year",""),
                    meta.get("track","").zfill(2) if meta.get("track") else "",
                    (meta.get("title","")  or "")[:26],
                    source, status))
                prog.advance(task)
    else:
        for i,path in enumerate(mp3s,1):
            print(f"[{i}/{total}] {os.path.basename(path)}")
            meta,source,status,dest = process_file(path,dst,opts,stats,log_cb=log)
            rows.append((i,
                (meta.get("artist","") or "")[:20],
                (meta.get("album","")  or "")[:22],
                meta.get("year",""),
                meta.get("track","").zfill(2) if meta.get("track") else "",
                (meta.get("title","")  or "")[:26],
                source, status))

    show_table(rows)

    if do_merge and not opts.get("dry_run"):
        cprint("\n[cyan]🔀 Merging duplicate album folders…[/cyan]" if HAS_RICH
               else "\nMerging duplicate album folders…")
        merge_duplicate_albums(dst, log_cb=lambda m: cprint(
            f"  [dim]{m}[/dim]" if HAS_RICH else f"  {m}"))

    show_summary(stats, dst)


def interactive():
    if HAS_RICH:
        console.print(Panel.fit(
            "[bold cyan]🎸 Music Organizer CLI[/bold cyan]\n"
            "[dim]Organize your MP3 archive with MusicBrainz + AcoustID[/dim]",
            border_style="cyan"))
        src      = Prompt.ask("[cyan]Source folder[/cyan]").strip()
        dst      = Prompt.ask("[cyan]Output folder[/cyan]", default=src).strip()
        copy     = Confirm.ask("Copy files? (No = move)",            default=True)
        acoust   = Confirm.ask("Use AcoustID fingerprint fallback?", default=True)
        wtags    = Confirm.ask("Write enriched tags back?",          default=True)
        over     = Confirm.ask("Overwrite existing?",                default=False)
        dry      = Confirm.ask("Dry run? (preview, no changes)",     default=False)
        do_merge = Confirm.ask("Merge duplicate album folders?",     default=True)
        verbose  = Confirm.ask("Verbose log?",                       default=False)
    else:
        print("=" * 52 + "\n  🎸 Music Organizer CLI\n" + "=" * 52)
        src      = input("Source folder: ").strip()
        dst      = input(f"Output folder [{src}]: ").strip() or src
        copy     = input("Copy files? [Y/n]: ").strip().lower()        != "n"
        acoust   = input("AcoustID fallback? [Y/n]: ").strip().lower() != "n"
        wtags    = input("Write tags back? [Y/n]: ").strip().lower()   != "n"
        over     = input("Overwrite existing? [y/N]: ").strip().lower() == "y"
        dry      = input("Dry run? [y/N]: ").strip().lower()            == "y"
        do_merge = input("Merge duplicate albums? [Y/n]: ").strip().lower() != "n"
        verbose  = input("Verbose log? [y/N]: ").strip().lower()        == "y"

    opts = {"copy":copy,"acoustid":acoust,"write_tags":wtags,"overwrite":over,"dry_run":dry}
    run(src, dst, opts, verbose=verbose, do_merge=do_merge)


def main():
    p = argparse.ArgumentParser(
        prog="music_organizer_cli",
        description="🎸 Music Organizer — organize MP3s via MusicBrainz + AcoustID",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python music_organizer_cli.py
  python music_organizer_cli.py "D:/Music" "D:/Out"
  python music_organizer_cli.py "D:/Music" "D:/Out" --move --verbose
  python music_organizer_cli.py "D:/Music" "D:/Out" --dry-run
  python music_organizer_cli.py "D:/Music" "D:/Out" --no-merge
""")
    p.add_argument("source",          nargs="?")
    p.add_argument("output",          nargs="?")
    p.add_argument("--move",          action="store_true")
    p.add_argument("--no-acoustid",   action="store_true")
    p.add_argument("--no-tags",       action="store_true")
    p.add_argument("--overwrite",     action="store_true")
    p.add_argument("--dry-run",       action="store_true")
    p.add_argument("--no-merge",      action="store_true")
    p.add_argument("--verbose","-v",  action="store_true")
    p.add_argument("--install-deps",  action="store_true")
    args = p.parse_args()

    if args.install_deps:
        import subprocess
        subprocess.check_call([sys.executable,"-m","pip","install","mutagen","rich","-q"])
        print("Done."); return

    if not args.source:
        interactive(); return

    opts = {"copy": not args.move, "acoustid": not args.no_acoustid,
            "write_tags": not args.no_tags, "overwrite": args.overwrite,
            "dry_run": args.dry_run}
    run(args.source, args.output or args.source, opts,
        verbose=args.verbose, do_merge=not args.no_merge)


if __name__ == "__main__":
    main()
