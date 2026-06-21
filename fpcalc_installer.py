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
    system = platform.system()
    machine = platform.machine()
    key = (system, machine)
    url = FPCALC_URLS.get(key)
    if not url:
        for (s, m), u in FPCALC_URLS.items():
            if s == system:
                url = u
                break
    return url

def install_dir():
    return Path(sys.argv[0]).parent.resolve()

def fpcalc_target():
    fname = "fpcalc.exe" if platform.system() == "Windows" else "fpcalc"
    return install_dir() / fname

def download_fpcalc(progress_cb=None, done_cb=None, error_cb=None):
    def _run():
        try:
            url = get_download_url()
            if not url:
                raise RuntimeError(f"No fpcalc binary for {platform.system()} {platform.machine()}")
            with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "MusicOrganizer/1.0"}),
                timeout=30
            ) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                tmp   = tempfile.NamedTemporaryFile(delete=False, suffix=Path(url).suffix)
                downloaded = 0
                chunk = 8192
                while True:
                    data = resp.read(chunk)
                    if not data: break
                    tmp.write(data)
                    downloaded += len(data)
                    if progress_cb:
                        progress_cb(downloaded, total)
                tmp_path = tmp.name
                tmp.close()
            target = fpcalc_target()
            fname  = "fpcalc.exe" if platform.system() == "Windows" else "fpcalc"
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
