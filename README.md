# YT Downloader

A fast, simple desktop app for downloading YouTube videos as **MP4** (up to 4K/8K at 60fps), as **MP3** (320 kbps), or as both at once.
You copy a link and it starts downloading.

![icon](assets/icon.png)

## Features

- **Copy-and-go.** With *Auto-add copied links* on, any YouTube link you copy (in your browser, Discord, anywhere) is added to the queue and starts downloading. You can also paste into the box, press **Ctrl+V** anywhere in the window, or paste a block of text with several links in it.
- **Highest quality by default.** Picks the best video stream and the best audio stream and merges them into an MP4 (4K60 if the video has it). You can cap the resolution (2160p down to 360p).
- **MP4, MP3, or MP4 + MP3.** "MP4 + MP3" downloads once and makes both files from that one download.
- **Queue with parallel downloads.** Choose 1 to 6 downloads at a time. Each item shows a thumbnail, live progress, speed and time left. Pause or resume the whole queue; right-click an item to open, play, retry, copy its link or remove it, or double-click a finished one to play it.
- **Never lose progress.** Close the app mid-download and unfinished items come back the next time you open it, continuing from where they stopped. Temporary errors (network blips, expired links) are retried once automatically.
- **Playlists and channels.** A playlist link adds every video as its own queue item. A `watch?v=...&list=...` link downloads just that one video.
- **MP3s with tags.** Title, artist and cover art are embedded.
- **Nice to have:** light and dark themes that follow Windows, overall progress in the window title, a taskbar flash and chime when everything has finished, a duplicate-link guard, readable error messages, and a window that remembers its size. Opening the app a second time just brings the existing window forward, so links are never downloaded twice.
- **Stays working.** YouTube changes often, so the app checks for a newer **yt-dlp** (the download engine) in the background and offers a one-click restart once it's ready. This works in the .exe too. Updates are the official yt-dlp release, checked against yt-dlp's published SHA-256 sums. You can also check by hand in Settings.
- **Command line too:** `"YT Downloader.exe" <link> [<link> ...]` opens the app with those links already queued.

## Install (Windows)

1. Get the code: either `git clone https://github.com/uxmbra/yt-downloader.git`, or download the ZIP from GitHub and extract it.
2. Double-click **`setup.bat`**.
   It installs anything that's missing (Python, [FFmpeg](https://ffmpeg.org), [Deno](https://deno.com)) using `winget`, installs the Python packages into a private `.venv` folder, and adds a **YT Downloader** shortcut to your Desktop and Start Menu.
3. After that, launch it from the shortcut, or with `run.bat`.

> Why Deno? YouTube now requires a JavaScript runtime to unlock the full-quality formats, and yt-dlp uses Deno for that.
> FFmpeg merges the separate video and audio streams and creates the MP3s.

## Using it

| Step | |
|---|---|
| 1 | Choose **MP4**, **MP3** or **MP4 + MP3**, plus a quality (MP4 only) |
| 2 | Copy a YouTube link, or paste it into the box |
| 3 | Done. Files go to `Downloads\YT Downloader` (click the folder bar to change it) |

**Settings (⚙):**

- *Max compatibility mode*: forces H.264 video + AAC audio, which plays on anything (old TVs, some editors). YouTube only offers H.264 up to 1080p.
- *Allow HDR*: off by default, because HDR video looks washed out on non-HDR screens. The SDR version is picked at the same resolution.
- *MP3 quality*: 320 kbps (default), 256, 192, or VBR V0.
- *Download engine*: shows the yt-dlp version, with **Check for updates** and automatic checks (on by default).
- *Embed cover art and tags*, *Split playlists*, *Notify when downloads finish*, *Show thumbnails*.

## Build a standalone .exe (optional)

```bat
build_exe.bat
```

This creates `dist\YT Downloader\` with `YT Downloader.exe`, plus FFmpeg and Deno copied into its `bin` folder. Zip that folder and it runs on any Windows PC with no Python needed. It's a good thing to attach to a GitHub Release.
The .exe keeps its yt-dlp engine up to date by itself (see Settings).

## Project layout

```
ytdl_gui/
  engine.py           download queue + yt-dlp options (no GUI code)
  gui.py              CustomTkinter window, queue rows, settings dialog
  updater.py          checks for, verifies and loads newer yt-dlp versions
  single_instance.py  keeps one window; a second launch forwards its links
  thumbs.py           background thumbnail loading
  settings.py         settings + saved queue in %APPDATA%\YTDownloader\
  tools.py            finds FFmpeg/Deno, Explorer/taskbar helpers
run.pyw        launcher (no console window)
setup.ps1/.bat one-time installer
build_exe.*    PyInstaller build
scripts/       make_icon.py (regenerates assets/icon.*)
```

Run from source with: `.venv\Scripts\python -m ytdl_gui`

## Troubleshooting

- **"Sign in to confirm you're not a bot" or many failures at once:** open Settings, click **Check for updates**, then **Restart now**.
- **Stuck on a bad engine update?** Delete `%APPDATA%\YTDownloader\engine` and the app goes back to its built-in yt-dlp.
- **"FFmpeg/Deno not found" warning:** run `setup.bat` again, or put `ffmpeg.exe`, `ffprobe.exe` and `deno.exe` in a `bin` folder next to `run.pyw`.
- **Age-restricted or private videos** need a signed-in account and aren't supported.

## License

[MIT](LICENSE) for this project's code. Bundled third-party tools keep their own licences (see [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt); FFmpeg is GPLv3).

## Legal

For personal use. Only download content you own or have permission to download, and respect YouTube's Terms of Service and copyright law where you live.
