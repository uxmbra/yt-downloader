"""The main window (CustomTkinter)."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import tools
from .engine import (
    ACTIVE,
    FINISHED,
    DownloadManager,
    Job,
    JobOptions,
    Status,
    clean_error,
    cleanup_partials,
    extract_urls,
    is_collection_url,
    is_youtube_url,
)
from .settings import APP_NAME, Settings

# ------------------------------------------------------------------ styling
ACCENT = ("#D62F35", "#E5383B")
ACCENT_HOVER = ("#B3242A", "#C42B30")
# Segmented buttons have a single text colour, so in light mode the selected segment is a pale red.
SEG_SELECTED = ("#F7C6C8", "#E5383B")
SEG_SELECTED_HOVER = ("#F1B0B3", "#C42B30")
BG = ("#F2F2F5", "#121214")
CARD = ("#FFFFFF", "#1C1C20")
CARD_BORDER = ("#E2E2E8", "#2A2A30")
SUBTLE = ("#E9E9EE", "#26262C")
SUBTLE_HOVER = ("#DCDCE3", "#303037")
TEXT = ("#16161A", "#EDEDF0")
MUTED = ("#6B6B75", "#9696A0")
SUCCESS = ("#1E8E3E", "#43D18A")
ERROR = ("#C5221F", "#FF6B6B")

MODE_LABELS = {"MP4": "mp4", "MP3": "mp3", "MP4 + MP3": "both"}
QUALITY_LABELS = {
    "Best available": "best",
    "2160p (4K)": "2160",
    "1440p": "1440",
    "1080p": "1080",
    "720p": "720",
    "480p": "480",
    "360p": "360",
}
MP3_LABELS = {"320 kbps (best)": "320", "256 kbps": "256", "192 kbps": "192", "VBR V0 (smaller files)": "0"}
PARALLEL_CHOICES = ["1", "2", "3", "4", "5", "6"]


def label_for(mapping: dict[str, str], value: str) -> str:
    return next((k for k, v in mapping.items() if v == value), next(iter(mapping)))


def fmt_bytes(n: float | None) -> str:
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def fmt_eta(sec: float | None) -> str:
    if sec is None:
        return ""
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# ------------------------------------------------------------------ queue row
class JobRow(ctk.CTkFrame):
    def __init__(self, master, job: Job, app: "App") -> None:
        super().__init__(master, fg_color=CARD, corner_radius=12, border_width=1, border_color=CARD_BORDER)
        self.job, self.app = job, app
        self._last_state: tuple | None = None
        self._spinning = False
        self.grid_columnconfigure(0, weight=1)

        self.title_lbl = ctk.CTkLabel(self, text="", anchor="w", font=app.f_row_title, text_color=TEXT)
        self.title_lbl.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=(12, 0))

        self.badge = ctk.CTkLabel(
            self, text="", font=app.f_badge, fg_color=SUBTLE, corner_radius=6, text_color=MUTED, height=22
        )
        self.badge.grid(row=0, column=1, padx=4, pady=(12, 0))

        self.action_btn = ctk.CTkButton(self, text="", width=86, height=30, corner_radius=8, font=app.f_small_bold)
        self.action_btn.grid(row=0, column=2, rowspan=3, padx=(10, 4))

        self.remove_btn = ctk.CTkButton(
            self, text="✕", width=30, height=30, corner_radius=8, fg_color="transparent",
            hover_color=SUBTLE_HOVER, text_color=MUTED, font=app.f_small_bold, command=self._remove,
        )
        self.remove_btn.grid(row=0, column=3, rowspan=3, padx=(0, 12))

        self.bar = ctk.CTkProgressBar(self, height=6, corner_radius=3, progress_color=ACCENT, fg_color=SUBTLE)
        self.bar.set(0)
        self.bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(9, 5))

        self.status_lbl = ctk.CTkLabel(self, text="", anchor="w", font=app.f_small, text_color=MUTED, justify="left")
        self.status_lbl.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 11))
        self.refresh()

    # -- actions
    def _remove(self) -> None:
        self.app.remove_job(self.job)

    def _cancel(self) -> None:
        self.app.manager.cancel(self.job)

    def _retry(self) -> None:
        self.app.manager.retry(self.job)

    def _show(self) -> None:
        tools.open_folder(self.job.opts.output_dir, self.job.filepath or None)

    # -- drawing
    def _spin(self, on: bool) -> None:
        if on and not self._spinning:
            self.bar.configure(mode="indeterminate")
            self.bar.start()
        elif not on and self._spinning:
            self.bar.stop()
            self.bar.configure(mode="determinate")
        self._spinning = on

    def refresh(self) -> None:
        j = self.job
        state = (j.status, round(j.progress, 3), j.detail, j.title, j.resolution, j.error,
                 int((j.speed or 0) / 20000), None if j.eta is None else int(j.eta))
        if state == self._last_state:
            return
        self._last_state = state

        self.title_lbl.configure(text=truncate(j.display_title, 88))
        badge = {"mp4": "MP4", "mp3": "MP3", "both": "MP4 + MP3"}[j.opts.mode]
        if j.opts.mode != "mp3":
            badge += " · " + (j.resolution or ("Best" if j.opts.quality == "best" else f"≤{j.opts.quality}p"))
        self.badge.configure(text=f"  {badge}  ")

        s = j.status
        color = MUTED
        if s == Status.QUEUED:
            text = "Waiting in queue"
            self._spin(False)
            self.bar.set(0)
        elif s == Status.STARTING:
            text = j.detail or "Starting…"
            self._spin(True)
        elif s == Status.DOWNLOADING:
            self._spin(False)
            self.bar.set(j.progress)
            parts = [j.detail or "Downloading", f"{j.progress * 100:.0f}%"]
            if j.total_bytes:
                parts.append(f"of {fmt_bytes(j.total_bytes)}")
            if j.speed:
                parts.append(f"{fmt_bytes(j.speed)}/s")
            if j.eta is not None:
                parts.append(f"{fmt_eta(j.eta)} left")
            text = "  ·  ".join(parts)
        elif s == Status.PROCESSING:
            text = (j.detail or "Processing") + "…"
            self._spin(True)
        elif s == Status.DONE:
            self._spin(False)
            self.bar.set(1)
            name = os.path.basename(j.filepath) if j.filepath else ""
            if j.opts.mode == "both" and name:
                name = os.path.splitext(name)[0] + " (.mp4 + .mp3)"
            text = "✓  Saved" + (f"  ·  {name}" if name else "")
            color = SUCCESS
        elif s == Status.FAILED:
            self._spin(False)
            self.bar.set(0)
            text = "✕  " + (j.error or "Failed")
            color = ERROR
        else:  # cancelled
            self._spin(False)
            self.bar.set(0)
            text = "Cancelled"
        self.status_lbl.configure(text=truncate(text, 140), text_color=color)
        idle = s in (Status.QUEUED, Status.FAILED, Status.CANCELLED)  # hide the 0% dot
        self.bar.configure(progress_color=SUCCESS if s == Status.DONE else SUBTLE if idle else ACCENT)

        if s in (Status.FAILED, Status.CANCELLED):
            self.action_btn.configure(text="Retry", command=self._retry, fg_color=ACCENT,
                                      hover_color=ACCENT_HOVER, text_color="white")
        elif s == Status.DONE:
            self.action_btn.configure(text="Show", command=self._show, fg_color=SUBTLE,
                                      hover_color=SUBTLE_HOVER, text_color=TEXT)
        else:
            self.action_btn.configure(text="Cancel", command=self._cancel, fg_color=SUBTLE,
                                      hover_color=SUBTLE_HOVER, text_color=TEXT)


# ------------------------------------------------------------------ settings window
class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app: "App") -> None:
        super().__init__(app)
        self.app = app
        s = app.settings
        self.title("Settings")
        self.geometry("560x700")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.transient(app)
        self.after(250, self._bring_to_front)

        body = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14, border_width=1, border_color=CARD_BORDER)
        body.pack(fill="both", expand=True, padx=18, pady=18)
        body.grid_columnconfigure(0, weight=1)
        row = 0

        def section(text: str) -> None:
            nonlocal row
            ctk.CTkLabel(body, text=text, font=app.f_section, text_color=TEXT, anchor="w").grid(
                row=row, column=0, columnspan=2, sticky="ew", padx=20, pady=(18 if row else 16, 4))
            row += 1

        def switch(text: str, hint: str, attr: str) -> None:
            nonlocal row
            var = tk.BooleanVar(value=getattr(s, attr))
            sw = ctk.CTkSwitch(body, text=text, variable=var, font=app.f_body, text_color=TEXT,
                               progress_color=ACCENT, command=lambda: self._set(attr, var.get()))
            sw.grid(row=row, column=0, columnspan=2, sticky="w", padx=20, pady=(6, 0))
            row += 1
            if hint:
                ctk.CTkLabel(body, text=hint, font=app.f_small, text_color=MUTED, anchor="w", justify="left").grid(
                    row=row, column=0, columnspan=2, sticky="w", padx=(66, 20))
                row += 1

        section("Video")
        switch("Max compatibility mode", "H.264 + AAC so it plays on anything (TVs, old phones). Caps at ~1080p.",
               "compat_mode")
        switch("Allow HDR video", "Off: picks the SDR version at the same resolution (HDR looks washed out\n"
               "on most screens).", "allow_hdr")

        section("Audio")
        ctk.CTkLabel(body, text="MP3 quality", font=app.f_body, text_color=TEXT, anchor="w").grid(
            row=row, column=0, sticky="w", padx=20, pady=6)
        mp3 = ctk.CTkOptionMenu(body, values=list(MP3_LABELS), width=190, fg_color=SUBTLE, button_color=SUBTLE,
                                button_hover_color=SUBTLE_HOVER, text_color=TEXT, font=app.f_body,
                                command=lambda v: self._set("mp3_quality", MP3_LABELS[v]))
        mp3.set(label_for(MP3_LABELS, s.mp3_quality))
        mp3.grid(row=row, column=1, sticky="e", padx=20, pady=6)
        row += 1
        switch("Embed cover art and tags", "", "embed_thumbnail")

        section("Queue")
        switch("Split playlists and channels", "A playlist link adds every video as its own item.",
               "expand_playlists")

        section("Engine")
        switch("Keep yt-dlp updated automatically", "Updates quietly after you close the app (at most once a day).",
               "auto_update")
        eng = ctk.CTkFrame(body, fg_color="transparent")
        eng.grid(row=row, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 0))
        eng.grid_columnconfigure(0, weight=1)
        row += 1
        ff = "found" if tools.ffmpeg_path() else "MISSING"
        dn = "found" if tools.deno_path() else "MISSING"
        self.engine_lbl = ctk.CTkLabel(
            eng, text=f"yt-dlp {tools.ytdlp_version()}   ·   FFmpeg {ff}   ·   Deno {dn}",
            font=app.f_small, text_color=MUTED, anchor="w")
        self.engine_lbl.grid(row=0, column=0, sticky="w")
        self.update_btn = ctk.CTkButton(eng, text="Update now", width=110, height=30, corner_radius=8,
                                        fg_color=SUBTLE, hover_color=SUBTLE_HOVER, text_color=TEXT,
                                        font=app.f_small_bold, command=self._update_now)
        self.update_btn.grid(row=0, column=1, sticky="e")
        if not tools.can_self_update():
            self.update_btn.configure(state="disabled")

        ctk.CTkButton(self, text="Done", height=36, corner_radius=10, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=app.f_body_bold, command=self.destroy).pack(fill="x", padx=18, pady=(0, 18))

    def _bring_to_front(self) -> None:
        self.app.apply_icon(self)
        self.lift()
        self.focus_force()

    def _set(self, attr: str, value) -> None:
        setattr(self.app.settings, attr, value)
        self.app.settings.save()

    def _update_now(self) -> None:
        self.update_btn.configure(state="disabled", text="Updating…")

        def work() -> None:
            ok, msg = tools.update_ytdlp()
            self.app.post(lambda: self._update_done(ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _update_done(self, ok: bool, msg: str) -> None:
        if not self.winfo_exists():
            return
        self.update_btn.configure(state="normal", text="Update now")
        if ok:
            self.app.settings.last_update_check = time.time()
            self.app.settings.save()
            self.engine_lbl.configure(text=f"yt-dlp {msg} installed. Restart the app to use it.", text_color=SUCCESS)
        else:
            self.engine_lbl.configure(text=f"Update failed: {truncate(msg, 60)}", text_color=ERROR)


# ------------------------------------------------------------------ main window
class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.title(APP_NAME)
        self.geometry("1000x740")
        self.minsize(780, 560)
        self.configure(fg_color=BG)
        self.apply_icon(self)

        family = "Segoe UI" if tools.IS_WINDOWS else "Helvetica"
        self.f_h1 = ctk.CTkFont(family=family, size=24, weight="bold")
        self.f_section = ctk.CTkFont(family=family, size=15, weight="bold")
        self.f_row_title = ctk.CTkFont(family=family, size=14, weight="bold")
        self.f_body = ctk.CTkFont(family=family, size=13)
        self.f_body_bold = ctk.CTkFont(family=family, size=13, weight="bold")
        self.f_input = ctk.CTkFont(family=family, size=15)
        self.f_small = ctk.CTkFont(family=family, size=12)
        self.f_small_bold = ctk.CTkFont(family=family, size=12, weight="bold")
        self.f_badge = ctk.CTkFont(family=family, size=11, weight="bold")

        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self.manager = DownloadManager(self._events.put, self.settings.max_parallel)
        self.jobs: list[Job] = []
        self.rows: dict[int, JobRow] = {}
        self._clip_seen: set[str] = set()
        self._last_clip = self._read_clipboard()  # ignore whatever was copied before launch
        self._toast_after: str | None = None
        self._expanding = 0
        self._settings_win: SettingsWindow | None = None

        self._build()
        cleanup_partials(self.settings.output_dir)

        self.bind("<Control-v>", self._on_ctrl_v)
        self.bind("<Control-V>", self._on_ctrl_v)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_events)
        self.after(700, self._poll_clipboard)
        self.after(50, self.entry.focus_set)

    # ---------------------------------------------------------------- layout
    def _build(self) -> None:
        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=24, pady=(20, 14))
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(3, weight=1)

        # Header
        head = ctk.CTkFrame(root, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        logo = ctk.CTkLabel(head, text="▼", width=40, height=40, corner_radius=10, fg_color=ACCENT,
                            text_color="white", font=ctk.CTkFont(size=18, weight="bold"))
        logo.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(head, text=APP_NAME, font=self.f_h1, text_color=TEXT, anchor="w").grid(
            row=0, column=1, sticky="w")
        ctk.CTkLabel(head, text="Paste a link, or just copy one anywhere: it's queued instantly.",
                     font=self.f_small, text_color=MUTED, anchor="w").grid(row=1, column=1, sticky="w")
        ctk.CTkButton(head, text="⚙  Settings", width=110, height=34, corner_radius=10, fg_color=SUBTLE,
                      hover_color=SUBTLE_HOVER, text_color=TEXT, font=self.f_body_bold,
                      command=self.open_settings).grid(row=0, column=2, rowspan=2, sticky="e")

        # Input card
        card = ctk.CTkFrame(root, fg_color=CARD, corner_radius=14, border_width=1, border_color=CARD_BORDER)
        card.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        card.grid_columnconfigure(0, weight=1)

        inrow = ctk.CTkFrame(card, fg_color="transparent")
        inrow.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        inrow.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(
            inrow, height=46, corner_radius=10, border_width=1, border_color=CARD_BORDER, fg_color=BG,
            text_color=TEXT, font=self.f_input,
            placeholder_text="Paste YouTube links here (videos, Shorts, playlists, several at once)…",
        )
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda e: self._add_from_entry())
        self.entry.bind("<<Paste>>", lambda e: self.after(15, self._add_from_entry))
        ctk.CTkButton(inrow, text="Paste", width=90, height=46, corner_radius=10, fg_color=SUBTLE,
                      hover_color=SUBTLE_HOVER, text_color=TEXT, font=self.f_body_bold,
                      command=self._add_from_clipboard).grid(row=0, column=1, padx=(10, 0))
        ctk.CTkButton(inrow, text="Download", width=120, height=46, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, font=self.f_body_bold,
                      command=self._add_from_entry).grid(row=0, column=2, padx=(10, 0))

        opts = ctk.CTkFrame(card, fg_color="transparent")
        opts.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        opts.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(opts, text="Format", font=self.f_small_bold, text_color=MUTED).grid(row=0, column=0, padx=(2, 8))
        self.mode_btn = ctk.CTkSegmentedButton(
            opts, values=list(MODE_LABELS), height=32, corner_radius=8, font=self.f_body_bold,
            fg_color=SUBTLE, unselected_color=SUBTLE, unselected_hover_color=SUBTLE_HOVER,
            selected_color=SEG_SELECTED, selected_hover_color=SEG_SELECTED_HOVER, text_color=TEXT,
            command=self._on_mode,
        )
        self.mode_btn.set(label_for(MODE_LABELS, self.settings.mode))
        self.mode_btn.grid(row=0, column=1)

        ctk.CTkLabel(opts, text="Quality", font=self.f_small_bold, text_color=MUTED).grid(
            row=0, column=2, padx=(20, 8))
        self.quality_menu = ctk.CTkOptionMenu(
            opts, values=list(QUALITY_LABELS), width=150, height=32, corner_radius=8, fg_color=SUBTLE,
            button_color=SUBTLE, button_hover_color=SUBTLE_HOVER, text_color=TEXT, font=self.f_body,
            command=self._on_quality,
        )
        self.quality_menu.set(label_for(QUALITY_LABELS, self.settings.quality))
        self.quality_menu.grid(row=0, column=3)

        self.clip_var = tk.BooleanVar(value=self.settings.watch_clipboard)
        ctk.CTkSwitch(opts, text="Auto-add copied links", variable=self.clip_var, font=self.f_body,
                      text_color=TEXT, progress_color=ACCENT, command=self._on_clip_toggle).grid(
            row=0, column=4, padx=(20, 0))

        folder = ctk.CTkFrame(card, fg_color="transparent")
        folder.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        folder.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(folder, text="Save to", font=self.f_small_bold, text_color=MUTED).grid(
            row=0, column=0, padx=(2, 8))
        self.folder_btn = ctk.CTkButton(
            folder, text="", height=32, corner_radius=8, anchor="w", fg_color=SUBTLE, hover_color=SUBTLE_HOVER,
            text_color=TEXT, font=self.f_body, command=self._choose_folder)
        self.folder_btn.grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(folder, text="Open folder", width=110, height=32, corner_radius=8, fg_color=SUBTLE,
                      hover_color=SUBTLE_HOVER, text_color=TEXT, font=self.f_body_bold,
                      command=lambda: tools.open_folder(self.settings.output_dir)).grid(row=0, column=2, padx=(10, 0))
        self._refresh_folder()
        self._on_mode(self.mode_btn.get(), save=False)

        # Queue header
        qhead = ctk.CTkFrame(root, fg_color="transparent")
        qhead.grid(row=2, column=0, sticky="ew", pady=(20, 8))
        qhead.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(qhead, text="Queue", font=self.f_section, text_color=TEXT).grid(row=0, column=0, padx=(2, 10))
        self.counts_lbl = ctk.CTkLabel(qhead, text="", font=self.f_small, text_color=MUTED, anchor="w")
        self.counts_lbl.grid(row=0, column=1, sticky="w")
        for col, (txt, cmd) in enumerate((("Retry failed", self.retry_failed), ("Clear finished", self.clear_finished),
                                          ("Cancel all", self.cancel_all)), start=2):
            ctk.CTkButton(qhead, text=txt, width=104, height=30, corner_radius=8, fg_color="transparent",
                          border_width=1, border_color=CARD_BORDER, hover_color=SUBTLE_HOVER, text_color=TEXT,
                          font=self.f_small_bold, command=cmd).grid(row=0, column=col, padx=(8, 0))

        # Queue list
        self.list = ctk.CTkScrollableFrame(root, fg_color="transparent", corner_radius=0,
                                           scrollbar_button_color=SUBTLE, scrollbar_button_hover_color=SUBTLE_HOVER)
        self.list.grid(row=3, column=0, sticky="nsew")
        self.list.grid_columnconfigure(0, weight=1)
        self.empty_lbl = ctk.CTkLabel(
            self.list, text="Nothing here yet.\n\nCopy a YouTube link in your browser and it shows up here,\n"
                            "or paste one above (Ctrl+V works anywhere in this window).",
            font=self.f_body, text_color=MUTED, justify="center")
        self.empty_lbl.pack(pady=70)

        # Footer
        foot = ctk.CTkFrame(root, fg_color="transparent")
        foot.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        foot.grid_columnconfigure(0, weight=1)
        self.toast_lbl = ctk.CTkLabel(foot, text="", font=self.f_small, text_color=MUTED, anchor="w")
        self.toast_lbl.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(foot, text="Downloads at once", font=self.f_small_bold, text_color=MUTED).grid(
            row=0, column=1, padx=(10, 8))
        self.parallel_btn = ctk.CTkSegmentedButton(
            foot, values=PARALLEL_CHOICES, height=28, corner_radius=8, font=self.f_small_bold, fg_color=SUBTLE,
            unselected_color=SUBTLE, unselected_hover_color=SUBTLE_HOVER, selected_color=SEG_SELECTED,
            selected_hover_color=SEG_SELECTED_HOVER, text_color=TEXT, command=self._on_parallel)
        self.parallel_btn.set(str(min(self.settings.max_parallel, 6)))
        self.parallel_btn.grid(row=0, column=2)

        missing = [n for n, p in (("FFmpeg", tools.ffmpeg_path()), ("Deno", tools.deno_path())) if not p]
        if missing:
            self.toast(f"⚠  {' and '.join(missing)} not found. Run setup.bat so MP3 and top quality work.",
                       color=ERROR, seconds=0)
        self._update_counts()

    # ---------------------------------------------------------------- helpers
    def apply_icon(self, window) -> None:
        ico = tools.resource_path("assets", "icon.ico")
        if tools.IS_WINDOWS and ico.exists():
            try:
                window.iconbitmap(str(ico))
            except tk.TclError:
                pass

    def post(self, fn) -> None:
        """Run fn on the GUI thread (safe to call from any thread)."""
        self._events.put(fn)

    def toast(self, text: str, color=MUTED, seconds: float = 5) -> None:
        self.toast_lbl.configure(text=text, text_color=color)
        if self._toast_after:
            self.after_cancel(self._toast_after)
            self._toast_after = None
        if seconds:
            self._toast_after = self.after(int(seconds * 1000), lambda: self.toast_lbl.configure(text=""))

    def _refresh_folder(self) -> None:
        self.folder_btn.configure(text="  📁  " + truncate(self.settings.output_dir, 90))

    def _current_options(self) -> JobOptions:
        s = self.settings
        return JobOptions(mode=s.mode, quality=s.quality, output_dir=s.output_dir, compat=s.compat_mode,
                          allow_hdr=s.allow_hdr, mp3_quality=s.mp3_quality, embed_thumbnail=s.embed_thumbnail)

    # ---------------------------------------------------------------- option callbacks
    def _on_mode(self, label: str, save: bool = True) -> None:
        self.settings.mode = MODE_LABELS[label]
        self.quality_menu.configure(state="disabled" if self.settings.mode == "mp3" else "normal")
        if save:
            self.settings.save()

    def _on_quality(self, label: str) -> None:
        self.settings.quality = QUALITY_LABELS[label]
        self.settings.save()

    def _on_clip_toggle(self) -> None:
        self.settings.watch_clipboard = self.clip_var.get()
        self._last_clip = self._read_clipboard()
        self.settings.save()

    def _on_parallel(self, value: str) -> None:
        self.settings.max_parallel = int(value)
        self.manager.set_max_parallel(int(value))
        self.settings.save()

    def _choose_folder(self) -> None:
        path = filedialog.askdirectory(initialdir=self.settings.output_dir, title="Choose download folder")
        if path:
            self.settings.output_dir = os.path.normpath(path)
            self.settings.save()
            self._refresh_folder()

    def open_settings(self) -> None:
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.focus_force()
            return
        self._settings_win = SettingsWindow(self)

    # ---------------------------------------------------------------- adding links
    def _add_from_entry(self) -> None:
        text = self.entry.get()
        if not text.strip():
            return
        if self.add_text(text):
            self.entry.delete(0, "end")

    def _add_from_clipboard(self) -> None:
        self.add_text(self._read_clipboard() or "", empty_msg="The clipboard has no links in it.")

    def _on_ctrl_v(self, event) -> None:
        if isinstance(event.widget, (tk.Entry, tk.Text)):
            return  # normal paste into a text box (the entry adds on <<Paste>>)
        self._add_from_clipboard()

    def add_text(self, text: str, from_clipboard: bool = False, empty_msg: str | None = None) -> bool:
        urls = extract_urls(text)
        if from_clipboard:
            urls = [u for u in urls if is_youtube_url(u)]
        if not urls:
            if not from_clipboard:
                self.toast(empty_msg or "No links found. Paste a full link starting with https://", color=ERROR)
            return False
        added = skipped = 0
        for url in urls:
            if is_collection_url(url) and self.settings.expand_playlists:
                self._expand_async(url)
            elif self.add_url(url):
                added += 1
            else:
                skipped += 1
        if added:
            msg = f"Added {added} link{'s' if added != 1 else ''}"
            if from_clipboard:
                msg += " from clipboard"
            if skipped:
                msg += f"  ·  {skipped} already in queue"
            self.toast(msg)
        elif skipped:
            self.toast("Already in the queue")
        return True

    def add_url(self, url: str, title: str = "") -> bool:
        opts = self._current_options()
        job = Job(url=url, opts=opts, title=title)
        outputs = {"mp4": {"mp4"}, "mp3": {"mp3"}, "both": {"mp4", "mp3"}}
        for other in self.jobs:
            if (other.key == job.key and other.status not in FINISHED
                    and outputs[other.opts.mode] & outputs[opts.mode]):
                return False  # would write the same file as a download that's already queued
        self.jobs.append(job)
        if self.empty_lbl.winfo_ismapped():
            self.empty_lbl.pack_forget()
        row = JobRow(self.list, job, self)
        row.pack(fill="x", pady=(0, 8), padx=(0, 6))
        self.rows[job.id] = row
        self.manager.submit(job)
        self._update_counts()
        return True

    def _expand_async(self, url: str) -> None:
        self._expanding += 1
        self.toast("Reading playlist…", seconds=0)
        self._update_counts()

        def work() -> None:
            try:
                entries = DownloadManager.expand(url)
                err = None
            except Exception as exc:  # noqa: BLE001
                entries, err = [], str(exc)
            self.post(lambda: self._expanded(entries, err))

        threading.Thread(target=work, daemon=True).start()

    def _expanded(self, entries: list[tuple[str, str]], err: str | None) -> None:
        if err:
            self._expanding -= 1
            self.toast(f"Couldn't read playlist: {truncate(clean_error(err), 90)}", color=ERROR, seconds=10)
        elif not entries:
            self._expanding -= 1
            self.toast("No videos found at that link.", color=ERROR)
        else:
            self._add_batch(entries, 0, 0)
        self._update_counts()

    def _add_batch(self, entries: list[tuple[str, str]], start: int, added: int) -> None:
        """Add big playlists 20 rows at a time so the window never freezes."""
        for url, title in entries[start:start + 20]:
            added += self.add_url(url, title)
        start += 20
        if start < len(entries):
            self.toast(f"Adding playlist… {start}/{len(entries)}", seconds=0)
            self.after(1, lambda: self._add_batch(entries, start, added))
        else:
            self._expanding -= 1
            self.toast(f"Added {added} video{'s' if added != 1 else ''} from playlist")
            self._update_counts()

    # ---------------------------------------------------------------- clipboard watching
    def _read_clipboard(self) -> str | None:
        try:
            return self.clipboard_get()
        except tk.TclError:
            return None

    def _poll_clipboard(self) -> None:
        try:
            if self.clip_var.get():
                clip = self._read_clipboard()
                if clip and clip != self._last_clip and len(clip) < 20000:
                    self._last_clip = clip
                    fresh = [u for u in extract_urls(clip) if is_youtube_url(u) and u not in self._clip_seen]
                    if fresh:
                        self._clip_seen.update(fresh)
                        self.add_text("\n".join(fresh), from_clipboard=True)
                elif clip:
                    self._last_clip = clip
        finally:
            self.after(700, self._poll_clipboard)

    # ---------------------------------------------------------------- queue actions
    def remove_job(self, job: Job) -> None:
        if job.status not in FINISHED:
            self.manager.cancel(job)
        row = self.rows.pop(job.id, None)
        if row:
            row.destroy()
        if job in self.jobs:
            self.jobs.remove(job)
        if not self.jobs:
            self.empty_lbl.pack(pady=70)
        self._update_counts()

    def clear_finished(self) -> None:
        for job in [j for j in self.jobs if j.status in (Status.DONE, Status.CANCELLED)]:
            self.remove_job(job)

    def retry_failed(self) -> None:
        for job in [j for j in self.jobs if j.status == Status.FAILED]:
            self.manager.retry(job)

    def cancel_all(self) -> None:
        for job in [j for j in self.jobs if j.status not in FINISHED]:
            self.manager.cancel(job)

    def _update_counts(self) -> None:
        by = {s: 0 for s in Status}
        for j in self.jobs:
            by[j.status] += 1
        active = sum(by[s] for s in ACTIVE)
        parts = []
        if active:
            parts.append(f"{active} downloading")
        if by[Status.QUEUED]:
            parts.append(f"{by[Status.QUEUED]} waiting")
        if self._expanding:
            parts.append("reading playlist…")
        if by[Status.DONE]:
            parts.append(f"{by[Status.DONE]} done")
        if by[Status.FAILED]:
            parts.append(f"{by[Status.FAILED]} failed")
        self.counts_lbl.configure(text="  ·  ".join(parts))
        title = APP_NAME
        if active or by[Status.QUEUED]:
            title = f"({active + by[Status.QUEUED]}) {APP_NAME}"
        self.title(title)

    def _drain_events(self) -> None:
        dirty: set[int] = set()
        try:
            for _ in range(2000):
                item = self._events.get_nowait()
                if isinstance(item, Job):
                    dirty.add(item.id)
                else:
                    item()
        except queue.Empty:
            pass
        for job_id in dirty:
            row = self.rows.get(job_id)
            if row is not None:
                row.refresh()
        if dirty:
            self._update_counts()
        self.after(100, self._drain_events)

    # ---------------------------------------------------------------- closing
    def _on_close(self) -> None:
        running = [j for j in self.jobs if j.status not in FINISHED]
        if running and not messagebox.askyesno(
            APP_NAME, f"{len(running)} download(s) haven't finished.\nQuit anyway and cancel them?", parent=self
        ):
            return
        for j in running:
            self.manager.cancel(j)
        self._maybe_schedule_update()
        self.settings.save()
        self.destroy()

    def _maybe_schedule_update(self) -> None:
        s = self.settings
        if not (s.auto_update and tools.can_self_update()) or time.time() - s.last_update_check < 86400:
            return
        s.last_update_check = time.time()
        flags = (0x00000008 | tools.NO_WINDOW) if tools.IS_WINDOWS else 0  # DETACHED_PROCESS
        try:
            subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "--disable-pip-version-check",
                 "yt-dlp[default]"],
                creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
            )
        except OSError:
            pass


def main() -> None:
    if tools.IS_WINDOWS:
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YTDownloader.App")
        except Exception:
            pass
    ctk.set_appearance_mode("system")
    app = App()
    # Links passed on the command line ("YT Downloader.exe <url> ...") are queued at startup.
    if links := " ".join(sys.argv[1:]).strip():
        app.after(300, lambda: app.add_text(links))
    app.mainloop()


if __name__ == "__main__":
    main()
