# Night Playlist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the "Recently played" feature. Replace the queue with one list holding every song of the night, with a now-playing marker. Tapping any song jumps playback to it without reordering the list. Only the owner gets a "Clear queue" button, and it asks for confirmation first.

**Architecture:** `Room` keeps the night as three consecutive slices: `played` (oldest first), `now_playing`, and `queue` (upcoming). Together they form one ordered list, and the boundary between them is the cursor. Advancing, jumping and adding only move that boundary; they never reorder the list. Reordering and removing still apply only to `queue`, and that code is unchanged. The room is saved to `data_dir/room.json` after every change, so only "Clear queue" wipes it.

**Tech Stack:** Same as the existing app: FastAPI + pydantic and pytest (backend); React + TypeScript, @dnd-kit and vitest (frontend).

**Spec:** No separate doc. The user's words in this conversation:
- "Revert whatever changes you made previously to main." The user chose to reset `main` to `391194f`, which drops the two Recently played commits.
- "The queue should show every single song ever played that night."
- "Pressing on a song in the queue skips to that song, while maintaining the order to the queue at that time." On going back, the user chose **"Carry on down the list"**: tapping song 3 plays 3, 4, 5, 6, 7, 8.
- "Leave the rearranging function alone as that is perfect now."
- The list clears "every time the host presses on clear queue. This button should only be available to the host. Additionally, there should be a pop up for confirmation since this is a very risky action."

## Global Constraints

- The single uvicorn worker, plain-HTTP LAN constraints and snake_case API from the original plan (`docs/superpowers/plans/2026-10-28-ytmusic-jam.md`) still apply.
- Do not change the reorder behaviour: `POST /api/queue/{id}/move` keeps `to_index` relative to the upcoming `queue`, and the drag-and-drop code in `QueueDrawer.tsx` stays as it is.
- "Host" in the spec means the `owner` role. Clearing is enforced on the server: guests get a 403.
- Anyone in the jam (owner or guest) can jump to a song, just as anyone can Skip.
- The night list has no length limit ("every single song").
- Room file: `settings.data_dir / "room.json"`. Writes are atomic (write a temp file in the same dir, then `os.replace`). A missing or corrupt file means an empty room, never a crash. After loading, `is_playing` is always `False`.
- Confirmation copy (exact): title `Clear the whole queue?`, body `This removes every song from tonight's list, including the one playing now. This can't be undone.`, buttons `Cancel` / `Clear everything`.

## Review Focus

1. **Long nights on a phone.** With 150+ songs, opening the queue must land on the now-playing row, not the top of the night (Task 4 `scrolls the now-playing row into view on open`).
2. **Restart mid-party.** After `docker compose restart`, the list comes back intact and paused, and nothing plays until someone presses play (Task 2 `test_reload_restores_lists_paused`, Task 3 `test_room_survives_app_restart`).
3. **Corrupt or half-written `room.json`.** The app starts with an empty night instead of crash-looping (Task 2 `test_corrupt_store_starts_empty`).
4. **Tapping the song that's already playing.** Nothing happens: it doesn't restart, skip or bump the version (Task 1 `test_jump_to_current_is_noop`, Task 4 `tapping the now-playing row does nothing`).
5. **A guest calling clear directly.** `POST /api/queue/clear` with a guest cookie returns 403 and the list stays (Task 3 `test_clear_is_owner_only`).

---

## File Structure

```
backend/app/models.py     RoomState gains `played`
backend/app/room.py       played slice, advance→played, jump(), clear(), save()/load
backend/app/main.py       POST /api/queue/{id}/play, POST /api/queue/clear (owner), Room(store_path), save on change
backend/tests/test_room.py  test_api.py
frontend/src/types.ts     RoomState.played
frontend/src/api.ts       playItem(), clearQueue()
frontend/src/components/QueueDrawer.tsx   one list: played + now playing + sortable upcoming; tap to jump; Clear button
frontend/src/components/ConfirmDialog.tsx new, reusable confirm modal
frontend/src/App.tsx      wiring
frontend/src/index.css    played/now-playing row styles, dialog
README.md                 feature bullets
```

---

### Task 1: Revert, branch, and the night-list model in `Room`

**Files:** Modify `backend/app/models.py`, `backend/app/room.py`, `backend/tests/test_room.py`. Create `docs/superpowers/plans/2026-10-28-night-playlist.md` (a copy of this plan).

