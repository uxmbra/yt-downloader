"""Only one window at a time.

Two copies would both watch the clipboard and download every link twice. The
first copy listens on a localhost port; a second launch sends its links (if any)
there, which brings the existing window to the front, and then exits.
"""
from __future__ import annotations

import socket
import threading
import time
from typing import Callable

PORT = 47613
MAGIC = b"YTDL1\n"


class SingleInstance:
    def __init__(self) -> None:
        self._sock: socket.socket | None = None

    def acquire(self, wait: float = 0.0) -> bool:
        """Become the running instance. `wait` retries while a previous copy shuts down."""
        deadline = time.monotonic() + wait
        while True:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                sock.bind(("127.0.0.1", PORT))
                sock.listen(5)
                self._sock = sock
                return True
            except OSError:
                sock.close()
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.25)

    def serve(self, on_message: Callable[[str], None]) -> None:
        """Call on_message(text) for each message from a second launch (from a worker thread)."""
        sock = self._sock
        if sock is None:
            return

        def loop() -> None:
            while True:
                try:
                    conn, _ = sock.accept()
                except OSError:
                    return  # closed
                with conn:
                    conn.settimeout(3)
                    data = b""
                    try:
                        while len(data) < 1_000_000 and (chunk := conn.recv(65536)):
                            data += chunk
                    except OSError:
                        pass
                if data.startswith(MAGIC):
                    on_message(data[len(MAGIC):].decode("utf-8", "replace"))

        threading.Thread(target=loop, name="single-instance", daemon=True).start()

    def release(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None


def send_to_running(text: str) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=2) as s:
            s.sendall(MAGIC + text.encode("utf-8"))
        return True
    except OSError:
        return False
