import pytest

from app.models import Track
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
    def __init__(self, search_rows=(), song=None, error=None):
        self.search_rows = list(search_rows)
        self.song = song
        self.error = error
        self.calls = []

    def search(self, query, filter=None, limit=20):
        self.calls.append((query, filter, limit))
        if self.error:
            raise self.error
        return self.search_rows

    def get_song(self, video_id):
        if self.error:
            raise self.error
        return self.song


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
