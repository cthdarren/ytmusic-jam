"""Timed lyrics for the host tab's title: YouTube Music first, then lrclib.net.

LRCLIB is a free, keyless database of synced lyrics in LRC format; it covers many songs
YouTube Music only has untimed lyrics for (or none, as with most music videos).
"""

import http.client
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol

from app.models import LyricLine, Track
from app.ytm import UpstreamError

log = logging.getLogger(__name__)

LRCLIB_SEARCH = "https://lrclib.net/api/search"
USER_AGENT = "YT Music Jam (self-hosted)"
# LRCLIB results whose length differs more than this belong to another version of the song.
MAX_DURATION_DIFF_SECONDS = 3
LRC_STAMP_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def parse_lrc(text: str) -> list[LyricLine]:
    """Lines of an LRC file, sorted by time. Tags like [ar:...] and blank lines are dropped."""
    lines = []
    for raw in text.splitlines():
        stamps = []
        rest = raw.strip()
        while match := LRC_STAMP_RE.match(rest):
            stamps.append(round((int(match[1]) * 60 + float(match[2])) * 1000))
            rest = rest[match.end():]
        rest = rest.strip()
        if rest:
            lines.extend(LyricLine(start_ms=ms, text=rest) for ms in stamps)
    return sorted(lines, key=lambda line: line.start_ms)


def fetch_lrclib(title: str, artist: str, duration_seconds: int | None) -> list[LyricLine]:
    """Synced lyrics from lrclib.net; empty when none match. Blocking."""
    params = {"track_name": title}
    first_artist = artist.split(", ")[0].strip()
    if first_artist:
        params["artist_name"] = first_artist
    request = urllib.request.Request(f"{LRCLIB_SEARCH}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            results = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise UpstreamError(f"LRCLIB returned {e.code}") from e
    except (OSError, http.client.HTTPException, ValueError) as e:
        raise UpstreamError(str(e)) from e
    for item in results if isinstance(results, list) else []:
        if not item.get("syncedLyrics"):
            continue
        if duration_seconds is not None and abs((item.get("duration") or 0) - duration_seconds) > MAX_DURATION_DIFF_SECONDS:
            continue
        return parse_lrc(item["syncedLyrics"])
    return []


class SyncedLyricsSource(Protocol):
    def get_synced_lyrics(self, video_id: str) -> list[LyricLine]: ...


class LyricsFinder:
    """Looks up a song's timed lyrics and remembers the answer (including "none")."""

    def __init__(self, ytm: SyncedLyricsSource, lrclib: Callable[[str, str, int | None], list[LyricLine]],
                 max_cached: int = 200) -> None:
        self.ytm = ytm
        self.lrclib = lrclib
        self.max_cached = max_cached
        self.cache: OrderedDict[str, list[LyricLine]] = OrderedDict()

    def find(self, track: Track) -> list[LyricLine]:
        """Never raises: a source that fails counts as having nothing, and isn't remembered. Blocking."""
        if track.video_id in self.cache:
            self.cache.move_to_end(track.video_id)
            return self.cache[track.video_id]
        failed = False
        try:
            lines = self.ytm.get_synced_lyrics(track.video_id)
        except UpstreamError as e:
            log.info("YouTube Music lyrics for %s failed: %s", track.video_id, e)
            failed, lines = True, []
        if not lines:
            try:
                lines = self.lrclib(track.title, track.artist, track.duration_seconds)
            except UpstreamError as e:
                log.info("LRCLIB lyrics for %s failed: %s", track.video_id, e)
                failed, lines = True, []
        if not failed:
            self.cache[track.video_id] = lines
            if len(self.cache) > self.max_cached:
                self.cache.popitem(last=False)
        return lines
