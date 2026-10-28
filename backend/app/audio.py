import asyncio
import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

import anyio

log = logging.getLogger(__name__)

# Opus first (best quality per byte, and what Premium's 256 kbps stream uses), AAC as a fallback.
AUDIO_FORMAT = "bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio"
AUDIO_EXTENSIONS = {".webm", ".m4a", ".mp4", ".opus", ".ogg", ".mp3"}
# Hours-long mixes would blow the cache; a stuck connection must not hang a download forever.
MAX_FILE_BYTES = 300 * 1024 * 1024
SOCKET_TIMEOUT_SECONDS = 30

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
        "socket_timeout": SOCKET_TIMEOUT_SECONDS,
        "max_filesize": MAX_FILE_BYTES,
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

    Different tracks download in parallel, so the host never waits behind a prefetch;
    concurrent requests for the same track share a single download. yt-dlp rewrites its
    cookie file when it finishes, so each download gets a private copy and the refreshed
    cookies are copied back afterwards (skipped if the original is read-only).
    """

    def __init__(self, cache_dir: Path, cookies_file: Path | None, max_bytes: int,
                 downloader: Downloader = ytdlp_download) -> None:
        self.cache_dir = cache_dir
        self.cookies_file = cookies_file
        self.max_bytes = max_bytes
        self.downloader = downloader
        self._cookie_lock = asyncio.Lock()
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
        path = self.cached(video_id)
        if path is not None:
            return path
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cookie_copy = self._copy_cookies()
        try:
            path = await anyio.to_thread.run_sync(self.downloader, video_id, self.cache_dir, cookie_copy)
            if cookie_copy is not None:
                await self._save_cookies(cookie_copy)
            return path
        finally:
            if cookie_copy is not None:
                cookie_copy.unlink(missing_ok=True)

    def _copy_cookies(self) -> Path | None:
        if self.cookies_file is None or not self.cookies_file.is_file():
            return None
        fd, name = tempfile.mkstemp(prefix="jam-cookies-", suffix=".txt")
        os.close(fd)
        shutil.copyfile(self.cookies_file, name)
        return Path(name)

    async def _save_cookies(self, refreshed: Path) -> None:
        """Keep YouTube's refreshed cookies so the session doesn't go stale."""
        assert self.cookies_file is not None
        if not os.access(self.cookies_file, os.W_OK):
            return
        async with self._cookie_lock:
            tmp: str | None = None
            try:
                fd, tmp = tempfile.mkstemp(dir=self.cookies_file.parent, prefix=".cookies-", suffix=".tmp")
                os.close(fd)
                shutil.copyfile(refreshed, tmp)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.cookies_file)
            except OSError:
                log.info("Couldn't write refreshed cookies back to %s", self.cookies_file, exc_info=True)
                if tmp is not None:
                    Path(tmp).unlink(missing_ok=True)

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