**Interfaces:**
- Produces: `RoomState(played: list[QueueItem], now_playing: QueueItem | None, queue: list[QueueItem], is_playing: bool, version: int)`. `played` is oldest first.
- Produces `Room` methods:
  - `advance(expected_item_id) -> bool`: on success, appends the old `now_playing` (if any) to `played`. Everything else stays as it is now.
  - `jump(item_id: str) -> bool`: builds the full list as `played + [now_playing] + queue` (leaving out `now_playing` if it's None), finds the target index `k`, then sets `played = L[:k]`, `now_playing = L[k]`, `queue = L[k+1:]` and `is_playing = True`. Returns False with no change (no version bump) if the target is already `now_playing`. Raises `KeyError` if the id isn't anywhere in the list.
  - `clear() -> None`: empties all three slices, sets `is_playing = False` and bumps the version.
  - `remove` and `move` still look only in `queue`, so ids in `played` or the current id raise `KeyError`.

- [ ] **Step 1: Revert and branch.** `git checkout main && git reset --hard 391194f` (the user approved this reset; nothing has been pushed). Then `git checkout -b feat/night-playlist`. Copy this plan into `docs/superpowers/plans/`. Expected: `git log --oneline -1` shows `391194f fix: keep auto-advance playing…`.
- [ ] **Step 2: Write the failing tests** in `test_room.py` (uses the existing `t()` and `room_with()` helpers):
  - `test_advance_moves_current_to_played`: with a, b, c and `advance(a.id)` → played `[a]`, now playing `b`, queue `[c]`.
  - `test_last_song_ending_goes_to_played`: → played `[a]`, `now_playing is None`.
  - `test_add_after_list_finished_plays_new_song`: played is kept, the new item is `now_playing`, and `is_playing` is True.
  - `test_jump_back_carries_on_down_the_list`: with i1..i8, advance until i7 plays, then `jump(i3)` → played `[i1, i2]`, now playing `i3`, queue `[i4..i8]`, `is_playing` True.
  - `test_jump_forward_passes_over_songs`: now playing a, queue b, c, d; `jump(c)` → played `[a, b]`, now playing `c`, queue `[d]`.
  - `test_jump_keeps_list_order`: after several jumps, `[ids of played + now + queue]` equals the original order.
  - `test_jump_after_list_finished`: every song played and nothing playing; `jump(first)` works.
  - `test_jump_to_current_is_noop`: returns False and the version is unchanged.
  - `test_jump_unknown_raises`, `test_jump_resumes_when_paused`.
  - `test_move_and_remove_ignore_played_ids`: both raise `KeyError` for a played id.
  - `test_clear_empties_everything`.
- [ ] **Step 3: Run** `cd backend && timeout 120 uv run pytest -q tests/test_room.py`. Expected: the new tests FAIL (`AttributeError` for jump/clear, or assertion errors).
- [ ] **Step 4: Implement** as described under Interfaces.
- [ ] **Step 5: Run** `timeout 120 uv run pytest -q`. Expected: everything passes except `test_api.py::test_state_starts_empty` (it now needs `"played": []`). Update that expected dict here, since the field is part of this task.
- [ ] **Step 6: Commit** `feat(backend): night list with played songs, jump and clear`.

---

### Task 2: Persist the room across restarts

**Files:** Modify `backend/app/room.py` and `backend/tests/test_room.py`.

**Interfaces:**
- Produces: `Room(store_path: Path | None = None)`. If the file exists and is valid, it loads `played`, `now_playing`, `queue` and `version` from it, with `is_playing = False`.
- Produces: `Room.save() -> None`, which writes `snapshot().model_dump_json()` atomically. It does nothing when `store_path` is None.

- [ ] **Step 1: Write the failing tests** (use `tmp_path`):
  - `test_reload_restores_lists_paused`: add 3 songs, advance once, `save()`. A new `Room(path)` has the same played, now and queue ids, and `is_playing is False`.
  - `test_missing_store_starts_empty`
  - `test_corrupt_store_starts_empty`: write `"{not json"` → empty room, no exception.
  - `test_clear_then_save_persists_empty`
  - `test_no_store_path_never_writes`: `Room().save()` creates no files in `tmp_path`.
- [ ] **Step 2: Run.** Expected: FAIL (TypeError on `store_path`). **Step 3: Implement.** Catch `OSError`/`ValueError` on load and log a warning with `logging.getLogger(__name__)`. **Step 4: Run** `uv run pytest -q`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat(backend): save the night list to data_dir/room.json`.

---

### Task 3: API: jump, owner-only clear, saving on change

**Files:** Modify `backend/app/main.py` and `backend/tests/test_api.py`.

**Interfaces:**
- Consumes: `Room.jump`, `Room.clear`, `Room.save`, `Room(store_path)` (Tasks 1–2), and the existing `require_owner` and `changed()` in `main.py`.
- Produces:
  - `POST /api/queue/{item_id}/play` (any session): returns `RoomState`. 404 `"That song is no longer in the queue"`. When `jump` returns False, it returns the snapshot without broadcasting.
  - `POST /api/queue/clear` (`require_owner`): returns `RoomState`. 403 for guests, 401 for anyone not logged in.
  - `create_app` builds `Room(settings.data_dir / "room.json")`.
  - `changed()` calls `room.save()` before broadcasting.

- [ ] **Step 1: Write the failing tests:**
  - `test_play_item_jumps_back`: queue 3 songs, call next twice, POST play on the first → it's `now_playing`, and played/queue are as in Task 1.
  - `test_play_unknown_returns_404`
  - `test_clear_is_owner_only`: a guest (use `test_auth.become_guest`-style setup in `conftest`, or the cookie-swap helper) gets 403 and the list is intact. The owner gets 200 with all lists empty.
  - `test_clear_requires_session`: anon → 401.
  - `test_room_survives_app_restart`: two `create_app` instances with the same `settings`. The second sees the same lists, paused.
  - `test_ws_broadcasts_jump`: a ws client receives a state whose `now_playing` is the tapped item.
- [ ] **Step 2: Run.** Expected: FAIL (404/405 on the new routes). **Step 3: Implement.** Declare `/api/queue/clear` before the `{item_id}` routes so FastAPI matches it first. **Step 4: Run** `uv run pytest -q`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat(backend): tap-to-play and owner-only clear endpoints`.

---

### Task 4: Frontend: one night list, tap to jump, Clear with confirmation

**Files:**
- Modify `frontend/src/types.ts`, `api.ts`, `components/QueueDrawer.tsx`, `components/QueueDrawer.test.tsx`, `App.tsx`, `index.css` and `README.md`.
- Create `components/ConfirmDialog.tsx`.

**Interfaces:**
- Consumes: the Task 3 endpoints.
- Produces:
  - `types.ts`: `RoomState.played: QueueItem[]`.
  - `api.ts`: `playItem(id: string): Promise<RoomState>` and `clearQueue(): Promise<RoomState>`.
  - `ConfirmDialog({ title, message, confirmLabel, onConfirm, onCancel })`: a modal with `role="alertdialog"` and the buttons `Cancel` and `confirmLabel` (styled `danger`).
  - `QueueDrawer` props: `{ open, played, nowPlaying, items, isOwner, onClose, onRemove, onMove, onPlay(id), onClear() }`. `items` is still the upcoming queue; the `reorder()` export and the sortable rows are unchanged.
- UI:
  - One `<ul>` in list order: played rows (dimmed), then the now-playing row (highlighted, `aria-current="true"`, "Now playing" label), then the upcoming sortable rows (drag handle + ✕ as now).
  - Each played and upcoming row's track area is a `<button aria-label="Play {title}">` that calls `onPlay(id)`. The now-playing row has no such button.
  - On open, the now-playing row gets `scrollIntoView({ block: 'center' })` (call it optionally, since jsdom doesn't implement it).
  - The header shows `Clear queue` only if `isOwner` and the night isn't empty. It opens the ConfirmDialog with the exact copy from Global Constraints, and confirming calls `onClear()`.
  - The `Queue (n)` button still counts upcoming songs.
  - App passes `played = state.played`, `nowPlaying = state.now_playing`, `isOwner = role === 'owner'`, `onPlay → api.playItem`, `onClear → api.clearQueue`.

- [ ] **Step 1: Write the failing tests** in `QueueDrawer.test.tsx`. Update the existing renders to pass the new props (played `[]`, nowPlaying `null`, isOwner `false`, no-op handlers), then add:
  - `renders the whole night in order`: played P1 and P2, now N, upcoming U1 and U2 → listitem titles in order `['P1','P2','N','U1','U2']`, and N's row has `aria-current="true"`.
  - `tapping a played song plays it`: click `Play P1` → `onPlay('p1')`.
  - `tapping an upcoming song plays it`: click `Play U2` → `onPlay('u2')`.
  - `tapping the now-playing row does nothing`: there is no `Play N` button.
  - `scrolls the now-playing row into view on open`: stub `Element.prototype.scrollIntoView = vi.fn()` and expect it to have been called.
  - `only the owner sees Clear queue`: absent when `isOwner` is false, present when true.
  - `Clear asks for confirmation`: click `Clear queue` → an alertdialog with the exact title. `Cancel` → `onClear` not called and the dialog is gone. Reopen and click `Clear everything` → `onClear` called once.
  - `shows the empty message when the night is empty`.
- [ ] **Step 2: Run** `cd frontend && npm test`. Expected: the new tests FAIL. **Step 3: Implement** using the existing `TrackInfo` component for every row. **Step 4: Run** `npm test && npm run build`. Expected: all PASS and the build succeeds.
- [ ] **Step 5: README.** Replace the Queue bullet with: the queue shows the whole night (played songs dimmed above the current one); tap any song to jump to it, and playback carries on down the list; drag to reorder upcoming songs; the host's **Clear queue** wipes the night after a confirmation; the list survives restarts and comes back paused.
- [ ] **Step 6: Manual smoke check.** Run the backend on a scratch port with a scratch `JAM_DATA_DIR`. Use curl to add 3 songs, call next twice, play the first, then clear as a guest (expect 403) and as the owner (expect 200 and empty lists). Restart the server between steps and confirm the list persists, paused.
- [ ] **Step 7: Commit** `feat(frontend): whole-night queue with tap-to-play and confirmed clear`.
