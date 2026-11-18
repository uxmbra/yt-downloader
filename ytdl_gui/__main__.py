from . import updater

updater.activate()  # must run before anything imports yt_dlp

from .gui import main  # noqa: E402

main()
