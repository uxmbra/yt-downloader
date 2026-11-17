"""Download queue built on yt-dlp. No GUI code in here.

Worker threads update Job objects and call `notify(job)`; the GUI decides how
to marshal that back onto its own thread.
"""
from __future__ import annotations

import itertools
import re
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.postprocessor import EmbedThumbnailPP, FFmpegExtractAudioPP
from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.utils import DownloadCancelled

from . import tools

PARTIAL_DIR = ".ytdl-partial"


class Status(str, Enum):
    QUEUED = "Queued"
    STARTING = "Starting"
    DOWNLOADING = "Downloading"
    PROCESSING = "Processing"
    DONE = "Done"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


ACTIVE = {Status.STARTING, Status.DOWNLOADING, Status.PROCESSING}
FINISHED = {Status.DONE, Status.FAILED, Status.CANCELLED}


# --------------------------------------------------------------------- URLs

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_YT_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")


def extract_urls(text: str) -> list[str]:
    """All http(s) links in a blob of text, in order, without duplicates."""
    seen: dict[str, None] = {}
    for m in _URL_RE.finditer(text or ""):
        seen.setdefault(m.group(0).rstrip(").,;]}>"), None)
    return list(seen)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_youtube_url(url: str) -> bool:
    host = _host(url)
    return any(host == h or host.endswith("." + h) for h in _YT_HOSTS)


def youtube_video_id(url: str) -> str | None:
    if not is_youtube_url(url):
        return None
    p = urlparse(url)
    if _host(url).endswith("youtu.be"):
        return p.path.strip("/").split("/")[0] or None
    if "v" in (q := parse_qs(p.query)):
        return q["v"][0]
    m = re.match(r"^/(?:shorts|live|embed|v)/([\w-]{11})", p.path)
    return m.group(1) if m else None


def is_collection_url(url: str) -> bool:
    """Playlist / channel links, which expand into one queue item per video."""
    if not is_youtube_url(url) or youtube_video_id(url):
        return False
    path = urlparse(url).path
    return path.startswith(("/playlist", "/@", "/channel/", "/c/", "/user/"))


def dedupe_key(url: str) -> str:
    vid = youtube_video_id(url)
    return f"yt:{vid}" if vid else url.strip()


# --------------------------------------------------------------------- jobs

_ids = itertools.count(1)


@dataclass
class JobOptions:
    mode: str = "mp4"            # mp4 | mp3 | both
    quality: str = "best"        # best or a max height like "1080"
    output_dir: str = "."
    compat: bool = False
    allow_hdr: bool = False
    mp3_quality: str = "320"
    embed_thumbnail: bool = True


@dataclass
class Job:
    url: str
    opts: JobOptions
    title: str = ""
    id: int = field(default_factory=lambda: next(_ids))
    status: Status = Status.QUEUED
    progress: float = 0.0              # 0..1
    speed: float | None = None         # bytes/s
    eta: float | None = None           # seconds
    total_bytes: float = 0
    detail: str = ""
    error: str = ""
    filepath: str = ""
    resolution: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def display_title(self) -> str:
        return self.title or self.url

    @property
    def key(self) -> str:
        return dedupe_key(self.url)


class _Logger:
    """Collects yt-dlp's messages instead of printing them."""

    def __init__(self) -> None:
        self.last_error = ""

    def debug(self, msg: str) -> None:
        pass

    info = debug

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        self.last_error = msg


class _InfoGrabber(PostProcessor):
    """Runs right after extraction, before downloading: gives us the title early."""

    def __init__(self, callback: Callable[[dict], None]) -> None:
        super().__init__(None)
        self._callback = callback

    def run(self, info):
        self._callback(info)
        return [], info


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def clean_error(msg: str) -> str:
    msg = _ANSI_RE.sub("", str(msg)).strip()
    msg = re.sub(r"^ERROR:\s*", "", msg)
    msg = re.sub(r"^\[[\w:]+\]\s*[\w-]+:\s*", "", msg)  # "[youtube] abc123: "
    hints = {
        "Sign in to confirm your age": "Age-restricted video: YouTube requires sign-in.",
        "Private video": "This video is private.",
        "Video unavailable": "Video unavailable (removed, private or region-blocked).",
        "ffmpeg not found": "FFmpeg is missing. Run setup.bat to install it.",
        "Sign in to confirm you": "YouTube is asking for sign-in (bot check). Try again later or update yt-dlp in Settings.",
    }
    for needle, nice in hints.items():
        if needle.lower() in msg.lower():
            return nice
    return msg.splitlines()[0][:300] if msg else "Unknown error"


# ------------------------------------------------------------------ manager

