import threading
import time

import pytest
from ytmusicapi.models.lyrics import LyricLine as YTLyricLine

from app.models import LyricLine, Track
from app.ytm import UpstreamError, YTMClient

SEARCH_ROW = {
    "videoId": "aaaaaaaaaaa",
    "title": "One More Time",
    "artists": [{"name": "Daft", "id": "x"}, {"name": "Punk", "id": "y"}],
    "duration_seconds": 320,
    "thumbnails": [
        {"url": "https://img/small", "width": 60, "height": 60},
        {"url": "https://img/large", "width": 120, "height": 120},
    ],
}

SONG = {
    "videoDetails": {
        "videoId": "bbbbbbbbbbb",
        "title": "Around the World",
        "author": "Daft Punk",
        "lengthSeconds": "215",
        "thumbnail": {"thumbnails": [{"url": "https://img/s"}, {"url": "https://img/l"}]},
    }
}


class FakeYT:
    def __init__(self, search_rows=(), song=None, error=None, lyrics_id=None, lyrics=None):
        self.search_rows = list(search_rows)
        self.song = song
        self.error = error
        self.lyrics_id = lyrics_id
        self.lyrics = lyrics
        self.calls = []
        self.lyrics_calls = []  # (browseId, timestamps) per get_lyrics call

    def search(self, query, filter=None, limit=20):
        self.calls.append((query, filter, limit))
        if self.error:
            raise self.error
        return self.search_rows

    def get_song(self, video_id):
        if self.error:
            raise self.error
        return self.song

    def get_watch_playlist(self, videoId=None, limit=25):
        if self.error:
            raise self.error
        return {"tracks": [], "lyrics": self.lyrics_id}

    def get_lyrics(self, browseId, timestamps=False):
        self.lyrics_calls.append((browseId, timestamps))
        return self.lyrics


def test_search_maps_fields():
    yt = FakeYT([SEARCH_ROW])
    tracks = YTMClient(yt).search("daft punk")
    assert tracks == [Track(video_id="aaaaaaaaaaa", title="One More Time", artist="Daft, Punk",
                            duration_seconds=320, thumbnail_url="https://img/large")]
    assert yt.calls == [("daft punk", "songs", 20)]


def test_search_passes_kind_and_truncates_to_limit():
    yt = FakeYT([SEARCH_ROW] * 5)
    assert len(YTMClient(yt).search("x", kind="videos", limit=3)) == 3
    assert yt.calls == [("x", "videos", 3)]


def test_search_skips_results_without_video_id():
    yt = FakeYT([{**SEARCH_ROW, "videoId": None}, SEARCH_ROW])
    assert [t.video_id for t in YTMClient(yt).search("x")] == ["aaaaaaaaaaa"]


def test_search_tolerates_missing_optional_fields():
    row = {"videoId": "ccccccccccc", "title": "Bare"}
    assert YTMClient(FakeYT([row])).search("x") == [
        Track(video_id="ccccccccccc", title="Bare", artist="", duration_seconds=None, thumbnail_url=None)
    ]


def test_get_track_maps_fields():
    assert YTMClient(FakeYT(song=SONG)).get_track("bbbbbbbbbbb") == Track(
        video_id="bbbbbbbbbbb", title="Around the World", artist="Daft Punk",
        duration_seconds=215, thumbnail_url="https://img/l")


def test_get_track_missing_details_raises_lookup():
    with pytest.raises(LookupError):
        YTMClient(FakeYT(song={"playabilityStatus": {"status": "ERROR"}})).get_track("bbbbbbbbbbb")


def test_upstream_exception_wrapped():
    client = YTMClient(FakeYT(error=RuntimeError("boom")))
    with pytest.raises(UpstreamError):
        client.search("x")
    with pytest.raises(UpstreamError):
        client.get_track("bbbbbbbbbbb")


TIMED = {
    "lyrics": [YTLyricLine("Hello", 9200, 10630, 1), YTLyricLine(" World ", 10680, 12540, 2),
               YTLyricLine("", 13000, 14000, 3)],
    "source": "Source: LyricFind",
    "hasTimestamps": True,
}


def test_synced_lyrics_from_timestamps():
    yt = FakeYT(lyrics_id="MPLYt_x", lyrics=TIMED)
    assert YTMClient(yt).get_synced_lyrics("bbbbbbbbbbb") == [
        LyricLine(start_ms=9200, text="Hello"), LyricLine(start_ms=10680, text="World")]
    assert yt.lyrics_calls == [("MPLYt_x", True)]


def test_synced_lyrics_none_without_browse_id():
    yt = FakeYT(lyrics_id=None, lyrics=TIMED)
    assert YTMClient(yt).get_synced_lyrics("bbbbbbbbbbb") == []
    assert yt.lyrics_calls == []


def test_synced_lyrics_ignores_unsynced():
    yt = FakeYT(lyrics_id="MPLYt_x", lyrics={"lyrics": "Hello\nWorld", "source": None, "hasTimestamps": False})
    assert YTMClient(yt).get_synced_lyrics("bbbbbbbbbbb") == []


def test_synced_lyrics_none_when_youtube_has_nothing():
    assert YTMClient(FakeYT(lyrics_id="MPLYt_x", lyrics=None)).get_synced_lyrics("bbbbbbbbbbb") == []


def test_synced_lyrics_wraps_errors():
    with pytest.raises(UpstreamError):
        YTMClient(FakeYT(error=RuntimeError("boom"))).get_synced_lyrics("bbbbbbbbbbb")


def test_synced_lyrics_drops_music_note_lines():
    timed = {**TIMED, "lyrics": [YTLyricLine("♪", 0, 6000, 1), YTLyricLine("Ah ah", 6980, 9000, 2),
                                 YTLyricLine(" ♪ ♪ ", 9100, 12000, 3), YTLyricLine("눈 감아도", 12000, 14000, 4)]}
    assert YTMClient(FakeYT(lyrics_id="MPLYt_x", lyrics=timed)).get_synced_lyrics("bbbbbbbbbbb") == [
        LyricLine(start_ms=6980, text="Ah ah"), LyricLine(start_ms=12000, text="눈 감아도")]


class OverlapYT(FakeYT):
    """Sleeps in every call and records how many calls were inside YTMusic at once."""

    def __init__(self):
        super().__init__(search_rows=[SEARCH_ROW], song=SONG, lyrics_id="MPLYt_x", lyrics=TIMED)
        self.lock = threading.Lock()
        self.inside = 0
        self.max_inside = 0

    def _enter(self):
        with self.lock:
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)
        time.sleep(0.02)
        with self.lock:
            self.inside -= 1

    def search(self, *args, **kwargs):
        self._enter()
        return super().search(*args, **kwargs)

    def get_song(self, video_id):
        self._enter()
        return super().get_song(video_id)

    def get_lyrics(self, browseId, timestamps=False):
        # Lyrics with timestamps switch the shared client to Android mode while they run
        # (ytmusicapi's as_mobile, "not thread-safe"), so nothing may run alongside them.
        self._enter()
        return super().get_lyrics(browseId, timestamps)


def test_calls_into_ytmusic_never_overlap():
    yt = OverlapYT()
    client = YTMClient(yt)
    calls = [lambda: client.get_synced_lyrics("bbbbbbbbbbb"), lambda: client.search("x"),
             lambda: client.get_track("bbbbbbbbbbb")] * 3
    threads = [threading.Thread(target=call) for call in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert yt.max_inside == 1
