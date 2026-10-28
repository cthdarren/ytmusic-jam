import os

import anyio
import pytest

from app.audio import AudioCache, AudioUnavailable
from tests.conftest import FakeDownloader

pytestmark = pytest.mark.anyio


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
    assert first.stat().st_size == 100
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
    assert dl.calls[0] == ("aaaaaaaaaaa", None)
    assert dl.calls[1][0] == "ccccccccccc" and dl.calls[1][1] is not None  # a private copy of cookies


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


async def test_different_songs_download_in_parallel(tmp_path):
    import time

    cache = make(tmp_path, FakeDownloader(delay=0.3))
    start = time.monotonic()
    async with anyio.create_task_group() as tg:
        for vid in ("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"):
            tg.start_soon(cache.ensure, vid)
    assert time.monotonic() - start < 0.6  # serial would take 0.9 s


class CookieWritingDownloader(FakeDownloader):
    """Like yt-dlp: reads the cookie file it is given and rewrites it when done."""

    def __call__(self, video_id, dest_dir, cookies_file):
        if cookies_file is not None:
            assert cookies_file.read_text().startswith("# Netscape")
            cookies_file.write_text(cookies_file.read_text() + f"refreshed-by-{video_id}\n")
        return super().__call__(video_id, dest_dir, cookies_file)


async def test_each_download_gets_its_own_cookie_copy_and_refreshes_are_kept(tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    dl = CookieWritingDownloader()
    cache = make(tmp_path, dl, cookies=cookies)
    await cache.ensure("aaaaaaaaaaa")
    used = dl.calls[0][1]
    assert used is not None and used != cookies
    assert "refreshed-by-aaaaaaaaaaa" in cookies.read_text()
    assert not used.exists()  # temp copy cleaned up


async def test_read_only_cookie_file_still_downloads(tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    cookies.chmod(0o444)
    try:
        cache = make(tmp_path, CookieWritingDownloader(), cookies=cookies)
        assert (await cache.ensure("aaaaaaaaaaa")).is_file()
        assert cookies.read_text() == "# Netscape HTTP Cookie File\n"
    finally:
        cookies.chmod(0o644)
