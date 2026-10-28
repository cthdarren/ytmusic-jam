import asyncio
import logging
import os
from collections.abc import Callable
from pathlib import Path

import anyio

log = logging.getLogger(__name__)

# Opus first (best quality per byte, and what Premium's 256 kbps stream uses), AAC as a fallback.
AUDIO_FORMAT = "bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio"
AUDIO_EXTENSIONS = {".webm", ".m4a", ".mp4", ".opus", ".ogg", ".mp3"}

Downloader = Callable[[str, Path, Path | None], Path]


class AudioUnavailable(Exception):
    """YouTube wouldn't give us audio for this video (removed, private, region-blocked...)."""


def ytdlp_download(video_id: str, dest_dir: Path, cookies_file: Path | None) -> Path:
    """Download one track's best audio stream into `dest_dir` as `<id>.<ext>`. Blocking."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    opts = {
        "format": AUDIO_FORMAT,
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if cookies_file is not None:
        opts["cookiefile"] = str(cookies_file)
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://music.youtube.com/watch?v={video_id}", download=True)
            path = Path(ydl.prepare_filename(info))
    except DownloadError as e:
        raise AudioUnavailable(str(e)) from e
    if not path.is_file():
        raise AudioUnavailable(f"yt-dlp finished but {path.name} is missing")
    return path


class AudioCache:
    """Downloaded tracks on disk, capped in size, evicting the least recently used first.

    Downloads run one at a time (yt-dlp rewrites the cookie file when it closes), and
    concurrent requests for the same track share a single download.
    """

    def __init__(self, cache_dir: Path, cookies_file: Path | None, max_bytes: int,
                 downloader: Downloader = ytdlp_download) -> None:
        self.cache_dir = cache_dir
        self.cookies_file = cookies_file
        self.max_bytes = max_bytes
        self.downloader = downloader
        self._lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Future[Path]] = {}

    def cached(self, video_id: str) -> Path | None:
        if not self.cache_dir.is_dir():
            return None
        for path in self.cache_dir.glob(f"{video_id}.*"):
            if path.suffix in AUDIO_EXTENSIONS and path.stem == video_id and path.is_file():
                return path
        return None

    async def ensure(self, video_id: str) -> Path:
        path = self.cached(video_id)
        if path is not None:
            os.utime(path)  # mark as recently used
            return path
        task = self._inflight.get(video_id)
        if task is None:
            task = asyncio.ensure_future(self._download(video_id))
            self._inflight[video_id] = task
            task.add_done_callback(lambda _: self._inflight.pop(video_id, None))
        return await asyncio.shield(task)

    async def _download(self, video_id: str) -> Path:
        async with self._lock:
            path = self.cached(video_id)
            if path is not None:
                return path
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cookies = self.cookies_file if self.cookies_file is not None and self.cookies_file.is_file() else None
            return await anyio.to_thread.run_sync(self.downloader, video_id, self.cache_dir, cookies)

    def prune(self, keep: set[str]) -> None:
        """Delete least recently used tracks until the cache fits, never touching `keep`."""
        if not self.cache_dir.is_dir():
            return
        files = [p for p in self.cache_dir.iterdir() if p.is_file() and p.suffix in AUDIO_EXTENSIONS]
        total = sum(p.stat().st_size for p in files)
        for path in sorted(files, key=lambda p: p.stat().st_mtime):
            if total <= self.max_bytes:
                break
            if path.stem in keep:
                continue
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size
            log.info("Evicted %s from the audio cache", path.name)
