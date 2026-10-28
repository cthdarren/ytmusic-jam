# Faster Preloading + Ready Marks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preload 4 songs at a time, and show in the queue which songs are already downloaded and will start instantly.

**Architecture:**
- **Speed:** `Preloader` concurrency comes from settings (default 4).
- **Notifications:** `AudioCache` gets an `on_change` callback that fires when a download finishes, when prune deletes files, and on clear. `main` responds by broadcasting `{"type": "ready", "video_ids": [...]}` over the existing WebSocket, and sends it on connect too.
- **Display:** `useRoom` keeps a `ready: Set<string>`, and `QueueDrawer` marks each row as ready or preparing. `RoomState` and `room.json` stay unchanged: readiness is a cache fact, not room state.

**Spec (user):**
- Diagnosis agreed with the user: preloading works, but right after a restart (or for songs just added or moved) songs aren't downloaded yet. Downloads take about 5–8 s each, two at a time.
- Proposal accepted: "1. More downloads at once (2 → 4) … 2. A 'ready' mark in the queue: a small indicator on each song that's already downloaded".
- User: "4 at a time is good".

## Global Constraints

- `JAM_PRELOAD_WORKERS` defaults to `4`.
- Ready message: `{"type": "ready", "video_ids": [<sorted ids of cached songs>]}`. It is sent on WebSocket connect (after the state message) and whenever the set changes. No message is sent if the set is unchanged.
- Row indicator: a ready song shows `aria-label="Ready to play"`, a song that isn't ready shows `aria-label="Downloading…"`. Show it on every row (played, playing, upcoming).

## Review Focus

1. **A download finishing with no room change.** The ready mark still appears (Task 1 `test_ws_ready_updates_when_download_finishes`).
2. **Prune or clear deleting files.** The marks go away (Task 1 `test_ws_ready_updates_after_clear`).
3. **Older clients and message types.** `useRoom` must ignore unknown messages and keep handling `state` (Task 2 `ready messages update the set`).

---

### Task 1: Backend — 4 workers, cache change notifications, ready broadcasts

**Files:** `backend/app/audio.py`, `backend/app/hub.py`, `backend/app/main.py`, `backend/app/settings.py`, tests (`test_audio.py`, `test_api.py`, `test_auth.py`), `.env.example`, `README.md`

**Interfaces:**
- `AudioCache.on_change: Callable[[], None] | None`. It is called after a successful download, after prune deletes at least one file, and after clear deletes at least one file.
- `AudioCache.ready_ids() -> set[str]`.
- `Hub.broadcast_message(msg: dict)` and `Hub.send_message(ws, msg)`.
- `Settings.preload_workers: int = 4` (env `JAM_PRELOAD_WORKERS`).

- [ ] Tests:
  - `test_on_change_called_after_download_prune_and_clear`
  - `test_ready_ids`
  - `test_ws_sends_ready_on_connect`
  - `test_ws_ready_updates_when_download_finishes`
  - `test_ws_ready_updates_after_clear`
  - `test_preload_workers_setting` (4 workers start; a fake downloader with a delay shows 4 running at once)
  - extend the settings env test
- [ ] Run (FAIL), implement, run (PASS), commit.

### Task 2: Frontend — ready set + row indicator

**Files:** `frontend/src/useRoom.ts`, `frontend/src/App.tsx`, `frontend/src/components/QueueDrawer.tsx`, tests, `index.css`

**Interfaces:**
- `useRoom(): { state, connected, ready: Set<string> }`. A message handler `applyMessage(msg, setState, setReady)` is exported for tests.
- `QueueDrawer` gets a `ready: Set<string>` prop.

- [ ] Tests:
  - `ready messages update the set`, plus an unknown message type that is ignored
  - `rows show ready vs downloading`
- [ ] Run (FAIL), implement, run (PASS), build, commit.
