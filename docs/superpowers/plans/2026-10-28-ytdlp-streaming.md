# yt-dlp Audio Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Play every song through server-side yt-dlp audio instead of the YouTube IFrame embed, so label-blocked songs play too. Use the owner's Premium cookies when provided, and send only audio.

**Architecture:** The backend downloads each track's best audio stream with yt-dlp, using the owner's YouTube cookies if `cookies.txt` exists, into a size-capped cache in `data_dir/audio-cache`. It serves the file at `GET /api/audio/{video_id}`, where Starlette's `FileResponse` handles byte ranges for seeking. Whenever the room changes, it starts background downloads of the current and next song. `/host` swaps the YT player for an `<audio>` element. Room, queue and phone UI are unchanged.

**Tech Stack:** `yt-dlp[default]` (needs a JS runtime: deno), FastAPI `FileResponse`, HTML `<audio>`.

**Spec:** From the conversation:
- "lets do yt-dlp for everything, this way we can also save bandwidth from the video from embed? maybe?"
- "either way put it in a separate branch to test first"
- Earlier: the user has YouTube Premium; the trigger was https://music.youtube.com/watch?v=AfeV_OZmHvM (an ATV "Art Track", IZ*ONE Violeta) being auto-skipped by the embed.

**Spike results (this machine, no cookies):**
- `yt_dlp.extract_info` resolves Violeta: format 251 (opus, about 130 kbps, webm, 3.27 MB), in 3.4 s.
- googlevideo requests **without** a byte range are throttled to about 2× real time (100 s for 3.2 MB). Ranged requests take 0.3 s.
- yt-dlp's own downloader uses ranged chunks, so the plan is to download with yt-dlp and serve the files locally.

## Global Constraints

