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


def flash_taskbar(window) -> None:
    """Flash the taskbar button until the window is focused (Windows)."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                        ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]

        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        # FLASHW_TRAY | FLASHW_TIMERNOFG: flash until the window comes to the foreground
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x02 | 0x0C, 0, 0)
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass


def is_foreground(window) -> bool:
    """Is this window the one the user is currently using?"""
    if not IS_WINDOWS:
        return window.focus_displayof() is not None
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        return ctypes.windll.user32.GetForegroundWindow() == hwnd
    except Exception:
        return True


def chime() -> None:
    if IS_WINDOWS:
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass


def open_file(path: str) -> bool:
    if not path or not os.path.exists(path):
        return False
    if IS_WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return True


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
