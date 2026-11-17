"""Locating external helper programs (FFmpeg, Deno) and updating yt-dlp."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

IS_WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder the app runs from (the repo root, or the folder of the .exe)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", app_dir()))
    return base.joinpath(*parts)


def _registry_path_dirs() -> list[str]:
    """PATH as currently stored in the registry.

    Tools installed after this process started (e.g. by setup.bat) are on the
    registry PATH but not yet on os.environ["PATH"].
    """
    if not IS_WINDOWS:
        return []
    import winreg

    dirs: list[str] = []
    keys = (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    )
    for root, sub in keys:
        try:
            with winreg.OpenKey(root, sub) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
                dirs += os.path.expandvars(value).split(os.pathsep)
        except OSError:
            pass
    return [d for d in dirs if d]


@lru_cache(maxsize=None)
def find_tool(name: str) -> str | None:
    """Return the full path of an executable, or None when it isn't installed."""
    exe = name + (".exe" if IS_WINDOWS else "")
    for folder in (app_dir() / "bin", app_dir()):
        candidate = folder / exe
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name) or shutil.which(name, path=os.pathsep.join(_registry_path_dirs()))
    if found:
        # winget installs aliases (symlinks); resolve so ffprobe is found next to ffmpeg.
        return os.path.realpath(found)
    return None


def ffmpeg_path() -> str | None:
    return find_tool("ffmpeg")


def deno_path() -> str | None:
    return find_tool("deno")


def ytdlp_version() -> str:
    try:
        from yt_dlp.version import __version__

        return __version__
    except Exception:
        return "?"


def can_self_update() -> bool:
    return not is_frozen()


def update_ytdlp() -> tuple[bool, str]:
    """Upgrade yt-dlp with pip. Takes effect the next time the app starts."""
    if not can_self_update():
        return False, "Updating isn't available in the .exe build. Download a newer release instead."
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "--disable-pip-version-check", "yt-dlp[default]"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, creationflags=NO_WINDOW)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "pip failed").strip().splitlines()[-1]
    out = subprocess.run(
        [sys.executable, "-c", "from yt_dlp.version import __version__ as v; print(v)"],
        capture_output=True, text=True, creationflags=NO_WINDOW,
    ).stdout.strip()
    return True, out or "updated"


def open_folder(path: str | Path, select_file: str | None = None) -> None:
    path = str(path)
    if IS_WINDOWS:
        if select_file and os.path.exists(select_file):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(select_file)])
        else:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def hide_folder(path: Path) -> None:
    if IS_WINDOWS:
        try:
            import ctypes

            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)  # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            pass
