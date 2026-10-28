import logging
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from app.models import QueueItem, RoomState, Track

log = logging.getLogger(__name__)


class Room:
    """The jam's playback state. Synchronous; callers keep it on one thread.

    The night is one ordered list split into `played`, `now_playing` and `queue`.
    Advancing and jumping only move the split point; they never reorder the list.
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path
        self.played: list[QueueItem] = []
        self.now_playing: QueueItem | None = None
        self.queue: list[QueueItem] = []
        self.is_playing = False
        self.version = 0
        self._load()

    def add(self, track: Track, added_by: str | None) -> QueueItem:
        item = QueueItem(track=track, added_by=added_by)
        if self.now_playing is None:
            self.now_playing = item
            self.is_playing = True
        else:
            self.queue.append(item)
        self.version += 1
        return item

    def remove(self, item_id: str) -> None:
        """Remove a played or upcoming song. The song playing has to be skipped instead."""
        if self.now_playing is not None and self.now_playing.id == item_id:
            raise ValueError("Can't remove the song that's playing")
        for songs in (self.queue, self.played):
            for i, item in enumerate(songs):
                if item.id == item_id:
                    songs.pop(i)
                    self.version += 1
                    return
        raise KeyError(item_id)

    def move(self, item_id: str, to_index: int) -> None:
        """Move any song to `to_index` in the whole night (played + now playing + upcoming).

        The song playing keeps playing wherever it lands: songs above it count as played,
        songs below it come up next.
        """
        night = self._night()
        item = night.pop(self._find(night, item_id))
        night.insert(max(0, min(to_index, len(night))), item)
        self._split_around_current(night)
        self.version += 1

    def advance(self, expected_item_id: str | None) -> bool:
        """Move to the next song, but only if `expected_item_id` is still playing.

        This makes duplicate "next" requests (two host tabs, double-tapped skip)
        skip exactly once.
        """
        current_id = self.now_playing.id if self.now_playing else None
        if expected_item_id != current_id:
            return False
        if self.now_playing is not None:
            self.played.append(self.now_playing)
        if self.queue:
            # Moving on always plays, so a stray pause reported at the end of a song can't stall the jam.
            self.now_playing = self.queue.pop(0)
            self.is_playing = True
        else:
            self.now_playing = None
            self.is_playing = False
        self.version += 1
        return True

    def jump(self, item_id: str) -> bool:
        """Play `item_id` from anywhere in the night; playback then carries on down the list."""
        if self.now_playing is not None and self.now_playing.id == item_id:
            return False
        night = self._night()
        self.now_playing = night[self._find(night, item_id)]
        self._split_around_current(night)
        self.is_playing = True
        self.version += 1
        return True

    def clear(self) -> None:
        self.played = []
        self.now_playing = None
        self.queue = []
        self.is_playing = False
        self.version += 1

    def set_playing(self, playing: bool) -> None:
        if self.now_playing is None or self.is_playing == playing:
            return
        self.is_playing = playing
        self.version += 1

    def snapshot(self) -> RoomState:
        return RoomState(
            played=list(self.played),
            now_playing=self.now_playing,
            queue=list(self.queue),
            is_playing=self.is_playing,
            version=self.version,
        )

    def save(self) -> None:
        """Write the night to `store_path` atomically, so a crash mid-write can't corrupt it."""
        if self.store_path is None:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.store_path.parent, prefix=".room-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(self.snapshot().model_dump_json())
            os.replace(tmp, self.store_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _load(self) -> None:
        """Restore a saved night, always paused so a restart never starts music on its own."""
        if self.store_path is None or not self.store_path.is_file():
            return
        try:
            state = RoomState.model_validate_json(self.store_path.read_text())
        except (OSError, ValueError, ValidationError) as e:
            log.warning("Ignoring unreadable room file %s: %s", self.store_path, e)
            return
        self.played = state.played
        self.now_playing = state.now_playing
        self.queue = state.queue
        self.version = state.version

    def _night(self) -> list[QueueItem]:
        return self.played + ([self.now_playing] if self.now_playing else []) + self.queue

    @staticmethod
    def _find(night: list[QueueItem], item_id: str) -> int:
        for i, item in enumerate(night):
            if item.id == item_id:
                return i
        raise KeyError(item_id)

    def _split_around_current(self, night: list[QueueItem]) -> None:
        """Re-derive played/upcoming from the night's order and the song playing."""
        if self.now_playing is None:
            self.played, self.queue = night, []
            return
        k = self._find(night, self.now_playing.id)
        self.played, self.queue = night[:k], night[k + 1:]
