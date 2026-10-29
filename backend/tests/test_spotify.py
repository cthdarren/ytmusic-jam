import json

import pytest

from app.models import Track
from app.spotify import SpotifyNotATrack, SpotifyTrack, best_match, parse_embed_page, parse_spotify
from app.ytm import UpstreamError

ID = "4cOdK2wGLETKBW3PvgPWqT"


@pytest.mark.parametrize("text", [
    f"https://open.spotify.com/track/{ID}",
    f"https://open.spotify.com/track/{ID}?si=abc123def",
    f"  open.spotify.com/track/{ID}  ",
    f"https://open.spotify.com/intl-de/track/{ID}",
    f"spotify:track:{ID}",
])
def test_parses_spotify_track_links(text):
    assert parse_spotify(text) == ID


@pytest.mark.parametrize("text", [
    "", "daft punk", "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://open.spotify.com/track/short", "https://example.com/track/" + ID,
])
def test_ignores_other_text(text):
    assert parse_spotify(text) is None


@pytest.mark.parametrize("text", [
    f"https://open.spotify.com/album/{ID}",
    f"https://open.spotify.com/playlist/{ID}",
    f"https://open.spotify.com/episode/{ID}",
    f"spotify:playlist:{ID}",
])
def test_rejects_non_track_spotify_links(text):
    with pytest.raises(SpotifyNotATrack):
        parse_spotify(text)


def embed_html(entity):
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def test_parse_embed_page():
    html = embed_html({"name": "Never Gonna Give You Up", "artists": [{"name": "Rick Astley"}], "duration": 213573})
    assert parse_embed_page(html) == SpotifyTrack("Never Gonna Give You Up", ["Rick Astley"], 213573)


def test_parse_embed_page_missing_data_raises_upstream():
    with pytest.raises(UpstreamError):
        parse_embed_page("<html>new layout</html>")
    with pytest.raises(UpstreamError):
        parse_embed_page(embed_html({"artists": []}))


def song(vid, title, artist, seconds):
    return Track(video_id=vid, title=title, artist=artist, duration_seconds=seconds)


def test_prefers_matching_duration_and_artist():
    wanted = SpotifyTrack("Never Gonna Give You Up", ["Rick Astley"], 213_573)
    candidates = [
        song("cover000000", "Never Gonna Give You Up", "Some Cover Band", 190),
        song("live0000000", "Never Gonna Give You Up (Live)", "Rick Astley", 260),
        song("original000", "Never Gonna Give You Up", "Rick Astley", 214),
    ]
    assert best_match(wanted, candidates).video_id == "original000"


def test_tolerates_feat_and_remaster_suffixes():
    wanted = SpotifyTrack("Sunflower - Spider-Man: Into the Spider-Verse", ["Post Malone", "Swae Lee"], 158_040)
    candidates = [
        song("unrelated00", "Sunflower", "Rex Orange County", 250),
        song("right000000", "Sunflower (Spider-Man: Into the Spider-Verse)", "Post Malone & Swae Lee", 158),
    ]
    assert best_match(wanted, candidates).video_id == "right000000"


def test_unknown_durations_are_neutral():
    wanted = SpotifyTrack("Violeta", ["IZ*ONE"], None)
    candidates = [song("violeta0000", "비올레타 Violeta", "IZ*ONE", None)]
    assert best_match(wanted, candidates).video_id == "violeta0000"


def test_no_good_match_returns_none():
    wanted = SpotifyTrack("Bohemian Rhapsody", ["Queen"], 354_000)
    assert best_match(wanted, [song("nope0000000", "Baby Shark", "Pinkfong", 80)]) is None
    assert best_match(wanted, []) is None


def test_short_titles_do_not_match_by_containment():
    wanted = SpotifyTrack("i", ["Kendrick Lamar"], 232_000)
    candidates = [song("kingkunta00", "King Kunta", "Kendrick Lamar", 234), song("alright0000", "Alright", "Kendrick Lamar", 219)]
    assert best_match(wanted, candidates) is None


def test_similar_title_by_another_artist_is_not_a_match():
    wanted = SpotifyTrack("Home", ["Bebe Rexha"], 200_000)
    assert best_match(wanted, [song("homesick000", "Homesick", "Dua Lipa", 205)]) is None


def test_prefers_the_original_over_a_remix_of_the_same_length():
    wanted = SpotifyTrack("Levitating", ["Dua Lipa"], 203_000)
    candidates = [song("remix000000", "Levitating (Remix)", "Dua Lipa", 203), song("original000", "Levitating", "Dua Lipa", 203)]
    assert best_match(wanted, candidates).video_id == "original000"


@pytest.mark.parametrize("entity", [
    {"name": "Song", "artists": [None]},
    {"name": "Song", "artists": "Rick Astley"},
    {"name": "Song", "artists": [{"name": 5}]},
    {"name": "Song", "artists": [{"name": "A"}], "duration": "12a"},
    {"name": None, "artists": [{"name": "A"}]},
    {"name": "", "artists": [{"name": "A"}]},
])
def test_parse_embed_page_rejects_malformed_fields(entity):
    with pytest.raises(UpstreamError):
        parse_embed_page(embed_html(entity))


@pytest.mark.parametrize("error, expected", [
    ("http404", LookupError),
    ("http500", UpstreamError),
    ("timeout", UpstreamError),
    ("truncated", UpstreamError),
])
def test_fetch_maps_network_errors(monkeypatch, error, expected):
    import http.client
    import urllib.error

    from app import spotify

    def urlopen(*args, **kwargs):
        if error == "http404":
            raise urllib.error.HTTPError("u", 404, "Not Found", None, None)
        if error == "http500":
            raise urllib.error.HTTPError("u", 500, "Oops", None, None)
        if error == "timeout":
            raise urllib.error.URLError("timed out")
        raise http.client.IncompleteRead(b"partial")

    monkeypatch.setattr(spotify.urllib.request, "urlopen", urlopen)
    with pytest.raises(expected):
        spotify.fetch_spotify_track(ID)