class DownloadManager:
    def __init__(self, notify: Callable[[Job], None], max_parallel: int = 3) -> None:
        self._notify = notify
        self._lock = threading.Lock()
        self._pending: deque[Job] = deque()
        self._running: set[int] = set()
        self._max_parallel = max_parallel

    # ---- queue control
    @property
    def max_parallel(self) -> int:
        return self._max_parallel

    def set_max_parallel(self, n: int) -> None:
        with self._lock:
            self._max_parallel = max(1, int(n))
            self._pump()

    def submit(self, job: Job) -> None:
        with self._lock:
            job.status = Status.QUEUED
            self._pending.append(job)
            self._pump()
        self._notify(job)

    def retry(self, job: Job) -> None:
        job.cancel_event = threading.Event()
        job.progress, job.speed, job.eta = 0.0, None, None
        job.error = job.detail = ""
        self.submit(job)

    def cancel(self, job: Job) -> None:
        job.cancel_event.set()
        with self._lock:
            if job in self._pending:
                self._pending.remove(job)
                job.status = Status.CANCELLED
            else:
                job.detail = "Cancelling…" if job.status in ACTIVE else job.detail
        self._notify(job)

    def counts(self) -> tuple[int, int]:
        with self._lock:
            return len(self._running), len(self._pending)

    def _pump(self) -> None:  # caller holds the lock
        while self._pending and len(self._running) < self._max_parallel:
            job = self._pending.popleft()
            self._running.add(job.id)
            job.status = Status.STARTING
            threading.Thread(target=self._run, args=(job,), name=f"job-{job.id}", daemon=True).start()

    def _run(self, job: Job) -> None:
        try:
            self._download(job)
        finally:
            with self._lock:
                self._running.discard(job.id)
                self._pump()
            self._notify(job)

    # ---- playlist / channel expansion
    @staticmethod
    def expand(url: str) -> list[tuple[str, str]]:
        """Return (url, title) for every video in a playlist or channel link."""
        opts = {
            **_base_options(_Logger()),
            "extract_flat": "in_playlist",
            "skip_download": True,
            "noplaylist": False,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            out: list[tuple[str, str]] = []

            def walk(node: dict, depth: int) -> None:
                for entry in node.get("entries") or []:
                    if not entry:
                        continue
                    if entry.get("_type") == "playlist" or (
                        entry.get("ie_key") == "YoutubeTab" and depth < 2
                    ):
                        sub = entry if entry.get("entries") is not None else ydl.extract_info(
                            entry["url"], download=False
                        )
                        walk(sub, depth + 1)
                    elif entry.get("url") or entry.get("id"):
                        link = entry.get("url") or f"https://www.youtube.com/watch?v={entry['id']}"
                        out.append((link, entry.get("title") or ""))

            if info.get("entries") is None:
                return [(url, info.get("title") or "")]
            walk(info, 0)
            return out

    # ---- the download itself
    def _download(self, job: Job) -> None:
        if job.cancel_event.is_set():
            job.status = Status.CANCELLED
            return
        o = job.opts
        job.detail = "Fetching video info…"
        self._notify(job)

        out_dir = Path(o.output_dir)
        partial_root = out_dir / PARTIAL_DIR
        tmp = partial_root / f"job{job.id}-{int(time.time() * 1000)}"
        logger = _Logger()
        last_ping = [0.0]

        def ping(force: bool = False) -> None:
            now = time.monotonic()
            if force or now - last_ping[0] >= 0.2:
                last_ping[0] = now
                self._notify(job)

        def on_info(info: dict) -> None:
            job.title = info.get("title") or job.title
            if info.get("height") and o.mode != "mp3":
                job.resolution = f"{info['height']}p"
                if info.get("fps") and info["fps"] > 30:
                    job.resolution += f"{round(info['fps'])}"
            ping(True)

        def on_progress(d: dict) -> None:
            if job.cancel_event.is_set():
                raise DownloadCancelled("Cancelled by user")
            info = d.get("info_dict") or {}
            if d["status"] == "downloading":
                job.status = Status.DOWNLOADING
                done = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                frac = done / total if total else 0.0
                # Video and audio download one after another: show combined progress.
                fmts = info.get("requested_formats") or []
                if len(fmts) > 1:
                    idx = next((i for i, f in enumerate(fmts) if f.get("format_id") == info.get("format_id")), 0)
                    sizes = [f.get("filesize") or f.get("filesize_approx") or 0 for f in fmts]
                    if all(sizes):
                        sizes[idx] = total or sizes[idx]
                        job.total_bytes = sum(sizes)
                        job.progress = (sum(sizes[:idx]) + done) / job.total_bytes
                    else:
                        job.progress = (idx + frac) / len(fmts)
                    part = "video" if info.get("vcodec") not in (None, "none") else "audio"
                    job.detail = f"Downloading {part}"
                else:
                    job.total_bytes = total
                    job.progress = frac
                    job.detail = "Downloading"
                job.progress = min(job.progress, 1.0)
                job.speed = d.get("speed")
                job.eta = d.get("eta")
                ping()
            elif d["status"] == "finished":
                job.speed = job.eta = None
                ping(True)

        pp_names = {
            "Merger": "Merging video + audio",
            "ExtractAudio": "Converting to MP3",
            "EmbedThumbnail": "Adding cover art",
            "Metadata": "Writing tags",
            "MoveFiles": "Finishing",
        }

        def on_postprocess(d: dict) -> None:
            if d["status"] == "started" and d.get("postprocessor") != _InfoGrabber.pp_key():
                job.status = Status.PROCESSING
                job.progress = 1.0
                job.speed = job.eta = None
                job.detail = pp_names.get(d.get("postprocessor", ""), "Processing")
                ping(True)

        try:
            opts, late_pps = _build_options(o, tmp, logger, on_progress, on_postprocess)
            if not partial_root.exists():
                partial_root.mkdir(parents=True, exist_ok=True)
                tools.hide_folder(partial_root)
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.add_post_processor(_InfoGrabber(on_info), when="before_dl")
                for make_pp in late_pps:
                    ydl.add_post_processor(make_pp(ydl), when="post_process")
                info = ydl.extract_info(job.url, download=True)
            if job.cancel_event.is_set():
                raise DownloadCancelled()
            downloads = (info or {}).get("requested_downloads") or []
            job.filepath = downloads[-1].get("filepath", "") if downloads else ""
            job.title = (info or {}).get("title") or job.title
            job.status, job.progress, job.detail = Status.DONE, 1.0, ""
        except DownloadCancelled:
            job.status, job.detail = Status.CANCELLED, ""
        except Exception as exc:  # noqa: BLE001 - any failure ends the job
            if job.cancel_event.is_set():
                job.status, job.detail = Status.CANCELLED, ""
            else:
                job.status = Status.FAILED
                job.error = clean_error(logger.last_error or str(exc))
                job.detail = ""
        finally:
            job.speed = job.eta = None
            shutil.rmtree(tmp, ignore_errors=True)
            try:
                partial_root.rmdir()  # only succeeds when no other job is using it
            except OSError:
                pass


def _base_options(logger: _Logger) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": logger,
        "noplaylist": True,
        "windowsfilenames": True,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "socket_timeout": 30,
    }
    if deno := tools.deno_path():
        opts["js_runtimes"] = {"deno": {"path": deno}}
    if ffmpeg := tools.ffmpeg_path():
        opts["ffmpeg_location"] = ffmpeg
    return opts