- This change is on branch `feat/ytdlp-streaming` only; it merges only after the user has tested it.
- It replaces the original constraint "No audio is downloaded or proxied … IFrame API only" (the user's decision).
- Cookies come from `JAM_COOKIES_FILE` (default `data_dir/cookies.txt`), Netscape format, used only if the file exists. Without cookies, playback still works (anonymous quality). They are never logged or served.
- Audio cache: `data_dir/audio-cache/`, capped by `JAM_AUDIO_CACHE_MB` (default `500`), evicting the least recently used files first. Never evict the current or next song.
- Format selector: `bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio`.
- yt-dlp calls are serialized (one at a time) because the cookie file is rewritten when yt-dlp closes. Concurrent requests for the same video share one download.
- `/api/audio/{video_id}` requires a session and checks the id against `^[A-Za-z0-9_-]{11}$`. The server only ever fetches URLs that yt-dlp resolves, never ones a user supplies.
- The Docker image ships deno, and its build step upgrades yt-dlp to the latest release so that `docker compose build --no-cache` picks up YouTube fixes.

## Review Focus

1. **A song YouTube won't give us** (removed, private, or a region block). The host skips it with a toast instead of stalling (Task 1 `test_ensure_unavailable_raises`, Task 2 `test_audio_unavailable_returns_404`, Task 3 `error event skips`).
2. **Two clients requesting the same song at once** (host plus prefetch). Only one download runs (Task 1 `test_concurrent_ensure_downloads_once`).
3. **Cache growth over a long night.** Eviction stays under the cap but never evicts the current or next song (Task 1 `test_prune_evicts_lru_but_keeps_pinned`).
4. **Song end vs pause.** The `<audio>` element fires `pause` just before `ended`, and that must not pause the room (Task 3, existing `shouldReportPause` near-end rule kept).
5. **Path tricks on `/api/audio/`.** `../`, overlong ids and the like get 400/404 and never touch the filesystem outside the cache (Task 2 `test_audio_rejects_bad_ids`).

---

### Task 1: `AudioCache` (backend)

**Files:** Create `backend/app/audio.py` and `backend/tests/test_audio.py`.

**Interfaces:**
- Produces:
  - `class AudioUnavailable(Exception)`.
  - `Downloader = Callable[[str, Path, Path | None], Path]`, called as `(video_id, dest_dir, cookies_file)` and returning the downloaded file's path.
  - `ytdlp_download(video_id, dest_dir, cookies_file) -> Path`, the real downloader. It uses yt-dlp with the format selector above, `outtmpl=dest_dir/"%(id)s.%(ext)s"`, `cookiefile` if one is given, `quiet`, and `noplaylist`. It maps `yt_dlp.utils.DownloadError` to `AudioUnavailable`.
  - `class AudioCache(cache_dir: Path, cookies_file: Path | None, max_bytes: int, downloader: Downloader = ytdlp_download)` with:
    - `cached(video_id) -> Path | None`
    - `async ensure(video_id) -> Path`: downloads in a threadpool if the file isn't cached. One global lock serializes downloads, and a per-id in-flight future dedupes concurrent requests. It touches the file's mtime when it's used.
    - `prune(keep: set[str]) -> None`

- [ ] Tests (fake downloader that writes N bytes and counts calls):
  - `test_ensure_downloads_once_then_serves_cache`
  - `test_concurrent_ensure_downloads_once`
  - `test_ensure_unavailable_raises`
  - `test_cookies_passed_only_when_file_exists`
  - `test_prune_evicts_lru_but_keeps_pinned`
  - `test_partial_files_ignored` (`*.part` is never treated as cached)
- [ ] Run (expect FAIL), implement, run (expect PASS). Commit `feat(backend): yt-dlp audio cache`.

### Task 2: `/api/audio/{video_id}` + prefetch + settings

**Files:** Modify `backend/app/settings.py`, `backend/app/main.py` and `backend/tests/{conftest,test_api,test_auth}.py`.

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `Settings.cookies_file: Path | None` and `Settings.audio_cache_mb: int = 500`.
  - `create_app(..., audio: AudioCache | None = None)`.
  - `GET /api/audio/{video_id}`: `FileResponse` with the right media type (`audio/webm` or `audio/mp4`). 400 for a bad id, 404 for `AudioUnavailable`, 401 without a session.
  - After each `changed()`, prefetches the current and next song with `asyncio.create_task`, swallowing and logging errors, and prunes with those two kept.
- [ ] Tests:
  - `test_audio_serves_file_with_ranges`: a `Range: bytes=0-9` request returns 206 and 10 bytes.
  - `test_audio_requires_session`, `test_audio_rejects_bad_ids`, `test_audio_unavailable_returns_404`
  - `test_change_prefetches_current_and_next`
  - `test_settings_cookie_and_cache_env`
- [ ] Run (FAIL), implement, run (PASS). Commit `feat(backend): serve cached audio and prefetch upcoming songs`.

### Task 3: Host player on `<audio>`

**Files:** Modify `frontend/src/components/HostPlayer.tsx`, `frontend/src/hostPlayerLogic.ts`, `frontend/src/hostPlayerLogic.test.ts`, `frontend/tsconfig.app.json` and `frontend/package.json`; remove `@types/youtube`.

**Interfaces:**
- Produces in `hostPlayerLogic.ts`:
  - `onPlayerEvent(event: {kind:'ended'} | {kind:'error'}, nowPlayingId)` → `{call:'next', expected}` or null. Any audio error skips, because yt-dlp failures are not transient on retry.
  - `shouldReportPause({ paused, roomPlaying, currentTime, duration })` and `shouldReportPlay({ paused, roomPlaying })`, based on the `<audio>` element's `paused` flag instead of YT states.
  - `audioUrl(videoId) -> string` = `/api/audio/${videoId}`.
- Behaviour:
  - "Start jam" still unlocks autoplay.
  - On a now-playing change: set `src`, then `play()` if the room is playing.
  - Shows album art, title and artist, plus a "Loading…" state until `canplay`.
  - `ended` → next. `error` → toast "Couldn't play {title} — skipping", then next.
  - Native play/pause is debounced and reported, as today.
- [ ] Update the tests for the new signatures, run (FAIL), implement, run, then `npm run build`. Commit `feat(frontend): play audio from the server instead of the YouTube embed`.

### Task 4: Docker, README, live check

- [ ] Dockerfile:
  - `COPY --from=denoland/deno:bin-<pinned> /deno /usr/local/bin/deno`
  - after `uv sync`, run `uv pip install --upgrade "yt-dlp[default]"`
- [ ] `.env.example`: add `JAM_AUDIO_CACHE_MB` and a cookies note.
- [ ] README:
  - how to export `cookies.txt` (a private window signed into music.youtube.com, a cookies.txt export extension, saved to `./data/cookies.txt`, window closed afterwards)
  - Premium quality
  - updating yt-dlp with `docker compose build --no-cache`
  - the YouTube-terms caveat
- [ ] Live check on a scratch port, without cookies: add Violeta, `curl` `/api/audio/AfeV_OZmHvM` with and without a Range header, confirm the cache file exists and that the next song gets prefetched. Then `docker compose build` and repeat the curl check in the container.
- [ ] Commit `chore: ship deno + latest yt-dlp in the image; document cookies`.
