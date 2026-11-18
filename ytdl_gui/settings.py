"""User settings, stored as JSON in %APPDATA%\\YTDownloader\\settings.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "YT Downloader"
CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "YTDownloader"
CONFIG_FILE = CONFIG_DIR / "settings.json"


def default_download_dir() -> str:
    return str(Path.home() / "Downloads" / "YT Downloader")


@dataclass
class Settings:
    output_dir: str = field(default_factory=default_download_dir)
    mode: str = "mp4"              # mp4 | mp3 | both
    quality: str = "best"          # best | 2160 | 1440 | 1080 | 720 | 480 | 360
    max_parallel: int = 3
    watch_clipboard: bool = True
    compat_mode: bool = False      # force H.264/AAC (plays everywhere, max ~1080p)
    allow_hdr: bool = False        # off = prefer the SDR version at the same resolution
    mp3_quality: str = "320"       # 320 | 256 | 192 | 0 (VBR V0)
    embed_thumbnail: bool = True
    expand_playlists: bool = True
    auto_update: bool = True       # check for a newer yt-dlp in the background
    last_update_check: float = 0.0
    notify_when_done: bool = True  # flash the taskbar + chime when the queue finishes
    show_thumbnails: bool = True
    window_geometry: str = ""
    window_zoomed: bool = False

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in data.items() if k in known})
        s.max_parallel = max(1, min(8, int(s.max_parallel)))
        return s

    def save(self) -> None:
        _write_json(CONFIG_FILE, asdict(self))


QUEUE_FILE = CONFIG_DIR / "queue.json"


def load_queue() -> list[dict]:
    """Unfinished downloads saved when the app last closed."""
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        return [d for d in data if isinstance(d, dict) and d.get("url")]
    except (OSError, ValueError, TypeError):
        return []


def save_queue(items: list[dict]) -> None:
    _write_json(QUEUE_FILE, items)


def _write_json(path: Path, data) -> None:
    """Write atomically, so a crash mid-write can't leave a corrupt file."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass
