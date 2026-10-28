import os
import threading
import time

import anyio
import pytest

from app.audio import AudioCache, AudioUnavailable

pytestmark = pytest.mark.anyio


class FakeDownloader:
    """Writes `size` bytes as <id>.webm; records calls; can fail or be slow."""

    def __init__(self, size=100, fail=(), delay=0.0):
        self.size = size
        self.fail = set(fail)
        self.delay = delay
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, video_id, dest_dir, cookies_file):
        with self.lock:
            self.calls.append((video_id, cookies_file))
        if self.delay:
            time.sleep(self.delay)
        if video_id in self.fail:
            raise AudioUnavailable(f"{video_id} is unavailable")
        path = dest_dir / f"{video_id}.webm"
        path.write_bytes(b"x" * self.size)
        return path


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make(tmp_path, downloader, cookies=None, max_bytes=10_000):
    return AudioCache(tmp_path / "cache", cookies, max_bytes, downloader=downloader)


async def test_ensure_downloads_once_then_serves_cache(tmp_path):
    dl = FakeDownloader()
    cache = make(tmp_path, dl)
    first = await cache.ensure("aaaaaaaaaaa")
    second = await cache.ensure("aaaaaaaaaaa")
    assert first == second == tmp_path / "cache" / "aaaaaaaaaaa.webm"
    assert first.read_bytes() == b"x" * 100
    assert len(dl.calls) == 1
    assert cache.cached("aaaaaaaaaaa") == first


async def test_concurrent_ensure_downloads_once(tmp_path):
    dl = FakeDownloader(delay=0.2)
    cache = make(tmp_path, dl)
    results = []

    async def get():
        results.append(await cache.ensure("aaaaaaaaaaa"))

    async with anyio.create_task_group() as tg:
        for _ in range(3):
            tg.start_soon(get)
    assert len(dl.calls) == 1
    assert len(set(results)) == 1


async def test_ensure_unavailable_raises(tmp_path):
    cache = make(tmp_path, FakeDownloader(fail={"bbbbbbbbbbb"}))
    with pytest.raises(AudioUnavailable):
        await cache.ensure("bbbbbbbbbbb")
    assert cache.cached("bbbbbbbbbbb") is None


async def test_failed_download_can_be_retried(tmp_path):
    dl = FakeDownloader(fail={"bbbbbbbbbbb"})
    cache = make(tmp_path, dl)
    with pytest.raises(AudioUnavailable):
        await cache.ensure("bbbbbbbbbbb")
    dl.fail.clear()
    assert (await cache.ensure("bbbbbbbbbbb")).is_file()


async def test_cookies_passed_only_when_file_exists(tmp_path):
    cookies = tmp_path / "cookies.txt"
    dl = FakeDownloader()
    cache = make(tmp_path, dl, cookies=cookies)
    await cache.ensure("aaaaaaaaaaa")
    cookies.write_text("# Netscape HTTP Cookie File\n")
    await cache.ensure("ccccccccccc")
    assert dl.calls == [("aaaaaaaaaaa", None), ("ccccccccccc", cookies)]


async def test_prune_evicts_lru_but_keeps_pinned(tmp_path):
    dl = FakeDownloader(size=400)
    cache = make(tmp_path, dl, max_bytes=1000)
    ids = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"]
    for i, vid in enumerate(ids):
        path = await cache.ensure(vid)
        os.utime(path, (1000 + i, 1000 + i))  # a is oldest, d newest
    cache.prune(keep={"aaaaaaaaaaa"})
    remaining = {vid for vid in ids if cache.cached(vid)}
    assert remaining == {"aaaaaaaaaaa", "ddddddddddd"}  # 800 bytes; oldest unpinned (b, c) evicted


def test_partial_files_ignored(tmp_path):
    cache = make(tmp_path, FakeDownloader())
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "aaaaaaaaaaa.webm.part").write_bytes(b"x")
    (tmp_path / "cache" / "aaaaaaaaaaa.webm.ytdl").write_bytes(b"x")
    assert cache.cached("aaaaaaaaaaa") is None
