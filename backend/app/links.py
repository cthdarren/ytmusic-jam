import re
from urllib.parse import parse_qs, urlparse

VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


def parse_video_id(text: str) -> str | None:
    """Extract an 11-char YouTube video id from a link or a bare id."""
    text = text.strip()
    if VIDEO_ID_RE.fullmatch(text):
        return text
    if "://" not in text:
        text = "https://" + text

    url = urlparse(text)
    host = (url.hostname or "").lower()
    segments = [s for s in url.path.split("/") if s]

    candidate = None
    if host == "youtu.be":
        candidate = segments[0] if segments else None
    elif host in YOUTUBE_HOSTS:
        if segments[:1] == ["watch"]:
            candidate = parse_qs(url.query).get("v", [None])[0]
        elif len(segments) >= 2 and segments[0] in ("shorts", "embed"):
            candidate = segments[1]

    if candidate and VIDEO_ID_RE.fullmatch(candidate):
        return candidate
    return None
