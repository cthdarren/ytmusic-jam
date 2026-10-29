"""Turn a Spotify track link into the matching YouTube Music song.

Spotify's public embed page carries the track's name, artists and duration in its
__NEXT_DATA__ JSON, so no API keys are needed. Matching then searches YouTube Music
and ranks results by title, artist and how close the duration is.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import urlparse

from app.models import Track
from app.ytm import UpstreamError

SPOTIFY_ID_RE = re.compile(r"[A-Za-z0-9]{22}")
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MIN_SCORE = 0.6
MIN_TITLE_SIMILARITY = 0.4


class SpotifyNotATrack(ValueError):
    """A Spotify link to something other than a single song (album, playlist, episode...)."""


@dataclass
class SpotifyTrack:
    name: str
    artists: list[str]
    duration_ms: int | None


def parse_spotify(text: str) -> str | None:
    """Spotify track id from a link or `spotify:track:` URI; None if it isn't a Spotify link."""
    text = text.strip()
    if text.startswith("spotify:"):
        parts = text.split(":")
        kind, item = (parts[1], parts[2]) if len(parts) >= 3 else ("", "")
    else:
        url = urlparse(text if "://" in text else "https://" + text)
        if (url.hostname or "").lower() != "open.spotify.com":
            return None
        segments = [s for s in url.path.split("/") if s]
        if segments and segments[0].startswith("intl-"):
            segments = segments[1:]
        kind, item = (segments[0], segments[1]) if len(segments) >= 2 else ("", "")
    if not SPOTIFY_ID_RE.fullmatch(item):
        return None
    if kind != "track":
        raise SpotifyNotATrack(kind)
    return item


def parse_embed_page(html: str) -> SpotifyTrack:
    match = NEXT_DATA_RE.search(html)
    try:
        entity = json.loads(match.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
        name = entity["name"]
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise UpstreamError("Spotify page didn't contain the song details") from e
    artists = [a["name"] for a in entity.get("artists") or [] if a.get("name")]
    duration = entity.get("duration")
    return SpotifyTrack(name, artists, int(duration) if duration else None)


def fetch_spotify_track(track_id: str) -> SpotifyTrack:
    """Read a track's details from Spotify's public embed page. Blocking."""
    request = urllib.request.Request(f"https://open.spotify.com/embed/track/{track_id}",
                                     headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            html = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise LookupError(track_id) from e
        raise UpstreamError(f"Spotify returned {e.code}") from e
    except OSError as e:
        raise UpstreamError(str(e)) from e
    return parse_embed_page(html)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _core_title(title: str) -> str:
    """Title without "(Remastered)", "[Live]", " - From the movie…" and "feat." tails."""
    title = re.sub(r"[(\[].*?[)\]]", " ", title)
    title = re.split(r" - |\bfeat\.|\bft\.", title, maxsplit=1)[0]
    return _normalise(title)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return max(0.9, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


def _title_similarity(wanted: str, candidate: str) -> float:
    return max(_similarity(_normalise(wanted), _normalise(candidate)),
               _similarity(_core_title(wanted), _core_title(candidate)))


def _artist_similarity(wanted: list[str], candidate: str) -> float:
    candidate = _normalise(candidate)
    return max((_similarity(_normalise(a), candidate) for a in wanted), default=0.0)


def _duration_penalty(wanted_ms: int | None, candidate_s: int | None) -> float:
    """0 within 3 s, rising to 1 at 30 s apart; unknown durations don't count."""
    if wanted_ms is None or candidate_s is None:
        return 0.0
    gap = abs(candidate_s - wanted_ms / 1000)
    return min(1.0, max(0.0, gap - 3) / 27)


def best_match(track: SpotifyTrack, candidates: list[Track]) -> Track | None:
    best, best_score = None, MIN_SCORE
    for candidate in candidates:
        title = _title_similarity(track.name, candidate.title)
        if title < MIN_TITLE_SIMILARITY:
            continue
        score = (title + _artist_similarity(track.artists, candidate.artist)
                 - _duration_penalty(track.duration_ms, candidate.duration_seconds))
        if score > best_score:
            best, best_score = candidate, score
    return best
