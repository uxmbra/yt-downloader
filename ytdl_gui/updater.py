"""Keeps the yt-dlp engine up to date, from source *and* in the .exe.

YouTube changes often and older yt-dlp versions stop working. Updates are the
official yt-dlp release in its "zipimport" form (one file holding yt-dlp and
its YouTube challenge-solver scripts), checked against the SHA-256 sums that
yt-dlp publishes with every release, and saved to
%APPDATA%\\YTDownloader\\engine. At startup `activate()` puts the newest one
first on sys.path, before anything imports yt_dlp.

This module must not import yt_dlp at module level.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import ssl
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .settings import CONFIG_DIR

ENGINE_DIR = CONFIG_DIR / "engine"
RELEASE_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
ASSET = "yt-dlp"            # the zipimport build (works on any OS with Python)
SUMS_ASSET = "SHA2-256SUMS"
USER_AGENT = "YT-Downloader-updater"
_FILE_RE = re.compile(r"^yt-dlp-([\d.]+)\.zip$")

_active_version: str | None = None   # engine loaded from ENGINE_DIR this session, if any


def vtuple(version: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version or ""))


def bundled_version() -> str:
    """yt-dlp version installed with the app (pip package or bundled in the .exe)."""
    try:
        from importlib.metadata import version

        return version("yt-dlp")
    except Exception:
        return "0"


def _staged() -> list[tuple[tuple[int, ...], str, Path]]:
    """Downloaded engines, oldest first."""
    found = []
    if ENGINE_DIR.is_dir():
        for p in ENGINE_DIR.iterdir():
            if m := _FILE_RE.match(p.name):
                found.append((vtuple(m.group(1)), m.group(1), p))
    return sorted(found)


def _purge_modules() -> None:
    for name in list(sys.modules):
        if name == "yt_dlp" or name.startswith(("yt_dlp.", "yt_dlp_ejs")):
            del sys.modules[name]


def activate() -> None:
    """Load the newest downloaded engine if it's newer than the bundled one."""
    global _active_version
    if os.environ.get("YTDL_NO_ENGINE_UPDATE"):
        return
    base = vtuple(bundled_version())
    for vt, ver, path in reversed(_staged()):
        if vt <= base:
            _remove(path)  # an app update brought a newer yt-dlp than this download
            continue
        if _active_version:
            _remove(path)  # older than the one already loaded
            continue
        sys.path.insert(0, str(path))
        try:
            import yt_dlp.version as v

            if v.__version__ != ver:
                raise ImportError(f"expected {ver}, got {v.__version__}")
            _active_version = ver
        except Exception:
            sys.path.remove(str(path))
            _purge_modules()
            _remove(path)


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def active_version() -> str:
    try:
        from yt_dlp.version import __version__

        return __version__
    except Exception:
        return _active_version or bundled_version()


def staged_version() -> str | None:
    """A downloaded engine that will be used after the next restart, if any."""
    files = _staged()
    if files and files[-1][0] > vtuple(active_version()):
        return files[-1][1]
    return None


# ------------------------------------------------------------------ network

def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _get(url: str, progress: Callable[[float], None] | None = None, accept: str | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        while chunk := resp.read(65536):
            buf.write(chunk)
            if progress and total:
                progress(buf.tell() / total)
        return buf.getvalue()


@dataclass
class UpdateResult:
    status: str        # "up_to_date" | "ready" (restart to use) | "error"
    version: str = ""
    message: str = ""


def check_and_download(progress: Callable[[float], None] | None = None) -> UpdateResult:
    """Fetch the latest yt-dlp release if it's newer than what we have. Never raises."""
    try:
        release = json.loads(_get(RELEASE_API, accept="application/vnd.github+json"))
        latest = release["tag_name"]
        have = max(vtuple(active_version()), vtuple(staged_version()))
        if vtuple(latest) <= have:
            if staged_version():
                return UpdateResult("ready", staged_version(), "Restart to finish updating.")
            return UpdateResult("up_to_date", active_version())

        assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
        if ASSET not in assets or SUMS_ASSET not in assets:
            return UpdateResult("error", latest, "The release is missing its files. Try again later.")
        sums = _get(assets[SUMS_ASSET]).decode("utf-8", "replace")
        expected = next((ln.split()[0].lower() for ln in sums.splitlines()
                         if ln.split()[1:] == [ASSET]), None)
        data = _get(assets[ASSET], progress)
        if not expected or hashlib.sha256(data).hexdigest() != expected:
            return UpdateResult("error", latest, "Download didn't match its checksum, so it was discarded.")

        # Sanity-check it really is yt-dlp <latest>.
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            version_py = zf.read("yt_dlp/version.py").decode("utf-8", "replace")
        if f"__version__ = '{latest}'" not in version_py:
            return UpdateResult("error", latest, "Downloaded file has an unexpected version.")

        ENGINE_DIR.mkdir(parents=True, exist_ok=True)
        target = ENGINE_DIR / f"yt-dlp-{latest}.zip"
        tmp = target.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return UpdateResult("ready", latest, "Restart to finish updating.")
    except Exception as exc:  # noqa: BLE001 - offline, rate-limited, etc.
        return UpdateResult("error", "", f"Couldn't check for updates ({type(exc).__name__}).")


def restart_command() -> list[str]:
    """Command that starts this app again (used after an update)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--restarted"]
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    launcher = Path(__file__).resolve().parent.parent / "run.pyw"
    return [str(pythonw if pythonw.exists() else exe), str(launcher), "--restarted"]
