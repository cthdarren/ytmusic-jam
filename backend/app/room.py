from app.models import QueueItem, RoomState, Track


class Room:
    """The jam's playback state. Synchronous; callers keep it on one thread.

    The night is one ordered list split into `played`, `now_playing` and `queue`.
    Advancing and jumping only move the split point; they never reorder the list.
    """

    def __init__(self) -> None:
        self.played: list[QueueItem] = []
        self.now_playing: QueueItem | None = None
        self.queue: list[QueueItem] = []
        self.is_playing = False
        self.version = 0

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
        self.queue.pop(self._index(item_id))
        self.version += 1

    def move(self, item_id: str, to_index: int) -> None:
        item = self.queue.pop(self._index(item_id))
        to_index = max(0, min(to_index, len(self.queue)))
        self.queue.insert(to_index, item)
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
        night = self.played + ([self.now_playing] if self.now_playing else []) + self.queue
        index = next((i for i, item in enumerate(night) if item.id == item_id), None)
        if index is None:
            raise KeyError(item_id)
        self.played = night[:index]
        self.now_playing = night[index]
        self.queue = night[index + 1:]
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

    def _index(self, item_id: str) -> int:
        for i, item in enumerate(self.queue):
            if item.id == item_id:
                return i
        raise KeyError(item_id)
