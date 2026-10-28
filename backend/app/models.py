from uuid import uuid4

from pydantic import BaseModel, Field


class Track(BaseModel):
    video_id: str
    title: str
    artist: str
    duration_seconds: int | None = None
    thumbnail_url: str | None = None


class QueueItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    track: Track
    added_by: str | None = None


class RoomState(BaseModel):
    played: list[QueueItem]  # oldest first; played + now_playing + queue is the whole night in order
    now_playing: QueueItem | None
    queue: list[QueueItem]
    is_playing: bool
    version: int
