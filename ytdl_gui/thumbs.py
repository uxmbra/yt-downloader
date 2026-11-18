"""Loads small video thumbnails for the queue in the background."""
from __future__ import annotations

import io
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

try:
    from PIL import Image, ImageDraw, ImageOps
except ImportError:  # thumbnails are optional
    Image = None  # type: ignore[assignment]

THUMB_SIZE = (112, 63)   # 16:9, in UI units (CTkImage handles display scaling)
_SCALE = 2               # fetch at 2x so it stays sharp on high-DPI screens
_RADIUS = 8


def available() -> bool:
    return Image is not None


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class ThumbnailLoader:
    def __init__(self, post: Callable[[Callable[[], None]], None]) -> None:
        self._post = post                      # runs a callable on the GUI thread
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumb")
        self._cache: dict[str, object] = {}    # url -> PIL image (or None if it failed)
        self._waiting: dict[str, list[Callable]] = {}
        self._ctx = _ssl_context()

    def request(self, url: str, callback: Callable[[object], None]) -> None:
        """callback(pil_image) on the GUI thread. Call from the GUI thread."""
        if not available() or not url:
            return
        if url in self._cache:
            if self._cache[url] is not None:
                callback(self._cache[url])
            return
        if url in self._waiting:
            self._waiting[url].append(callback)
            return
        self._waiting[url] = [callback]
        self._pool.submit(self._fetch, url)

    def _fetch(self, url: str) -> None:
        img = None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15, context=self._ctx) as resp:
                data = resp.read(2_000_000)
            w, h = THUMB_SIZE[0] * _SCALE, THUMB_SIZE[1] * _SCALE
            img = ImageOps.fit(Image.open(io.BytesIO(data)).convert("RGB"), (w, h), Image.LANCZOS)
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=_RADIUS * _SCALE, fill=255)
            img.putalpha(mask)
        except Exception:
            img = None
        self._post(lambda: self._deliver(url, img))

    def _deliver(self, url: str, img) -> None:
        self._cache[url] = img
        for cb in self._waiting.pop(url, []):
            if img is not None:
                cb(img)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
