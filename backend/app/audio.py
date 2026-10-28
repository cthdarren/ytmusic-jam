import asyncio
import logging
import os
import shutil
import tempfile
import time
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
# Downloads are short-term: anything not played or preloaded for a day is deleted.
MAX_AGE_SECONDS = 24 * 3600

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

    def prune(self, keep: set[str], max_age_seconds: float = MAX_AGE_SECONDS) -> None:
        """Delete tracks unused for `max_age_seconds`, then least recently used ones until the
        cache fits. Tracks in `keep` (playing or preloaded) are never deleted."""
        if not self.cache_dir.is_dir():
            return
        files = [p for p in self.cache_dir.iterdir() if p.is_file() and p.suffix in AUDIO_EXTENSIONS]
        total = sum(p.stat().st_size for p in files)
        stale_before = time.time() - max_age_seconds
        for path in sorted(files, key=lambda p: p.stat().st_mtime):
            stat = path.stat()
            if path.stem in keep or (total <= self.max_bytes and stat.st_mtime >= stale_before):
                continue
            path.unlink(missing_ok=True)
            total -= stat.st_size
            log.info("Evicted %s from the audio cache", path.name)

    def clear(self) -> None:
        """Delete every downloaded track (the night was cleared). Downloads still in progress
        are left alone so a song re-added straight away isn't broken; prune tidies them later."""
        if not self.cache_dir.is_dir():
            return
        for path in self.cache_dir.iterdir():
            if path.is_file() and path.suffix in AUDIO_EXTENSIONS:
                path.unlink(missing_ok=True)


class Preloader:
    """Keeps the songs about to play downloaded, nearest first.

    `update()` replaces the wanted list (in priority order) whenever the room changes; a
    few workers always pick the nearest song that isn't cached yet, so after a jump or a
    reorder the new nearest songs come first. Songs that fail aren't retried for a while.
    """

    def __init__(self, cache: AudioCache, concurrency: int = 2, retry_after: float = 300.0,
                 idle_timeout: float = 3600.0) -> None:
        self.cache = cache
        self.concurrency = concurrency
        self.retry_after = retry_after
        # Idle workers still wake up this often to prune, so old songs go even on quiet days.
        self.idle_timeout = idle_timeout
        self.wanted: list[str] = []
        self._in_progress: set[str] = set()
        self._failed_at: dict[str, float] = {}
        self._wake = asyncio.Event()
        self._workers: list[asyncio.Task] = []

    @property
    def idle(self) -> bool:
        return not self._in_progress and self._next() is None

    def start(self) -> None:
        """Start the workers (again, if any have stopped). Must be called on the event loop."""
        self._workers = [w for w in self._workers if not w.done()]
        while len(self._workers) < self.concurrency:
            self._workers.append(asyncio.create_task(self._work()))

    def update(self, wanted: list[str]) -> None:
        self.wanted = list(dict.fromkeys(wanted))
        self.start()
        self._wake.set()

    def reset(self) -> None:
        """Forget past failures (a new night has started)."""
        self._failed_at.clear()

    async def close(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    def _next(self) -> str | None:
        now = time.monotonic()
        for video_id in self.wanted:
            if video_id in self._in_progress or self.cache.cached(video_id) is not None:
                continue
            failed_at = self._failed_at.get(video_id)
            if failed_at is not None and now - failed_at < self.retry_after:
                continue
            return video_id
        return None

    async def _work(self) -> None:
        while True:
            try:
                await self._step()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never let one bad moment (a disk error while pruning, say) stop preloading for good.
                log.exception("Preloader hit an error; carrying on")
                await asyncio.sleep(1)

    async def _step(self) -> None:
        video_id = self._next()
        if video_id is None:
            if not self._in_progress:
                self.cache.prune(keep=set(self.wanted))
            self._wake.clear()
            # Wake up anyway to prune on quiet days and to retry songs whose back-off has passed.
            timeout = min(self.idle_timeout, self.retry_after) if self._failed_at else self.idle_timeout
            try:
                await asyncio.wait_for(self._wake.wait(), timeout)
            except TimeoutError:
                pass
            return
        self._in_progress.add(video_id)
        try:
            await self.cache.ensure(video_id)
            if self.cache.cached(video_id) is None:
                # Downloaded but not recognised as cached (unexpected file type): treat as failed so
                # we don't hit YouTube again for it in a tight loop.
                raise AudioUnavailable(f"{video_id} downloaded but isn't usable")
            self._failed_at.pop(video_id, None)
        except Exception:
            self._failed_at[video_id] = time.monotonic()
            log.warning("Couldn't preload %s", video_id, exc_info=True)
        finally:
            self._in_progress.discard(video_id)
