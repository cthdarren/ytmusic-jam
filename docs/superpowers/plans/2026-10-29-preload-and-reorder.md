# Preload Ahead + Whole-Night Reordering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two things:
- Preload the next 20 songs, nearest first, and keep the downloads short-term.
- Let anyone drag any song in the night (played, current or upcoming) to any position, while the current song keeps playing.

**Architecture:**
- **Reordering:** `Room.move(item_id, to_index)` now indexes the whole night (`played + [now_playing] + queue`). After the move, the list is split again around `now_playing`, so that song keeps playing, and the songs before it count as played and the songs after it as upcoming.
- **Preloading:** a single `Preloader` owned by the app keeps a priority list (the current song, then upcoming songs in order, up to `JAM_PRELOAD_SONGS`). Two workers always take the nearest song that isn't cached yet. The host's own `/api/audio` request bypasses the preloader, so the current song never waits.
- **Storage:** downloads are short-term. The LRU cap stays, files unused for 24 h are deleted, and Clear queue empties the cache.

**Spec (user's words):**
- "is it possible to add preloading of the following songs in the queue? bandwidth is not an issue. As long as these songs are short term stored and not long term to take up space"
- "create a new branch for the preloading feature, and set the default to 20. It should be preloading songs that are closer to being played first"
- "i also want to be able to rearrange songs in the queue including the songs that have already been played previously … I want to also be able to move the current playing song higher up or lower down the queue, while keeping the song playing"
- Agreed earlier (assistant proposal, user proceeded): Clear queue empties the song cache, and files untouched for 24 hours are deleted.

## Global Constraints

- `JAM_PRELOAD_SONGS` defaults to `20` and counts upcoming songs, so the current song is preloaded on top of that.
- Preload concurrency is `2`. Priority order is `now_playing`, then `queue[0]`, `queue[1]`, and so on.
- A failed preload isn't retried for 5 minutes, or until the song moves into the wanted list again after a Clear.
- Cache cap: `JAM_AUDIO_CACHE_MB` (500). Files whose mtime is older than 24 h are deleted even when under the cap. The current song and the preload list are never evicted.
- Move indexes refer to the whole night and are clamped to `[0, len(night) - 1]`. A move never changes `now_playing` or `is_playing`.
- `remove` works for played and upcoming songs. Removing `now_playing` raises `ValueError`, and the API returns 409 `"Skip the song that's playing instead of removing it"`.

## Review Focus

1. **Dragging the current song.** It must keep playing: no reload on the host, no `is_playing` flip (Task 1 `test_move_current_keeps_it_playing`).
2. **Dragging a played song below the current one.** It plays again later in that exact order (Task 1 `test_move_played_song_after_current_makes_it_upcoming`).
3. **Quickly reprioritised preloads.** After a jump or reorder, the new nearest songs come first and stale ones aren't started (Task 2 `test_reprioritises_after_update`).
4. **A permanently unavailable song in the preload list.** It isn't retried in a hot loop (Task 2 `test_failed_song_not_retried_immediately`).
5. **Clear queue.** It frees the disk (Task 3 `test_clear_empties_audio_cache`).

---

### Task 1: Whole-night move and remove (backend)

**Files:** `backend/app/room.py`, `backend/app/main.py`, `backend/tests/test_room.py`, `backend/tests/test_api.py`

**Interfaces:**
- `Room.move(item_id: str, to_index: int) -> None`: the index is a whole-night index. Raises `KeyError` for an unknown id.
- `Room.remove(item_id: str) -> None`: removes from `played` or `queue`. Raises `ValueError` for `now_playing` and `KeyError` for an unknown id.
- The move API body is unchanged (`{"to_index": int}`), but the index is now a whole-night index. Remove gains the 409.

- [ ] Tests:
  - Update `test_move`, `test_move_clamps_index`, `test_move_and_remove_ignore_played_ids` and `test_move_reorders` to the whole-night semantics.
  - Add `test_move_current_keeps_it_playing`, `test_move_played_song_after_current_makes_it_upcoming`, `test_move_upcoming_before_current_marks_it_played`, `test_move_when_nothing_playing`, `test_remove_played_song`, `test_remove_current_raises` and `test_remove_current_returns_409`.
- [ ] Run (FAIL), implement, run (PASS), commit `feat(backend): reorder and remove anywhere in the night`.

### Task 2: `Preloader` (backend)

**Files:** `backend/app/audio.py` (Preloader, `AudioCache.prune(keep, max_age_seconds)`, `AudioCache.clear()`), `backend/tests/test_audio.py`

**Interfaces:**
- `Preloader(cache: AudioCache, concurrency: int = 2, retry_after: float = 300)`:
  - `update(wanted: list[str]) -> None`, called from the event loop; `wanted` is in priority order.
  - `async close()`.
  - Workers start lazily on the first `update`.
- `AudioCache.prune(keep: set[str], max_age_seconds: float = 86400)` and `AudioCache.clear() -> None`.

- [ ] Tests (fake downloader; concurrency 1 where order matters):
  - `test_preloads_in_priority_order`
  - `test_reprioritises_after_update`
  - `test_failed_song_not_retried_immediately`
  - `test_prunes_to_wanted_when_idle`
  - `test_prune_deletes_stale_files`
  - `test_clear_removes_everything`
- [ ] Run (FAIL), implement, run (PASS), commit `feat(backend): preload upcoming songs nearest first`.

### Task 3: Wire it up (backend)

**Files:** `backend/app/settings.py`, `backend/app/main.py`, `backend/tests/test_api.py`, `backend/tests/test_auth.py`, `.env.example`, `README.md`

- [ ] Add `Settings.preload_songs: int = 20` (env `JAM_PRELOAD_SONGS`).
- [ ] In `changed()`, call `preloader.update([now] + queue[:preload_songs])`, replacing the old `prefetch`.
- [ ] Clear queue calls `audio.clear()`.
- [ ] Tests:
  - `test_change_preloads_upcoming_in_order` (replaces `test_change_prefetches_current_and_next`)
  - `test_preload_count_respected`
  - `test_clear_empties_audio_cache`
  - extend `test_settings_cookie_and_cache_env`
- [ ] Commit `feat: preload 20 songs ahead; Clear queue frees the song cache`.

### Task 4: Whole-night drag and drop (frontend)

**Files:** `frontend/src/components/QueueDrawer.tsx`, `QueueDrawer.test.tsx`, `index.css`, `README.md`

- [ ] One `SortableContext` over every id in night order. Every row gets a drag handle. Played and upcoming rows get ✕ (the current row doesn't).
- [ ] `onMove(id, wholeNightIndex)`.
- [ ] Optimistic order keyed to the props.
- [ ] Tests:
  - `every song has a drag handle`
  - `the playing song has no remove button`
  - `played songs can be removed`
  - `reorder` tests unchanged
- [ ] Commit `feat(frontend): drag any song in the night, including the one playing`.
