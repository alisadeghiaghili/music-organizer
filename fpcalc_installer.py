#!/usr/bin/env python3
"""fpcalc_installer.py — silent background downloader for fpcalc binary"""

import os, sys, platform, zipfile, tarfile, tempfile, shutil, threading
import urllib.request
from pathlib import Path

FPCALC_URLS = {
    ("Windows", "AMD64"):  "https://acoustid.org/files/chromaprint/chromaprint-fpcalc-1.6.0-windows-x86_64.zip",
    ("Windows", "x86"):    "https://acoustid.org/files/chromaprint/chromaprint-fpcalc-1.6.0-windows-x86_64.zip",
    ("Darwin",  "arm64"):  "https://acoustid.org/files/chromaprint/chromaprint-fpcalc-1.6.0-macos-arm64.tar.gz",
    ("Darwin",  "x86_64"): "https://acoustid.org/files/chromaprint/chromaprint-fpcalc-1.6.0-macos-x86_64.tar.gz",
    ("Linux",   "aarch64"):"https://acoustid.org/files/chromaprint/chromaprint-fpcalc-1.6.0-linux-arm64.tar.gz",
    ("Linux",   "x86_64"): "https://acoustid.org/files/chromaprint/chromaprint-fpcalc-1.6.0-linux-x86_64.tar.gz",
}


def get_download_url():
    system  = platform.system()
    machine = platform.machine()
    url = FPCALC_URLS.get((system, machine))
    if not url:
        for (s, _), u in FPCALC_URLS.items():
            if s == system:
                url = u
                break
    return url


def install_dir():
    """
    Returns the folder that contains the running exe (or script).
    Works correctly both when running as a PyInstaller onefile exe
    and when running as a plain .py script.
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller sets sys.executable to the actual .exe path
        return Path(sys.executable).parent.resolve()
    # Normal script execution
    return Path(sys.argv[0]).parent.resolve()


def fpcalc_target():
    fname = "fpcalc.exe" if platform.system() == "Windows" else "fpcalc"
    return install_dir() / fname


def download_fpcalc(progress_cb=None, done_cb=None, error_cb=None):
    def _run():
        try:
            url = get_download_url()
            if not url:
                raise RuntimeError(
                    f"No fpcalc binary available for "
                    f"{platform.system()} {platform.machine()}"
                )

            req = urllib.request.Request(
                url, headers={"User-Agent": "MusicOrganizer/1.0"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                total      = int(resp.headers.get("Content-Length", 0))
                suffix     = Path(url).suffix  # .zip or .gz
                tmp        = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                downloaded = 0
                while True:
                    data = resp.read(8192)
                    if not data:
                        break
                    tmp.write(data)
                    downloaded += len(data)
                    if progress_cb:
                        progress_cb(downloaded, total)
                tmp_path = tmp.name
                tmp.close()

            target = fpcalc_target()
            fname  = "fpcalc.exe" if platform.system() == "Windows" else "fpcalc"

            # Extract fpcalc binary from archive
            if tmp_path.endswith(".zip"):
                with zipfile.ZipFile(tmp_path) as z:
                    for name in z.namelist():
                        if name.endswith(fname):
                            with z.open(name) as src, open(target, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            break
            else:
                with tarfile.open(tmp_path) as t:
                    for member in t.getmembers():
                        if member.name.endswith(fname):
                            f = t.extractfile(member)
                            if f:
                                with open(target, "wb") as dst:
                                    shutil.copyfileobj(f, dst)
                            break

            os.unlink(tmp_path)

            if platform.system() != "Windows":
                target.chmod(0o755)

            if done_cb:
                done_cb(str(target))

        except Exception as e:
            if error_cb:
                error_cb(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
