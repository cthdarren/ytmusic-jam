from typing import Any, Literal

from ytmusicapi import YTMusic

from app.models import Track


class UpstreamError(Exception):
    """YouTube Music could not be reached or returned something unexpected."""


class YTMClient:
    """Unauthenticated YouTube Music lookups. Methods are blocking."""

    def __init__(self, yt: YTMusic | None = None) -> None:
        self.yt = yt if yt is not None else YTMusic()

    def search(self, query: str, kind: Literal["songs", "videos"] = "songs", limit: int = 20) -> list[Track]:
        try:
            rows = self.yt.search(query, filter=kind, limit=limit)
        except Exception as e:
            raise UpstreamError(str(e)) from e
        return [_track_from_search(r) for r in rows if r.get("videoId")][:limit]

    def get_track(self, video_id: str) -> Track:
        try:
            song = self.yt.get_song(video_id)
        except Exception as e:
            raise UpstreamError(str(e)) from e
        details = song.get("videoDetails")
        if not details:
            raise LookupError(f"Video {video_id} not found")
        thumbs = (details.get("thumbnail") or {}).get("thumbnails") or []
        length = details.get("lengthSeconds")
        return Track(
            video_id=details.get("videoId", video_id),
            title=details.get("title", ""),
            artist=details.get("author", ""),
            duration_seconds=int(length) if length else None,
            thumbnail_url=thumbs[-1]["url"] if thumbs else None,
        )


def _track_from_search(row: dict[str, Any]) -> Track:
    thumbs = row.get("thumbnails") or []
    return Track(
        video_id=row["videoId"],
        title=row.get("title", ""),
        artist=", ".join(a["name"] for a in row.get("artists") or []),
        duration_seconds=row.get("duration_seconds"),
        thumbnail_url=thumbs[-1]["url"] if thumbs else None,
    )
