import pytest

from app.models import Track
from app.room import Room


def t(n: int) -> Track:
    return Track(video_id=f"vid{n:08d}", title=f"Song {n}", artist="Artist",
                 duration_seconds=200, thumbnail_url=None)


def room_with(*ns: int) -> tuple[Room, list]:
    room = Room()
    items = [room.add(t(n), None) for n in ns]
    return room, items


def test_first_add_starts_playing():
    room = Room()
    room.add(t(1), "me")
    state = room.snapshot()
    assert state.now_playing.track == t(1)
    assert state.now_playing.added_by == "me"
    assert state.queue == []
    assert state.is_playing is True


def test_later_adds_queue_in_order():
    room, _ = room_with(1, 2, 3)
    assert [i.track for i in room.snapshot().queue] == [t(2), t(3)]


def test_same_song_twice_gets_distinct_ids():
    room, (a, b) = room_with(1, 1)
    assert a.id != b.id


def test_remove():
    room, (_, a, b) = room_with(0, 1, 2)
    room.remove(a.id)
    assert [i.id for i in room.snapshot().queue] == [b.id]


def test_remove_unknown_raises():
    room, _ = room_with(0, 1)
    with pytest.raises(KeyError):
        room.remove("nope")


def test_move():
    room, (_, a, b, c) = room_with(0, 1, 2, 3)
    room.move(c.id, 0)
    assert [i.id for i in room.snapshot().queue] == [c.id, a.id, b.id]


def test_move_clamps_index():
    room, (_, a, b, c) = room_with(0, 1, 2, 3)
    room.move(a.id, 99)
    assert [i.id for i in room.snapshot().queue] == [b.id, c.id, a.id]
    room.move(c.id, -5)
    assert [i.id for i in room.snapshot().queue] == [c.id, b.id, a.id]


def test_move_unknown_raises():
    room, _ = room_with(0, 1)
    with pytest.raises(KeyError):
        room.move("nope", 0)


def test_advance_pops_next():
    room, (cur, a, b) = room_with(0, 1, 2)
    assert room.advance(cur.id) is True
    state = room.snapshot()
    assert state.now_playing.id == a.id
    assert [i.id for i in state.queue] == [b.id]


def test_advance_ignores_stale_expected_id():
    room, (cur, a, b) = room_with(0, 1, 2)
    assert room.advance(cur.id) is True
    assert room.advance(cur.id) is False
    state = room.snapshot()
    assert state.now_playing.id == a.id
    assert [i.id for i in state.queue] == [b.id]


def test_advance_on_empty_queue_stops():
    room, (cur,) = room_with(0)
    assert room.advance(cur.id) is True
    state = room.snapshot()
    assert state.now_playing is None
    assert state.is_playing is False


def test_set_playing():
    room, _ = room_with(0)
    room.set_playing(False)
    assert room.snapshot().is_playing is False


def test_set_playing_noop_when_idle():
    room = Room()
    room.set_playing(True)
    assert room.snapshot().is_playing is False
    assert room.snapshot().version == 0


def test_version_increments_only_on_change():
    room, (cur,) = room_with(0)
    v = room.snapshot().version
    assert room.advance("stale") is False
    assert room.snapshot().version == v
    room.advance(cur.id)
    assert room.snapshot().version == v + 1


def test_advance_resumes_playback_when_next_song_exists():
    room, (cur, _) = room_with(0, 1)
    room.set_playing(False)
    room.advance(cur.id)
    assert room.snapshot().is_playing is True