class _ExtractAudioKeepSource(FFmpegExtractAudioPP):
    """Extract audio but keep the source video (moved to the output folder too)."""

    def run(self, info):
        src = info["filepath"]
        to_delete, info = super().run(info)
        if src in to_delete:
            to_delete = [f for f in to_delete if f != src]
            info.setdefault("__files_to_move", {})[src] = ""
        return to_delete, info


def _build_options(o: JobOptions, tmp: Path, logger: _Logger, on_progress, on_postprocess):
    """Returns (yt-dlp params, post-processor factories to add after the params' own)."""
    has_ffmpeg = tools.ffmpeg_path() is not None
    late: list[Callable] = []
    opts = _base_options(logger)
    opts.update({
        "paths": {"home": o.output_dir, "temp": str(tmp)},
        "outtmpl": {"default": "%(title).180B.%(ext)s"},
        "progress_hooks": [on_progress],
        "postprocessor_hooks": [on_postprocess],
    })
    pps: list[dict] = []
    thumb = o.embed_thumbnail and has_ffmpeg

    if o.mode in ("mp4", "both"):
        h = None if o.quality == "best" else int(o.quality)
        cap = f"[height<={h}]" if h else ""
        if has_ffmpeg:
            # Best video stream + best audio stream, merged into one .mp4
            opts["format"] = f"bv{cap}+ba/b{cap}/bv+ba/b"
            opts["merge_output_format"] = "mp4"
        else:
            opts["format"] = f"b{cap}[ext=mp4]/b{cap}/b"
        if o.compat:
            opts["format_sort"] = ["vcodec:h264", "res", "fps", "acodec:aac"]
        elif not o.allow_hdr:
            # Same top resolution/fps, but SDR: HDR looks washed out on most screens/players.
            opts["format_sort"] = ["res", "fps", "hdr:sdr"]
        pps.append({"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True})
        if thumb:
            pps.append({"key": "EmbedThumbnail", "already_have_thumbnail": o.mode == "both"})
        if o.mode == "both":
            # One download, two files: the MP3 is made from the merged MP4.
            late.append(lambda ydl: _ExtractAudioKeepSource(ydl, preferredcodec="mp3", preferredquality=o.mp3_quality))
            if thumb:
                late.append(lambda ydl: EmbedThumbnailPP(ydl, already_have_thumbnail=False))
    else:  # mp3
        if not has_ffmpeg:
            raise RuntimeError("ffmpeg not found")
        opts["format"] = "ba/b"
        pps.append({"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": o.mp3_quality})
        pps.append({"key": "FFmpegMetadata", "add_metadata": True})
        if thumb:
            pps.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

    if thumb:
        opts["writethumbnail"] = True
    opts["postprocessors"] = pps
    return opts, late


def cleanup_partials(output_dir: str) -> None:
    """Remove leftovers from downloads interrupted by closing the app."""
    shutil.rmtree(Path(output_dir) / PARTIAL_DIR, ignore_errors=True)
