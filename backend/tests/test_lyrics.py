import io
import json
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

from app import lyrics
from app.lyrics import LyricsFinder, fetch_lrclib, parse_lrc
from app.models import LyricLine, Track
from app.ytm import UpstreamError

LRC = "[00:01.00]One\n[00:02.00]Two"
ONE_TWO = [LyricLine(start_ms=1000, text="One"), LyricLine(start_ms=2000, text="Two")]
TRACK = Track(video_id="aaaaaaaaaaa", title="Song", artist="Singer", duration_seconds=200)


def lines(*pairs):
    return [LyricLine(start_ms=ms, text=text) for ms, text in pairs]


def test_parse_lrc_basic():
    assert parse_lrc("[00:12.34] Hello\n[01:02.5]World") == lines((12340, "Hello"), (62500, "World"))


def test_parse_lrc_skips_tags_and_blank_lines():
    assert parse_lrc("[ar:X]\n[ti:Y]\n[00:01.00]\n\n[00:02.00]  Hi  ") == lines((2000, "Hi"))


def test_parse_lrc_multiple_stamps_and_sorting():
    assert parse_lrc("[00:30.00][00:10.00]Chorus\n[00:20.00]Verse") == lines(
        (10000, "Chorus"), (20000, "Verse"), (30000, "Chorus"))


class FakeLRCLIB:
    """Stands in for urlopen: answers with `results` (JSON) and records the requested URLs."""

    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.urls = []

    def __call__(self, request, timeout=None):
        self.urls.append(request.full_url)
        if self.error:
            raise self.error
        return io.BytesIO(json.dumps(self.results).encode())

    def params(self):
        return parse_qs(urlparse(self.urls[-1]).query)


@pytest.fixture
def lrclib(monkeypatch):
    fake = FakeLRCLIB()
    monkeypatch.setattr(lyrics.urllib.request, "urlopen", fake)
    return fake


def test_lrclib_picks_synced_result_with_close_duration(lrclib):
    lrclib.results = [
        {"duration": 200, "syncedLyrics": None, "plainLyrics": "One"},
        {"duration": 300, "syncedLyrics": "[00:05.00]Wrong"},
        {"duration": 201.4, "syncedLyrics": LRC},
    ]
    assert fetch_lrclib("Song", "Singer", 200) == ONE_TWO
    assert lrclib.urls[0].startswith("https://lrclib.net/api/search?")
    assert lrclib.params() == {"track_name": ["Song"], "artist_name": ["Singer"]}


def test_lrclib_accepts_any_duration_when_unknown(lrclib):
    lrclib.results = [{"duration": 300, "syncedLyrics": LRC}]
    assert fetch_lrclib("Song", "Singer", None) == ONE_TWO


def test_lrclib_nothing_matching(lrclib):
    lrclib.results = [{"duration": 300, "syncedLyrics": LRC}]
    assert fetch_lrclib("Song", "Singer", 200) == []


def test_lrclib_uses_first_artist(lrclib):
    fetch_lrclib("Song", "A, B", 200)
    assert lrclib.params()["artist_name"] == ["A"]


def test_lrclib_leaves_out_missing_artist(lrclib):
    fetch_lrclib("Song", "", 200)
    assert lrclib.params() == {"track_name": ["Song"]}


def test_lrclib_404_means_nothing(lrclib):
    lrclib.error = urllib.error.HTTPError("u", 404, "Not Found", None, None)
    assert fetch_lrclib("Song", "Singer", 200) == []


@pytest.mark.parametrize("error", [
    OSError("down"),
    urllib.error.HTTPError("u", 500, "Oops", None, None),
])
def test_lrclib_errors_raise_upstream(lrclib, error):
    lrclib.error = error
    with pytest.raises(UpstreamError):
        fetch_lrclib("Song", "Singer", 200)


class FakeYTM:
    def __init__(self, result=(), error=None):
        self.result = list(result)
        self.error = error
        self.calls = []

    def get_synced_lyrics(self, video_id):
        self.calls.append(video_id)
        if self.error:
            raise self.error
        return self.result


class FakeLRCLIBFetcher:
    def __init__(self, result=(), error=None):
        self.result = list(result)
        self.error = error
        self.calls = []

    def __call__(self, title, artist, duration_seconds):
        self.calls.append((title, artist, duration_seconds))
        if self.error:
            raise self.error
        return self.result


def test_finder_prefers_ytm():
    ytm, lrc = FakeYTM(ONE_TWO), FakeLRCLIBFetcher(lines((5, "x")))
    assert LyricsFinder(ytm, lrc).find(TRACK) == ONE_TWO
    assert ytm.calls == ["aaaaaaaaaaa"]
    assert lrc.calls == []


def test_finder_falls_back_to_lrclib():
    lrc = FakeLRCLIBFetcher(ONE_TWO)
    assert LyricsFinder(FakeYTM(), lrc).find(TRACK) == ONE_TWO
    assert lrc.calls == [("Song", "Singer", 200)]


def test_finder_falls_back_when_ytm_errors():
    assert LyricsFinder(FakeYTM(error=UpstreamError("down")), FakeLRCLIBFetcher(ONE_TWO)).find(TRACK) == ONE_TWO


def test_finder_caches_results():
    ytm, lrc = FakeYTM(), FakeLRCLIBFetcher()
    finder = LyricsFinder(ytm, lrc)
    assert finder.find(TRACK) == []
    assert finder.find(TRACK) == []
    assert (len(ytm.calls), len(lrc.calls)) == (1, 1)


def test_finder_does_not_cache_failures():
    lrc = FakeLRCLIBFetcher(error=UpstreamError("down"))
    finder = LyricsFinder(FakeYTM(), lrc)
    assert finder.find(TRACK) == []
    lrc.error, lrc.result = None, ONE_TWO
    assert finder.find(TRACK) == ONE_TWO


def test_finder_forgets_oldest_beyond_limit():
    ytm = FakeYTM(ONE_TWO)
    finder = LyricsFinder(ytm, FakeLRCLIBFetcher(), max_cached=2)
    for vid in ("a", "b", "a", "c", "a", "b"):
        finder.find(TRACK.model_copy(update={"video_id": vid}))
    assert ytm.calls == ["a", "b", "c", "b"]


def test_parse_lrc_drops_music_note_lines():
    assert parse_lrc("[00:00.00]♪\n[00:05.00]Hi\n[00:09.00] ♪ \n") == lines((5000, "Hi"))
