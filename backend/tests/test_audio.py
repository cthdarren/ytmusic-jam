import asyncio
import os
import time

import anyio
import pytest

from app.audio import AudioCache, AudioPaused, AudioUnavailable, Preloader
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
        recent = time.time() - 60 + i
        os.utime(path, (recent, recent))  # a is oldest, d newest; all used within the last minute
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

    def __call__(self, video_id, dest_dir, cookies_file, cancel=None):
        if cookies_file is not None:
            assert cookies_file.read_text().startswith("# Netscape")
            cookies_file.write_text(cookies_file.read_text() + f"refreshed-by-{video_id}\n")
        return super().__call__(video_id, dest_dir, cookies_file, cancel)


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


async def wait_until(condition, timeout=3.0):
    with anyio.fail_after(timeout):
        while not condition():
            await anyio.sleep(0.01)


def downloaded_in_order(dl):
    return [vid for vid, _ in dl.calls]


async def test_preloads_in_priority_order(tmp_path):
    dl = FakeDownloader(delay=0.05)
    preloader = Preloader(make(tmp_path, dl), concurrency=1)
    preloader.update(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"])
    await wait_until(lambda: len(dl.calls) == 3 and preloader.idle)
    assert downloaded_in_order(dl) == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
    await preloader.close()


async def test_reprioritises_after_update(tmp_path):
    dl = FakeDownloader(delay=0.2)
    cache = make(tmp_path, dl)
    preloader = Preloader(cache, concurrency=1)
    preloader.update(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"])
    await anyio.sleep(0.1)  # a is downloading
    preloader.update(["ddddddddddd", "ccccccccccc"])  # someone jumped ahead
    await wait_until(lambda: cache.cached("ccccccccccc") is not None and preloader.idle)
    assert downloaded_in_order(dl) == ["aaaaaaaaaaa", "ddddddddddd", "ccccccccccc"]
    await preloader.close()


async def test_failed_song_not_retried_immediately(tmp_path):
    dl = FakeDownloader(fail={"bbbbbbbbbbb"})
    preloader = Preloader(make(tmp_path, dl), concurrency=2)
    wanted = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
    preloader.update(wanted)
    await wait_until(lambda: len(dl.calls) == 3 and preloader.idle)
    preloader.update(wanted)
    await anyio.sleep(0.2)
    assert downloaded_in_order(dl).count("bbbbbbbbbbb") == 1
    await preloader.close()


async def test_failed_song_retried_after_backoff(tmp_path):
    dl = FakeDownloader(fail={"bbbbbbbbbbb"})
    cache = make(tmp_path, dl)
    preloader = Preloader(cache, concurrency=1, retry_after=0.05)
    preloader.update(["bbbbbbbbbbb"])
    await wait_until(lambda: len(dl.calls) == 1 and preloader.idle)
    dl.fail.clear()
    preloader.update(["bbbbbbbbbbb"])
    await wait_until(lambda: cache.cached("bbbbbbbbbbb") is not None)
    await preloader.close()


async def test_prunes_to_wanted_when_idle(tmp_path):
    dl = FakeDownloader(size=400)
    cache = make(tmp_path, dl, max_bytes=1000)
    for old in ("xxxxxxxxxxx", "yyyyyyyyyyy"):
        recent = time.time() - 60
        os.utime(await cache.ensure(old), (recent, recent))  # older than a/b, but not stale
    preloader = Preloader(cache, concurrency=2)
    preloader.update(["aaaaaaaaaaa", "bbbbbbbbbbb"])
    await wait_until(lambda: preloader.idle and cache.cached("bbbbbbbbbbb") is not None and cache.cached("xxxxxxxxxxx") is None)
    assert cache.cached("aaaaaaaaaaa") and cache.cached("bbbbbbbbbbb")
    assert cache.cached("yyyyyyyyyyy") is None
    await preloader.close()


async def test_prune_deletes_stale_files(tmp_path):
    cache = make(tmp_path, FakeDownloader(), max_bytes=10**9)
    two_hours_ago = time.time() - 7200
    for vid in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        os.utime(await cache.ensure(vid), (two_hours_ago, two_hours_ago))
    await cache.ensure("ccccccccccc")
    cache.prune(keep={"aaaaaaaaaaa"}, max_age_seconds=3600)
    assert cache.cached("aaaaaaaaaaa") is not None  # pinned
    assert cache.cached("bbbbbbbbbbb") is None  # stale
    assert cache.cached("ccccccccccc") is not None  # fresh


async def test_clear_removes_downloaded_songs(tmp_path):
    cache = make(tmp_path, FakeDownloader())
    await cache.ensure("aaaaaaaaaaa")
    await cache.ensure("bbbbbbbbbbb")
    cache.clear()
    assert list((tmp_path / "cache").iterdir()) == []


class FlakyPruneCache(AudioCache):
    """A cache whose first prune hits a disk error."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prune_calls = 0

    def prune(self, keep, max_age_seconds=86400):
        self.prune_calls += 1
        if self.prune_calls == 1:
            raise OSError("EIO")
        super().prune(keep, max_age_seconds)


async def test_worker_survives_a_disk_error(tmp_path):
    cache = FlakyPruneCache(tmp_path / "cache", None, 10_000, downloader=FakeDownloader())
    preloader = Preloader(cache, concurrency=1)
    preloader.update(["aaaaaaaaaaa"])
    await wait_until(lambda: cache.prune_calls >= 1)
    preloader.update(["aaaaaaaaaaa", "bbbbbbbbbbb"])
    await wait_until(lambda: cache.cached("bbbbbbbbbbb") is not None)
    await preloader.close()


async def test_idle_prune_runs_on_a_timer(tmp_path):
    cache = make(tmp_path, FakeDownloader(), max_bytes=10**9)
    preloader = Preloader(cache, concurrency=1, idle_timeout=0.05)
    preloader.update(["aaaaaaaaaaa"])
    await wait_until(lambda: preloader.idle and cache.cached("aaaaaaaaaaa") is not None)
    stale = await cache.ensure("bbbbbbbbbbb")
    os.utime(stale, (time.time() - 2 * 86400,) * 2)
    await wait_until(lambda: cache.cached("bbbbbbbbbbb") is None)  # no update() needed
    await preloader.close()


async def test_failed_song_retried_without_another_update(tmp_path):
    dl = FakeDownloader(fail={"bbbbbbbbbbb"})
    preloader = Preloader(make(tmp_path, dl), concurrency=1, retry_after=0.05)
    preloader.update(["bbbbbbbbbbb"])
    await wait_until(lambda: len(dl.calls) == 1)
    dl.fail.clear()
    await wait_until(lambda: len(dl.calls) == 2)
    await preloader.close()


async def test_download_that_cannot_be_found_is_not_redownloaded_in_a_loop(tmp_path):
    class OddExtension(FakeDownloader):
        def __call__(self, video_id, dest_dir, cookies_file, cancel=None):
            super().__call__(video_id, dest_dir, cookies_file, cancel).rename(dest_dir / f"{video_id}.mka")
            return dest_dir / f"{video_id}.mka"

    dl = OddExtension()
    preloader = Preloader(make(tmp_path, dl), concurrency=1)
    preloader.update(["aaaaaaaaaaa"])
    await wait_until(lambda: len(dl.calls) >= 1)
    await anyio.sleep(0.2)
    assert len(dl.calls) == 1
    await preloader.close()


async def test_reset_forgets_failures(tmp_path):
    dl = FakeDownloader(fail={"aaaaaaaaaaa"})
    preloader = Preloader(make(tmp_path, dl), concurrency=1)
    preloader.update(["aaaaaaaaaaa"])
    await wait_until(lambda: len(dl.calls) == 1 and preloader.idle)
    dl.fail.clear()
    preloader.reset()
    preloader.update(["aaaaaaaaaaa"])
    await wait_until(lambda: len(dl.calls) == 2)
    await preloader.close()


def test_clear_leaves_in_progress_downloads(tmp_path):
    cache = make(tmp_path, FakeDownloader())
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "aaaaaaaaaaa.webm").write_bytes(b"x")
    (tmp_path / "cache" / "bbbbbbbbbbb.webm.part").write_bytes(b"x")
    cache.clear()
    assert [p.name for p in (tmp_path / "cache").iterdir()] == ["bbbbbbbbbbb.webm.part"]


async def test_on_change_called_after_download_prune_and_clear(tmp_path):
    changes = []
    cache = make(tmp_path, FakeDownloader(size=400), max_bytes=500)
    cache.on_change = lambda: changes.append(1)
    await cache.ensure("aaaaaaaaaaa")
    assert len(changes) == 1
    await cache.ensure("aaaaaaaaaaa")  # already cached: nothing changed
    assert len(changes) == 1
    await cache.ensure("bbbbbbbbbbb")
    assert len(changes) == 2
    cache.prune(keep={"bbbbbbbbbbb"})  # over the cap: a goes
    assert len(changes) == 3
    cache.prune(keep={"bbbbbbbbbbb"})  # nothing to delete
    assert len(changes) == 3
    cache.clear()
    assert len(changes) == 4
    cache.clear()
    assert len(changes) == 4


async def test_ready_ids(tmp_path):
    cache = make(tmp_path, FakeDownloader())
    assert cache.ready_ids() == set()
    await cache.ensure("aaaaaaaaaaa")
    (tmp_path / "cache" / "bbbbbbbbbbb.webm.part").write_bytes(b"x")
    assert cache.ready_ids() == {"aaaaaaaaaaa"}


class RecordingDownloader(FakeDownloader):
    """Remembers how many other downloads were running when each one started."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.started_alongside = {}

    def __call__(self, video_id, dest_dir, cookies_file, cancel=None):
        with self.lock:
            self.started_alongside[video_id] = self.active
        return super().__call__(video_id, dest_dir, cookies_file, cancel)


async def test_playing_and_next_song_download_alone_first(tmp_path):
    dl = RecordingDownloader(delay=0.15)
    cache = make(tmp_path, dl)
    preloader = Preloader(cache, concurrency=4)
    wanted = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd", "eeeeeeeeeee"]
    preloader.update(wanted)
    await wait_until(lambda: all(cache.cached(v) for v in wanted) and preloader.idle)
    assert downloaded_in_order(dl)[:2] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert dl.started_alongside["aaaaaaaaaaa"] == 0
    assert dl.started_alongside["bbbbbbbbbbb"] == 0  # the next song gets the connection to itself
    assert dl.max_active == 3  # then c, d and e go together
    await preloader.close()


async def test_next_song_first_when_playing_song_is_already_cached(tmp_path):
    dl = RecordingDownloader(delay=0.15)
    cache = make(tmp_path, dl)
    await cache.ensure("aaaaaaaaaaa")
    dl.calls.clear()
    preloader = Preloader(cache, concurrency=4)
    preloader.update(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"])
    await wait_until(lambda: cache.cached("ddddddddddd") is not None and preloader.idle)
    assert downloaded_in_order(dl)[0] == "bbbbbbbbbbb"
    assert dl.max_active == 2  # b alone, then c and d together
    await preloader.close()


async def test_failed_next_song_does_not_block_the_rest(tmp_path):
    dl = FakeDownloader(fail={"bbbbbbbbbbb"})
    cache = make(tmp_path, dl)
    preloader = Preloader(cache, concurrency=4)
    preloader.update(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"])
    await wait_until(lambda: cache.cached("ccccccccccc") is not None)
    await preloader.close()


async def test_urgent_song_starts_without_waiting_for_older_downloads(tmp_path):
    dl = RecordingDownloader(delay=0.4)
    cache = make(tmp_path, dl)
    preloader = Preloader(cache, concurrency=4)
    preloader.update(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd", "eeeeeeeeeee"])
    await wait_until(lambda: {"ccccccccccc", "ddddddddddd", "eeeeeeeeeee"} <= {v for v, _ in dl.calls})
    preloader.update(["zzzzzzzzzzz"])  # someone jumped to a new song while c, d, e download
    await anyio.sleep(0.1)
    assert "zzzzzzzzzzz" in {v for v, _ in dl.calls}  # started right away, not after c, d, e
    await preloader.close()


async def test_pause_others_stops_downloads_except_the_kept_ones(tmp_path):
    dl = FakeDownloader(delay=0.5)
    cache = make(tmp_path, dl)
    a = asyncio.ensure_future(cache.ensure("aaaaaaaaaaa"))
    b = asyncio.ensure_future(cache.ensure("bbbbbbbbbbb"))
    await wait_until(lambda: dl.active == 2)
    assert cache.pause_others(keep={"aaaaaaaaaaa"}) == {"bbbbbbbbbbb"}
    with pytest.raises(AudioPaused):
        await b
    assert (await a).is_file()
    assert dl.paused == ["bbbbbbbbbbb"]
    assert (await cache.ensure("bbbbbbbbbbb")).is_file()  # resumes on the next request


async def test_refocus_pauses_everything_but_the_playing_and_next_song(tmp_path):
    dl = RecordingDownloader(delay=0.4)
    cache = make(tmp_path, dl)
    for done in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        await cache.ensure(done)
    preloader = Preloader(cache, concurrency=4)
    preloader.update(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd", "eeeeeeeeeee"])
    await wait_until(lambda: dl.active == 3)  # c, d, e downloading together
    preloader.update(["ddddddddddd", "fffffffffff", "ccccccccccc", "eeeeeeeeeee"])  # someone tapped d
    preloader.refocus()
    await wait_until(lambda: set(dl.paused) == {"ccccccccccc", "eeeeeeeeeee"})
    await wait_until(lambda: cache.cached("fffffffffff") is not None)
    assert dl.started_alongside["fffffffffff"] == 0  # the new next song downloads alone
    # paused songs aren't failures: they resume straight after
    await wait_until(lambda: cache.cached("ccccccccccc") is not None and cache.cached("eeeeeeeeeee") is not None)
    await preloader.close()
