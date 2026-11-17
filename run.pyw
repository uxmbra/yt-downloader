"""Double-click launcher (no console window). Also the PyInstaller entry point."""
import os
import sys
import traceback

# Without a console (pythonw / windowed .exe) stdout and stderr are None,
# and libraries that write to them would crash.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))


def _crash(exc: BaseException) -> None:
    log_dir = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "YTDownloader")
    os.makedirs(log_dir, exist_ok=True)
    log = os.path.join(log_dir, "crash.log")
    with open(log, "w", encoding="utf-8") as fh:
        fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    try:
        from tkinter import Tk, messagebox

        root = Tk()
        root.withdraw()
        messagebox.showerror("YT Downloader", f"YT Downloader couldn't start:\n\n{exc}\n\nDetails: {log}")
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        from ytdl_gui.gui import main

        main()
    except Exception as exc:  # noqa: BLE001
        _crash(exc)
        raise
