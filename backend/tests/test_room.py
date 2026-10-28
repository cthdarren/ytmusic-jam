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


def order(room: Room) -> list[str]:
    """Ids of the whole night in list order: played, now playing, upcoming."""
    s = room.snapshot()
    return [i.id for i in s.played] + ([s.now_playing.id] if s.now_playing else []) + [i.id for i in s.queue]


def test_advance_moves_current_to_played():
    room, (a, b, c) = room_with(0, 1, 2)
    room.advance(a.id)
    s = room.snapshot()
    assert [i.id for i in s.played] == [a.id]
    assert s.now_playing.id == b.id
    assert [i.id for i in s.queue] == [c.id]


def test_last_song_ending_goes_to_played():
    room, (a,) = room_with(0)
    room.advance(a.id)
    s = room.snapshot()
    assert [i.id for i in s.played] == [a.id]
    assert s.now_playing is None


def test_add_after_list_finished_plays_new_song():
    room, (a,) = room_with(0)
    room.advance(a.id)
    b = room.add(t(1), None)
    s = room.snapshot()
    assert [i.id for i in s.played] == [a.id]
    assert s.now_playing.id == b.id
    assert s.is_playing is True


def test_jump_back_carries_on_down_the_list():
    room, items = room_with(*range(1, 9))
    for item in items[:6]:
        room.advance(item.id)
    assert room.snapshot().now_playing.id == items[6].id
    assert room.jump(items[2].id) is True
    s = room.snapshot()
    assert [i.id for i in s.played] == [items[0].id, items[1].id]
    assert s.now_playing.id == items[2].id
    assert [i.id for i in s.queue] == [i.id for i in items[3:]]
    assert s.is_playing is True


def test_jump_forward_passes_over_songs():
    room, (a, b, c, d) = room_with(0, 1, 2, 3)
    room.jump(c.id)
    s = room.snapshot()
    assert [i.id for i in s.played] == [a.id, b.id]
    assert s.now_playing.id == c.id
    assert [i.id for i in s.queue] == [d.id]


def test_jump_keeps_list_order():
    room, items = room_with(*range(6))
    original = [i.id for i in items]
    for target in (items[4], items[1], items[5], items[0], items[3]):
        room.jump(target.id)
        assert order(room) == original


def test_jump_after_list_finished():
    room, (a, b) = room_with(0, 1)
    room.advance(a.id)
    room.advance(b.id)
    assert room.snapshot().now_playing is None
    room.jump(a.id)
    s = room.snapshot()
    assert s.now_playing.id == a.id
    assert [i.id for i in s.queue] == [b.id]
    assert s.is_playing is True


def test_jump_to_current_is_noop():
    room, (a, _) = room_with(0, 1)
    v = room.snapshot().version
    assert room.jump(a.id) is False
    assert room.snapshot().version == v


def test_jump_unknown_raises():
    room, _ = room_with(0, 1)
    with pytest.raises(KeyError):
        room.jump("nope")


def test_jump_resumes_when_paused():
    room, (_, b) = room_with(0, 1)
    room.set_playing(False)
    room.jump(b.id)
    assert room.snapshot().is_playing is True


def test_move_and_remove_ignore_played_ids():
    room, (a, _, _) = room_with(0, 1, 2)
    room.advance(a.id)
    with pytest.raises(KeyError):
        room.move(a.id, 0)
    with pytest.raises(KeyError):
        room.remove(a.id)


def test_clear_empties_everything():
    room, (a, _, _) = room_with(0, 1, 2)
    room.advance(a.id)
    v = room.snapshot().version
    room.clear()
    s = room.snapshot()
    assert (s.played, s.now_playing, s.queue, s.is_playing) == ([], None, [], False)
    assert s.version == v + 1


def test_reload_restores_lists_paused(tmp_path):
    path = tmp_path / "room.json"
    room = Room(path)
    a, b, c = (room.add(t(n), "Sam") for n in range(3))
    room.advance(a.id)
    room.save()
    restored = Room(path)
    s = restored.snapshot()
    assert [i.id for i in s.played] == [a.id]
    assert s.now_playing.id == b.id
    assert s.now_playing.added_by == "Sam"
    assert [i.id for i in s.queue] == [c.id]
    assert s.is_playing is False
    assert s.version == room.snapshot().version


def test_missing_store_starts_empty(tmp_path):
    s = Room(tmp_path / "room.json").snapshot()
    assert (s.played, s.now_playing, s.queue, s.version) == ([], None, [], 0)


def test_corrupt_store_starts_empty(tmp_path):
    path = tmp_path / "room.json"
    path.write_text("{not json")
    s = Room(path).snapshot()
    assert (s.played, s.now_playing, s.queue) == ([], None, [])


def test_clear_then_save_persists_empty(tmp_path):
    path = tmp_path / "room.json"
    room = Room(path)
    room.add(t(0), None)
    room.save()
    room.clear()
    room.save()
    assert Room(path).snapshot().now_playing is None


def test_save_leaves_no_temp_files(tmp_path):
    room = Room(tmp_path / "room.json")
    room.add(t(0), None)
    room.save()
    assert [p.name for p in tmp_path.iterdir()] == ["room.json"]


def test_no_store_path_never_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    room = Room()
    room.add(t(0), None)
    room.save()
    assert list(tmp_path.iterdir()) == []
