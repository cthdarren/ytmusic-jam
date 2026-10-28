from app.models import QueueItem, RoomState, Track


class Room:
    """The jam's playback state. Synchronous; callers keep it on one thread."""

    def __init__(self) -> None:
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
        if self.queue:
            self.now_playing = self.queue.pop(0)
        else:
            self.now_playing = None
            self.is_playing = False
        self.version += 1
        return True

    def set_playing(self, playing: bool) -> None:
        if self.now_playing is None or self.is_playing == playing:
            return
        self.is_playing = playing
        self.version += 1

    def snapshot(self) -> RoomState:
        return RoomState(
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
